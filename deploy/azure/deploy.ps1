<#
Deploys the Clara phone server to Azure App Service (Linux, Python 3.12).
Secrets from .env (API keys, Twilio token, webhook key, live-view password) are stored in an
Azure Key Vault; the app reads them through Key Vault references. Safe to re-run: use it again
to push code or .env setting changes (including new key values).

Usage:  .\deploy\azure\deploy.ps1 -AppName clara-<something-unique>
#>
param(
    [Parameter(Mandatory = $true)][string]$AppName,
    [string]$ResourceGroup = "clara-rg",
    [string]$Location = "eastus",
    # F1 (Free) works on a new trial subscription; B1 needs Basic quota but supports Always On.
    [string]$Sku = "F1",
    [string]$Vault = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$plan = "$AppName-plan"

. "$PSScriptRoot\common.ps1"

$settings = Read-DotEnv (Join-Path $root ".env")
$provider = if ($settings["LLM_PROVIDER"]) { $settings["LLM_PROVIDER"].ToLower() } else { "anthropic" }
$required = @("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "PHONE_WEBHOOK_KEY", "LIVE_VIEW_PASSWORD")
$required += switch ($provider) {
    "anthropic" { @("ANTHROPIC_API_KEY") }
    "azure_openai" { @("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT") }
    default { throw "Unknown LLM_PROVIDER '$provider' in .env (use anthropic or azure_openai)" }
}
$missing = @($required | Where-Object { -not $settings[$_] })
if ($missing.Count -gt 0) { throw "Set these in .env before deploying: $($missing -join ', ')" }

# Optional settings are sent only when present. AZURE_OPENAI_REASONING_EFFORT is sent even when
# empty, because empty deliberately turns reasoning effort off (for non-reasoning models).
$optional = "LLM_PROVIDER", "ANTHROPIC_MODEL"
$present = @(($required + $optional) | Where-Object { $settings[$_] })
# Every secret in .env goes to the vault, including the unused provider's key, so switching
# LLM_PROVIDER later needs no other change.
$secrets = @{}
foreach ($name in $SecretSettings | Where-Object { $settings[$_] }) { $secrets[$name] = $settings[$name] }
$appSettings = @($present | Where-Object { $SecretSettings -notcontains $_ } |
    ForEach-Object { @{ name = $_; value = $settings[$_]; slotSetting = $false } })
if ($settings.ContainsKey("AZURE_OPENAI_REASONING_EFFORT")) {
    $appSettings += @{ name = "AZURE_OPENAI_REASONING_EFFORT"; value = $settings["AZURE_OPENAI_REASONING_EFFORT"]; slotSetting = $false }
}
Write-Host "Model provider: $provider"
$appSettings += @{ name = "SCM_DO_BUILD_DURING_DEPLOYMENT"; value = "true"; slotSetting = $false }

Write-Host "1/6 Resource group '$ResourceGroup' in $Location"
Invoke-Az group create --name $ResourceGroup --location $Location -o none | Out-Null

Write-Host "2/6 App Service plan '$plan' ($Sku, Linux)"
Invoke-Az appservice plan create --resource-group $ResourceGroup --name $plan --is-linux --sku $Sku -o none | Out-Null

Write-Host "3/6 Web app '$AppName'"
Invoke-Az webapp create --resource-group $ResourceGroup --plan $plan --name $AppName --runtime "PYTHON:3.12" -o none | Out-Null

if (-not $Vault) { $Vault = Get-DefaultVaultName }
Write-Host "4/6 Secrets to Key Vault '$Vault', other settings to the app (values not printed)"
$vaultId = Initialize-Vault $Vault $ResourceGroup
Grant-AppVaultAccess webapp $ResourceGroup $AppName $vaultId
$appSettings += Sync-VaultSecrets $Vault $secrets
Write-AppSettings webapp $ResourceGroup $AppName $appSettings

$alwaysOn = if ($Sku -eq "F1") { "false" } else { "true" }
Write-Host "5/6 Startup command, Always On ($alwaysOn), HTTPS only"
# One worker: calls and the live feed live in memory, so every request must reach the same process.
Invoke-Az webapp config set --resource-group $ResourceGroup --name $AppName --always-on $alwaysOn -o none `
    --startup-file "gunicorn --bind=0.0.0.0:8000 --workers=1 --threads=16 --timeout=120 hcm_agent.telephony.server:app"
Invoke-Az webapp update --resource-group $ResourceGroup --name $AppName --https-only true -o none | Out-Null
Invoke-Az webapp log config --resource-group $ResourceGroup --name $AppName --docker-container-logging filesystem -o none | Out-Null

Write-Host "6/6 Uploading code (Azure installs the requirements; this takes a few minutes)"
$zip = Join-Path $env:TEMP "clara-app.zip"
python (Join-Path $PSScriptRoot "package.py") $zip
if ($LASTEXITCODE -ne 0) { throw "Packaging the app failed" }
try {
    Invoke-Az webapp deploy --resource-group $ResourceGroup --name $AppName --src-path $zip --type zip -o none | Out-Null
} finally {
    Remove-Item $zip -ErrorAction SilentlyContinue
}

$url = "https://$AppName.azurewebsites.net"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Live view: $url/live"
Write-Host "Place a call: clara-call --url $url --to +1XXXXXXXXXX --name <FirstName>"

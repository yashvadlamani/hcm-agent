<#
Deploys the Clara phone server to Azure App Service (Linux, Python 3.12).
Safe to re-run: use it again to push code or .env setting changes.

Usage:  .\deploy\azure\deploy.ps1 -AppName clara-<something-unique>
#>
param(
    [Parameter(Mandatory = $true)][string]$AppName,
    [string]$ResourceGroup = "clara-rg",
    [string]$Location = "eastus",
    # F1 (Free) works on a new trial subscription; B1 needs Basic quota but supports Always On.
    [string]$Sku = "F1"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$plan = "$AppName-plan"

function Invoke-Az {
    # Azure occasionally reports a just-updated resource as missing for a few seconds, so retry.
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & az @args --only-show-errors
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -lt 3) { Write-Host "  retrying in 15s..."; Start-Sleep -Seconds 15 }
    }
    # Only the command name goes in the error, never the arguments (they can contain secrets).
    throw "Azure CLI step failed: az $($args[0]) $($args[1])"
}

$settings = @{}
foreach ($line in Get-Content (Join-Path $root ".env")) {
    if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') { $settings[$Matches[1]] = $Matches[2].Trim().Trim('"') }
}
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
$appSettings = @(($required + $optional) | Where-Object { $settings[$_] } |
    ForEach-Object { @{ name = $_; value = $settings[$_]; slotSetting = $false } })
if ($settings.ContainsKey("AZURE_OPENAI_REASONING_EFFORT")) {
    $appSettings += @{ name = "AZURE_OPENAI_REASONING_EFFORT"; value = $settings["AZURE_OPENAI_REASONING_EFFORT"]; slotSetting = $false }
}
Write-Host "Model provider: $provider"
$appSettings += @{ name = "SCM_DO_BUILD_DURING_DEPLOYMENT"; value = "true"; slotSetting = $false }

Write-Host "1/6 Resource group '$ResourceGroup' in $Location"
Invoke-Az group create --name $ResourceGroup --location $Location --output none

Write-Host "2/6 App Service plan '$plan' ($Sku, Linux)"
Invoke-Az appservice plan create --resource-group $ResourceGroup --name $plan --is-linux --sku $Sku --output none

Write-Host "3/6 Web app '$AppName'"
Invoke-Az webapp create --resource-group $ResourceGroup --plan $plan --name $AppName --runtime "PYTHON:3.12" --output none

Write-Host "4/6 App settings from .env ($($appSettings.Count) values; not printed)"
$settingsFile = Join-Path $env:TEMP "clara-appsettings-$([guid]::NewGuid()).json"
try {
    ConvertTo-Json -InputObject $appSettings | Set-Content -Path $settingsFile -Encoding ascii
    Invoke-Az webapp config appsettings set --resource-group $ResourceGroup --name $AppName --settings "@$settingsFile" --output none
} finally {
    Remove-Item $settingsFile -ErrorAction SilentlyContinue
}

$alwaysOn = if ($Sku -eq "F1") { "false" } else { "true" }
Write-Host "5/6 Startup command, Always On ($alwaysOn), HTTPS only"
# One worker: calls and the live feed live in memory, so every request must reach the same process.
Invoke-Az webapp config set --resource-group $ResourceGroup --name $AppName --always-on $alwaysOn --output none `
    --startup-file "gunicorn --bind=0.0.0.0:8000 --workers=1 --threads=16 --timeout=120 hcm_agent.telephony.server:app"
Invoke-Az webapp update --resource-group $ResourceGroup --name $AppName --https-only true --output none
Invoke-Az webapp log config --resource-group $ResourceGroup --name $AppName --docker-container-logging filesystem --output none

Write-Host "6/6 Uploading code (Azure installs the requirements; this takes a few minutes)"
$zip = Join-Path $env:TEMP "clara-app.zip"
python (Join-Path $PSScriptRoot "package.py") $zip
if ($LASTEXITCODE -ne 0) { throw "Packaging the app failed" }
try {
    Invoke-Az webapp deploy --resource-group $ResourceGroup --name $AppName --src-path $zip --type zip --output none
} finally {
    Remove-Item $zip -ErrorAction SilentlyContinue
}

$url = "https://$AppName.azurewebsites.net"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Live view: $url/live"
Write-Host "Place a call: clara-call --url $url --to +1XXXXXXXXXX --name <FirstName>"

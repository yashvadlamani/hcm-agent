<#
Shared helpers for the deploy scripts. Dot-source it:  . "$PSScriptRoot\common.ps1"

Secrets live in an Azure Key Vault. The deploy scripts copy them there from .env and give each
app a Key Vault reference instead of the value, so the apps read them from the vault.
#>

# Settings that are secrets: stored in Key Vault, never as plain app settings.
$SecretSettings = @(
    "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY", "ACS_CONNECTION_STRING",
    "PHONE_WEBHOOK_KEY", "LIVE_VIEW_PASSWORD", "CallRequestsStorage"
)

# Settings from earlier versions (Twilio) that the deploy scripts remove from the apps.
$RetiredSettings = @("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER")

# Call the Azure CLI's Python directly: az.cmd goes through cmd.exe, which breaks on characters
# like '&' in arguments.
$script:azPython = Join-Path (Split-Path (Get-Command az).Source) "..\python.exe"

function Invoke-Az {
    # Azure occasionally reports a just-changed resource as missing for a few seconds, so retry.
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $out = & $script:azPython -IBm azure.cli @args --only-show-errors
        if ($LASTEXITCODE -eq 0) { return $out }
        if ($attempt -lt 3) { Write-Host "  retrying in 15s..."; Start-Sleep -Seconds 15 }
    }
    # Only the command name goes in the error, never the arguments (they can contain secrets).
    throw "Azure CLI step failed: az $($args[0]) $($args[1]) $($args[2])"
}

# For lookups that may legitimately fail (resource not created yet): returns the output, or
# nothing on error. PowerShell 5.1 would otherwise turn the CLI's stderr into a fatal error.
function Get-AzOptional {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $script:azPython -IBm azure.cli @args --only-show-errors 2>$null
        if ($LASTEXITCODE -eq 0) { return $out }
    } catch {
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([A-Z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $values[$Matches[1]] = $Matches[2].Trim().Trim('"') }
    }
    return $values
}

# Vault names are global: derive a stable one from the subscription ID.
function Get-DefaultVaultName {
    $subId = (Invoke-Az account show --query id -o tsv).Trim()
    return "clara-kv-" + ($subId -replace '-', '').Substring(0, 12)
}

# Creates the vault if needed (Azure RBAC permissions) and lets the signed-in user manage secrets.
function Initialize-Vault([string]$Vault, [string]$ResourceGroup) {
    $vaultId = Get-AzOptional keyvault show -n $Vault --query id -o tsv
    if (-not $vaultId) {
        # A new subscription must opt in to Key Vault once (takes a minute or two).
        $state = Get-AzOptional provider show -n Microsoft.KeyVault --query registrationState -o tsv
        if ("$state".Trim() -ne "Registered") {
            Write-Host "  registering Key Vault on this subscription (one time)..."
            Invoke-Az provider register -n Microsoft.KeyVault --wait | Out-Null
        }
        $location = (Invoke-Az group show -n $ResourceGroup --query location -o tsv).Trim()
        $vaultId = Invoke-Az keyvault create -n $Vault -g $ResourceGroup -l $location `
            --enable-rbac-authorization true --retention-days 7 --query id -o tsv
    }
    $vaultId = "$vaultId".Trim()
    $me = (Invoke-Az ad signed-in-user show --query id -o tsv).Trim()
    Grant-VaultRole $vaultId $me "User" "Key Vault Secrets Officer"
    return $vaultId
}

function Grant-VaultRole([string]$VaultId, [string]$PrincipalId, [string]$PrincipalType, [string]$Role) {
    $existing = Get-AzOptional role assignment list --assignee $PrincipalId --role $Role --scope $VaultId --query "[0].id" -o tsv
    if (-not $existing) {
        Invoke-Az role assignment create --assignee-object-id $PrincipalId --assignee-principal-type $PrincipalType `
            --role $Role --scope $VaultId -o none | Out-Null
    }
}

# Gives the app ($Kind: webapp or functionapp) its own Azure identity and lets it read secrets.
function Grant-AppVaultAccess([string]$Kind, [string]$ResourceGroup, [string]$App, [string]$VaultId) {
    $principal = (Invoke-Az $Kind identity assign -g $ResourceGroup -n $App --query principalId -o tsv).Trim()
    Grant-VaultRole $VaultId $principal "ServicePrincipal" "Key Vault Secrets User"
}

# Writes each secret to the vault and returns app settings that reference them. Values go through
# a temporary file so they never appear on a command line.
function Sync-VaultSecrets([string]$Vault, [hashtable]$Values) {
    $references = @()
    $file = Join-Path $env:TEMP "clara-secret-$([guid]::NewGuid()).txt"
    try {
        foreach ($name in $Values.Keys) {
            $secretName = $name.Replace("_", "-")   # Key Vault names allow letters, digits and '-'
            $current = Get-AzOptional keyvault secret show --vault-name $Vault -n $secretName --query value -o tsv
            if ("$current".Trim() -ne $Values[$name]) {
                [IO.File]::WriteAllText($file, $Values[$name])
                # A new role assignment can take a minute or two to apply, so allow extra time.
                $saved = $false
                for ($attempt = 1; $attempt -le 8 -and -not $saved; $attempt++) {
                    Get-AzOptional keyvault secret set --vault-name $Vault -n $secretName --file $file --encoding utf-8 -o none | Out-Null
                    $saved = ($LASTEXITCODE -eq 0)
                    if (-not $saved) { Write-Host "  waiting for vault access..."; Start-Sleep -Seconds 20 }
                }
                if (-not $saved) { throw "Couldn't save secret '$secretName' to Key Vault '$Vault'" }
            }
            $references += @{ name = $name; value = "@Microsoft.KeyVault(VaultName=$Vault;SecretName=$secretName)"; slotSetting = $false }
        }
    } finally {
        Remove-Item $file -ErrorAction SilentlyContinue
    }
    # Changing a setting makes the app re-read every secret right away instead of within 24 hours.
    $references += @{ name = "SECRETS_SYNCED_AT"; value = (Get-Date).ToUniversalTime().ToString("o"); slotSetting = $false }
    return $references
}

function Remove-RetiredSettings([string]$Kind, [string]$ResourceGroup, [string]$App) {
    Invoke-Az $Kind config appsettings delete -g $ResourceGroup -n $App --setting-names @RetiredSettings -o none | Out-Null
}

function Write-AppSettings([string]$Kind, [string]$ResourceGroup, [string]$App, [array]$AppSettings) {
    $file = Join-Path $env:TEMP "clara-appsettings-$([guid]::NewGuid()).json"
    try {
        ConvertTo-Json -InputObject $AppSettings | Set-Content -Path $file -Encoding ascii
        Invoke-Az $Kind config appsettings set -g $ResourceGroup -n $App --settings "@$file" -o none | Out-Null
    } finally {
        Remove-Item $file -ErrorAction SilentlyContinue
    }
}

# Lets GitHub Actions deploy the app: turns on publish-profile (basic) deployment auth and,
# when $Path is given, writes the publish profile there. The file is a secret: add it to GitHub,
# then delete it. Uses the ARM API because the CLI's export doesn't support Flex Consumption.
function Export-PublishProfile([string]$ResourceGroup, [string]$App, [string]$Path) {
    Invoke-Az resource update -g $ResourceGroup --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies `
        --parent "sites/$App" -n scm --set properties.allow=true -o none | Out-Null
    if ($Path) {
        $siteId = (Invoke-Az webapp show -g $ResourceGroup -n $App --query id -o tsv).Trim()
        Invoke-Az rest --method post --url "https://management.azure.com$siteId/publishxml?api-version=2024-04-01" `
            --output-file $Path | Out-Null
        Write-Host "  Publish profile written to $Path (a secret: add it to GitHub, then delete the file)."
    }
}

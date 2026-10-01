<#
Deploys the call-request Azure Function: uploading a JSON file to the storage container
`call-requests` under `incoming/` makes Clara place a test call.

Creates (or updates) in the resource group:
  - a storage account with the private `call-requests` container
  - a Flex Consumption Function App (Python 3.12) running functions/function_app.py
  - an Event Grid subscription that triggers the function for each new incoming/*.json
Secrets (ACS connection string, webhook key, storage connection) go to the Key Vault shared with the Clara
server; the Function app reads them through Key Vault references.

Safe to re-run: use it again to push code or .env setting changes. GitHub Actions
(.github/workflows/deploy-function.yml) can also redeploy the code on every push.

Usage:
  .\deploy\azure\deploy_function.ps1 -FunctionApp clara-hcm-agent-calls -ClaraAppName clara-hcm-agent-demo
#>
param(
    [Parameter(Mandatory = $true)][string]$FunctionApp,
    [Parameter(Mandatory = $true)][string]$ClaraAppName,
    [string]$ResourceGroup = "clara-rg",
    [string]$Location = "centralus",
    [string]$StorageAccount = "",
    [string]$Vault = "",
    [string]$PublishProfilePath = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$container = "call-requests"
$functionName = "call_request"

. "$PSScriptRoot\common.ps1"

$settings = Read-DotEnv (Join-Path $root ".env")
$required = "ACS_CONNECTION_STRING", "ACS_PHONE_NUMBER", "ACS_COGNITIVE_SERVICES_ENDPOINT", "PHONE_WEBHOOK_KEY", "ALLOWED_CALL_NUMBERS"
$missing = @($required | Where-Object { -not $settings[$_] })
if ($missing.Count -gt 0) { throw "Set these in .env before deploying: $($missing -join ', ')" }

if (-not $StorageAccount) {
    # Storage account names are global: derive a stable one from the subscription ID.
    $subId = (Invoke-Az account show --query id -o tsv).Trim()
    $StorageAccount = "clarahcm" + ($subId -replace '-', '').Substring(0, 12)
}
if (-not $Vault) { $Vault = Get-DefaultVaultName }
$claraUrl = "https://$ClaraAppName.azurewebsites.net"

Write-Host "1/7 Storage account '$StorageAccount' and container '$container'"
Invoke-Az storage account create -g $ResourceGroup -n $StorageAccount -l $Location --sku Standard_LRS --kind StorageV2 `
    --min-tls-version TLS1_2 --allow-blob-public-access false -o none | Out-Null
Invoke-Az storage container create --account-name $StorageAccount --auth-mode key -n $container -o none | Out-Null
# A placeholder keeps incoming/ visible between uploads (blob storage has no real folders).
Invoke-Az storage blob upload --account-name $StorageAccount --auth-mode key -c $container -n incoming/README.txt `
    -f (Join-Path $root "functions\incoming_README.txt") --overwrite true -o none | Out-Null
$connection = (Invoke-Az storage account show-connection-string -g $ResourceGroup -n $StorageAccount --query connectionString -o tsv).Trim()

Write-Host "2/7 Function app '$FunctionApp' (Flex Consumption, Python 3.12)"
$exists = Get-AzOptional functionapp show -g $ResourceGroup -n $FunctionApp --query name -o tsv
if (-not $exists) {
    Invoke-Az functionapp create -g $ResourceGroup -n $FunctionApp --storage-account $StorageAccount `
        --flexconsumption-location $Location --runtime python --runtime-version 3.12 -o none | Out-Null
}

Write-Host "3/7 Secrets to Key Vault '$Vault', other settings to the app (values not printed)"
$vaultId = Initialize-Vault $Vault $ResourceGroup
Grant-AppVaultAccess functionapp $ResourceGroup $FunctionApp $vaultId
$secrets = @{ CallRequestsStorage = $connection }
$appSettings = @(@{ name = "CLARA_BASE_URL"; value = $claraUrl; slotSetting = $false })
foreach ($name in $required + "MAX_CALLS_PER_HOUR") {
    if (-not $settings[$name]) { continue }
    if ($SecretSettings -contains $name) { $secrets[$name] = $settings[$name] }
    else { $appSettings += @{ name = $name; value = $settings[$name]; slotSetting = $false } }
}
$appSettings += Sync-VaultSecrets $Vault $secrets
Write-AppSettings functionapp $ResourceGroup $FunctionApp $appSettings
Remove-RetiredSettings functionapp $ResourceGroup $FunctionApp

Write-Host "4/7 Uploading code (Azure installs the requirements; this takes a few minutes)"
$zip = Join-Path $env:TEMP "clara-function.zip"
python (Join-Path $PSScriptRoot "package_function.py") $zip
if ($LASTEXITCODE -ne 0) { throw "Packaging the function failed" }
try {
    Invoke-Az functionapp deployment source config-zip -g $ResourceGroup -n $FunctionApp --src $zip --build-remote true -o none | Out-Null
} finally {
    Remove-Item $zip -ErrorAction SilentlyContinue
}

Write-Host "5/7 Waiting for the function's blob-trigger key"
$blobKey = ""
for ($i = 0; $i -lt 24 -and -not $blobKey; $i++) {
    $blobKey = Get-AzOptional functionapp keys list -g $ResourceGroup -n $FunctionApp `
        --query systemKeys.blobs_extension -o tsv
    if (-not $blobKey) { Start-Sleep -Seconds 10 }
}
if (-not $blobKey) { throw "The function didn't start (no blobs_extension key). Check its logs in the Azure portal." }

Write-Host "6/7 Event Grid: trigger the function for each new $container/incoming/*.json"
$topic = "$StorageAccount-events"
$storageId = (Invoke-Az storage account show -g $ResourceGroup -n $StorageAccount --query id -o tsv).Trim()
$topicExists = Get-AzOptional eventgrid system-topic show -g $ResourceGroup -n $topic --query name -o tsv
if (-not $topicExists) {
    Invoke-Az eventgrid system-topic create -g $ResourceGroup -n $topic -l $Location `
        --topic-type Microsoft.Storage.StorageAccounts --source $storageId -o none | Out-Null
}
$endpoint = "https://$FunctionApp.azurewebsites.net/runtime/webhooks/blobs?functionName=Host.Functions.$functionName&code=$blobKey"
Invoke-Az eventgrid system-topic event-subscription create -g $ResourceGroup --system-topic-name $topic `
    -n "call-requests-incoming" --endpoint $endpoint --endpoint-type webhook `
    --included-event-types Microsoft.Storage.BlobCreated `
    --subject-begins-with "/blobServices/default/containers/$container/blobs/incoming/" --subject-ends-with ".json" `
    -o none | Out-Null

Write-Host "7/7 Deployment access for GitHub Actions"
Export-PublishProfile $ResourceGroup $FunctionApp $PublishProfilePath

Write-Host ""
Write-Host "Done. To place a test call, upload a JSON file to incoming/, for example:"
Write-Host "  az storage blob upload --account-name $StorageAccount --auth-mode key -c $container -n incoming/test.json -f request.json"
Write-Host "Results appear in $container/processed/ or $container/failed/."

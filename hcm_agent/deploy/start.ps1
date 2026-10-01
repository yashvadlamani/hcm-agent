<#
Turns the Clara app back on. With -Sku B1 (needs Basic quota) it also moves the plan to B1
and turns Always On back on; the default F1 (Free) tier just starts the app.

Usage:  .\hcm_agent\deploy\start.ps1 -AppName clara-<your-app> [-Sku B1]
#>
param(
    [Parameter(Mandatory = $true)][string]$AppName,
    [string]$ResourceGroup = "clara-rg",
    [string]$Sku = "F1"
)
$ErrorActionPreference = "Stop"

function Invoke-Az {
    & az @args --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI step failed: az $($args[0]) $($args[1])" }
}

Write-Host "Starting '$AppName' on $Sku"
Invoke-Az appservice plan update --resource-group $ResourceGroup --name "$AppName-plan" --sku $Sku --output none
if ($Sku -ne "F1") {
    Invoke-Az webapp config set --resource-group $ResourceGroup --name $AppName --always-on true --output none
}
Invoke-Az webapp start --resource-group $ResourceGroup --name $AppName --output none
Write-Host "Running at https://$AppName.azurewebsites.net (allow about a minute to warm up)."

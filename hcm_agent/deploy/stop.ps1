<#
Turns the Clara app off and makes sure its plan is on the Free tier, so it uses no credit.
A stopped app on a paid plan is still billed, which is why this also changes the tier
(a no-op when the plan is already on F1).

Usage:  .\hcm_agent\deploy\stop.ps1 -AppName clara-<your-app>
#>
param(
    [Parameter(Mandatory = $true)][string]$AppName,
    [string]$ResourceGroup = "clara-rg"
)
$ErrorActionPreference = "Stop"

function Invoke-Az {
    & az @args --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI step failed: az $($args[0]) $($args[1])" }
}

Write-Host "Stopping '$AppName'"
Invoke-Az webapp stop --resource-group $ResourceGroup --name $AppName --output none
Invoke-Az webapp config set --resource-group $ResourceGroup --name $AppName --always-on false --output none
Invoke-Az appservice plan update --resource-group $ResourceGroup --name "$AppName-plan" --sku F1 --output none
Write-Host "Stopped. The plan is on the Free tier. Run start.ps1 to turn it back on."

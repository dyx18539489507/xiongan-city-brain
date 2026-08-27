[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

$workspace = Split-Path -Parent $PSScriptRoot
$sumoGui = Join-Path $workspace '.tools\sumo\bin\sumo-gui.exe'
$viewSettings = Join-Path $workspace 'scenarios\source\xiongan_rongdong_20\simple-shapes.view.xml'
$resolvedConfig = [System.IO.Path]::GetFullPath($ConfigPath)

foreach ($requiredFile in @($sumoGui, $viewSettings, $resolvedConfig)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required SUMO file was not found: $requiredFile"
    }
}

$sumoArguments = '-c "{0}" --gui-settings-file "{1}" --delay 200' -f $resolvedConfig, $viewSettings

Start-Process `
    -FilePath $sumoGui `
    -ArgumentList $sumoArguments `
    -WorkingDirectory (Split-Path -Parent $resolvedConfig)

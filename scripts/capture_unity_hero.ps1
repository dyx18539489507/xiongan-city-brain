param([switch]$SkipConfigure)

$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$unity = Join-Path $workspace '.tools\unity\6000.3.9f1\Editor\Unity.exe'
$project = Join-Path $workspace 'apps\unity-digital-twin'
$log = Join-Path $workspace 'outputs\3d\runtime\unity-hero-preview.log'
$preview = Join-Path $workspace 'outputs\3d\audit\latest-hero-preview.png'
$junctionPreview = Join-Path $workspace 'outputs\3d\audit\latest-b01-monitor.png'
$overviewPreview = Join-Path $workspace 'outputs\3d\audit\latest-city-overview.png'
$cameraAssets = Join-Path $workspace 'apps\web-dashboard\public\assets\cameras'

if (-not (Test-Path -LiteralPath $unity)) { throw "Unity is not installed at $unity" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

$process = Start-Process -FilePath $unity -ArgumentList @(
    '-batchmode',
    '-quit',
    '-job-worker-count', '1',
    '-projectPath', "`"$project`"",
    '-executeMethod', $(if ($SkipConfigure) { 'Xiongan.DigitalTwin.Editor.XionganBuildPipeline.CaptureHeroPreview' } else { 'Xiongan.DigitalTwin.Editor.XionganBuildPipeline.ConfigureAndCapture' }),
    '-logFile', "`"$log`""
) -WindowStyle Hidden -Wait -PassThru

if ($process.ExitCode -ne 0 -or
    -not (Test-Path -LiteralPath $preview) -or
    -not (Test-Path -LiteralPath $junctionPreview) -or
    -not (Test-Path -LiteralPath $overviewPreview)) {
    throw "Unity hero preview failed (exit=$($process.ExitCode)). See $log"
}

New-Item -ItemType Directory -Force -Path $cameraAssets | Out-Null
Copy-Item -LiteralPath $preview -Destination (Join-Path $cameraAssets 'hero.png') -Force
Copy-Item -LiteralPath $junctionPreview -Destination (Join-Path $cameraAssets 'junction.png') -Force
Copy-Item -LiteralPath $overviewPreview -Destination (Join-Path $cameraAssets 'overview.png') -Force

Write-Host "Unity hero preview captured at $preview and camera assets refreshed in $cameraAssets"

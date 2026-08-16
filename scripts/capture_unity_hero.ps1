$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$unity = Join-Path $workspace '.tools\unity\6000.3.9f1\Editor\Unity.exe'
$project = Join-Path $workspace 'apps\unity-digital-twin'
$log = Join-Path $workspace 'outputs\3d\runtime\unity-hero-preview.log'
$preview = Join-Path $workspace 'outputs\3d\audit\latest-hero-preview.png'

if (-not (Test-Path -LiteralPath $unity)) { throw "Unity is not installed at $unity" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

$process = Start-Process -FilePath $unity -ArgumentList @(
    '-batchmode',
    '-quit',
    '-job-worker-count', '1',
    '-projectPath', "`"$project`"",
    '-executeMethod', 'Xiongan.DigitalTwin.Editor.XionganBuildPipeline.CaptureHeroPreview',
    '-logFile', "`"$log`""
) -WindowStyle Hidden -Wait -PassThru

if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $preview)) {
    throw "Unity hero preview failed (exit=$($process.ExitCode)). See $log"
}

Write-Host "Unity hero preview captured at $preview"

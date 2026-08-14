$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$unityRoot = Join-Path $workspace '.tools\unity'
$unity = Join-Path $unityRoot '6000.3.9f1\Editor\Unity.exe'
$project = Join-Path $workspace 'apps\unity-digital-twin'
$logs = Join-Path $unityRoot 'logs'
$buildLog = Join-Path $logs 'unity-webgl-build.log'
$webIndex = Join-Path $workspace 'apps\web-dashboard\public\unity\index.html'

if (-not (Test-Path -LiteralPath $unity)) { throw "Unity is not installed at $unity" }
New-Item -ItemType Directory -Force -Path $logs,(Join-Path $unityRoot 'cache\upm'),(Join-Path $unityRoot 'cache\npm') | Out-Null

$env:UPM_CACHE_ROOT = Join-Path $unityRoot 'cache\upm'
$env:UPM_NPM_CACHE_PATH = Join-Path $unityRoot 'cache\npm'

$unityProcess = Start-Process -FilePath $unity -ArgumentList @(
    '-batchmode',
    '-quit',
    '-job-worker-count', '1',
    '-projectPath', "`"$project`"",
    '-executeMethod', 'Xiongan.DigitalTwin.Editor.XionganBuildPipeline.ConfigureAndBuild',
    '-logFile', "`"$buildLog`""
) -WindowStyle Hidden -Wait -PassThru
$unityExitCode = $unityProcess.ExitCode
$logText = if (Test-Path -LiteralPath $buildLog) { Get-Content -Raw -LiteralPath $buildLog } else { '' }
$fatalPatterns = 'No valid Unity Editor license|Scripts have compiler errors|Compilation failed|BuildFailedException|Build completed with a result of ''Failed'''
if ($unityExitCode -ne 0 -or $logText -match $fatalPatterns) {
    throw "Unity WebGL build failed (exit=$unityExitCode). See $buildLog"
}
if (-not (Test-Path -LiteralPath $webIndex) -or $logText -notmatch 'Unity WebGL build complete') {
    throw "Unity exited without a verified WebGL artifact. See $buildLog"
}

Write-Host "Unity WebGL build completed in apps\web-dashboard\public\unity"

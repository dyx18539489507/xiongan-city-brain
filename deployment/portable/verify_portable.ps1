[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 5187
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$requiredFiles = @(
    'runtime\python\python.exe',
    'runtime\sumo\bin\sumo.exe',
    'web\index.html',
    'web\unity\index.html',
    'web\unity\Build\unity.loader.js',
    'generated\scenes\xiongan_rongdong_20.scene.json',
    'scenarios\generated\xiongan_rongdong_20\xiongan_rongdong_20.sumocfg',
    'scenarios\source\hebei-2026-08-21.osm.pbf',
    'scenarios\source\hebei-2026-08-21-roads.sqlite',
    'START_PLATFORM.cmd',
    'src\traffic_platform\api\app.py'
)
foreach ($relative in $requiredFiles) {
    $path = Join-Path $workspace $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required file: $relative" }
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Self-test port $Port is in use. Run .\verify_portable.ps1 -Port 5197"
}

$pythonVersionOutput = & (Join-Path $workspace 'runtime\python\python.exe') --version 2>&1
$pythonExitCode = $LASTEXITCODE
if ($pythonExitCode -ne 0) { throw 'Portable Python failed to start.' }
$pythonVersion = $pythonVersionOutput | Select-Object -First 1

# Windows PowerShell 5.1 can terminate a native process early when its output
# is piped into Select-Object -First, producing a false non-zero exit code.
$sumoVersionOutput = & (Join-Path $workspace 'runtime\sumo\bin\sumo.exe') --version 2>&1
$sumoExitCode = $LASTEXITCODE
if ($sumoExitCode -ne 0) { throw 'Portable SUMO failed to start.' }
$sumoVersion = $sumoVersionOutput | Select-Object -First 1

& (Join-Path $workspace 'runtime\python\python.exe') -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Portable Python dependency check failed.' }

try {
    & (Join-Path $workspace 'start_portable.ps1') -Port $Port -DurationS 30 -NoBrowser
    $ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/ready" -TimeoutSec 10
    $scene = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/v1/scenes/xiongan_rongdong_20/3d" -TimeoutSec 30
    $unity = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/unity/index.html" -TimeoutSec 10
    $loader = Invoke-WebRequest -UseBasicParsing -Method Head -Uri "http://127.0.0.1:$Port/unity/Build/unity.loader.js" -TimeoutSec 10
    $unityData = Invoke-WebRequest -UseBasicParsing -Method Head -Uri "http://127.0.0.1:$Port/unity/Build/unity.data" -TimeoutSec 10
    $localMap = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/v1/osm/local-map?west=115.917520&south=39.058814&east=115.918273&north=39.059154" -TimeoutSec 30
    if (@($ready.StatusCode, $scene.StatusCode, $unity.StatusCode, $loader.StatusCode, $unityData.StatusCode, $localMap.StatusCode) | Where-Object { $_ -ne 200 }) {
        throw 'One or more portable HTTP checks failed.'
    }

    $state = Get-Content -LiteralPath (Join-Path $workspace 'runtime-state\portable-process.json') -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not $state.experimentId) { throw 'Portable launcher did not create a SUMO experiment.' }
    $deadline = (Get-Date).AddSeconds(45)
    do {
        $experiment = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/experiments/$($state.experimentId)" -TimeoutSec 5
        if ($experiment.status -eq 'failed') { throw "Portable SUMO smoke test failed: $($experiment.error)" }
        if ($experiment.status -in @('running', 'completed')) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if ($experiment.status -notin @('running', 'completed')) {
        throw "Portable SUMO smoke test did not start in time (status=$($experiment.status))."
    }
    Write-Host 'Portable package self-test passed.'
    Write-Host "Python: $pythonVersion"
    Write-Host "SUMO: $sumoVersion"
    Write-Host "Real SUMO experiment: $($state.experimentId) ($($experiment.status))"
    Write-Host 'Offline Hebei OSM map endpoint: passed'
}
finally {
    & (Join-Path $workspace 'stop_portable.ps1')
}

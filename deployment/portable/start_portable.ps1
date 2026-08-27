[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 5177,
    [ValidateSet('BASE', 'S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07')]
    [string]$Profile = 'BASE',
    [string]$Algorithm = 'fixed-time',
    [ValidateRange(0, 2147483647)]
    [int]$Seed = 42,
    [ValidateRange(1, 18000)]
    [double]$DurationS = 1800,
    [switch]$SkipExperiment,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $workspace 'runtime-state'
$statePath = Join-Path $runtimeDir 'portable-process.json'
$logDir = Join-Path $runtimeDir 'logs'
$python = Join-Path $workspace 'runtime\python\python.exe'
$sumoHome = Join-Path $workspace 'runtime\sumo'
$sumoBinary = Join-Path $sumoHome 'bin\sumo.exe'
$scenePath = Join-Path $workspace 'generated\scenes\xiongan_rongdong_20.scene.json'
$scenarioPath = Join-Path $workspace 'scenarios\generated\xiongan_rongdong_20\xiongan_rongdong_20.sumocfg'
$webPath = Join-Path $workspace 'web\index.html'
$url = "http://127.0.0.1:$Port/?view=3d"

function Wait-Http(
    [string]$Uri,
    [int]$TimeoutS = 180,
    [System.Diagnostics.Process]$ServerProcess = $null
) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    do {
        if ($ServerProcess) {
            $ServerProcess.Refresh()
            if ($ServerProcess.HasExited) {
                $stderrPath = Join-Path $logDir 'server.stderr.log'
                $stderr = if (Test-Path -LiteralPath $stderrPath) {
                    (Get-Content -LiteralPath $stderrPath -Tail 20 -ErrorAction SilentlyContinue) -join "`n"
                }
                else { '' }
                $detail = if ($stderr) { "`n$stderr" } else { "`nSee: $stderrPath" }
                throw "Portable server exited before it became ready (exit code $($ServerProcess.ExitCode)).$detail"
            }
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        }
        catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

foreach ($required in @($python, $sumoBinary, $scenePath, $scenarioPath, $webPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Portable package is incomplete. Missing: $required"
    }
}

if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    $oldState = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
    $oldProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$oldState.pid)" -ErrorAction SilentlyContinue
    if ($oldProcess) {
        $commandLine = [string]$oldProcess.CommandLine
        $expectedPython = [System.IO.Path]::GetFullPath($python)
        $executablePath = [System.IO.Path]::GetFullPath([string]$oldProcess.ExecutablePath)
        if (
            $oldProcess.Name -eq 'python.exe' -and
            $executablePath -eq $expectedPython -and
            $commandLine.Contains('portable_server.py')
        ) {
            try {
                Wait-Http "http://127.0.0.1:$([int]$oldState.port)/ready" 5
                $existingUrl = "http://127.0.0.1:$([int]$oldState.port)/?view=3d"
                if (-not $NoBrowser) { Start-Process $existingUrl | Out-Null }
                Write-Host "The 3D demo is already running: $existingUrl"
                exit 0
            }
            catch {
                throw "A recorded portable process is still running but is not healthy (PID $($oldState.pid)). Run stop_portable.ps1 first."
            }
        }
        throw "PID $($oldState.pid) is not owned by this package. Remove runtime-state\portable-process.json only after checking that process."
    }
    Remove-Item -LiteralPath $statePath -Force
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owners = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Port $Port is already in use (PID $owners). Choose another port, for example: .\start_portable.ps1 -Port 5187"
}

[System.IO.Directory]::CreateDirectory($logDir) | Out-Null
[System.IO.Directory]::CreateDirectory((Join-Path $workspace 'results')) | Out-Null
$env:SUMO_HOME = $sumoHome
$env:SUMO_BINARY = $sumoBinary
$env:PYTHONPATH = (Join-Path $workspace 'src') + ';' + (Join-Path $sumoHome 'tools')
$env:TRAFFIC_MESSAGE_BUS = 'emulated'
$env:ENVIRONMENT = 'portable-demo'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:NO_PROXY = '127.0.0.1,localhost'
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:REDIS_URL -ErrorAction SilentlyContinue

$process = $null
try {
    $process = Start-Process -FilePath $python `
        -ArgumentList @('portable_server.py', '--host', '127.0.0.1', '--port', "$Port") `
        -WorkingDirectory $workspace `
        -RedirectStandardOutput (Join-Path $logDir 'server.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'server.stderr.log') `
        -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$Port/ready" 180 $process

    $experimentId = $null
    if (-not $SkipExperiment) {
        $request = @{
            scenario_id = 'xiongan_rongdong_20'
            profile = $Profile
            algorithm = $Algorithm
            seed = $Seed
            duration_s = $DurationS
            gui = $false
        } | ConvertTo-Json
        $created = Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:$Port/api/v1/experiments" `
            -ContentType 'application/json' -Body $request -TimeoutSec 15
        $experimentId = [string]$created.id
        Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:$Port/api/v1/experiments/$experimentId/start" `
            -TimeoutSec 15 | Out-Null
    }

    $state = [ordered]@{
        status = 'running'
        workspace = $workspace
        pid = $process.Id
        port = $Port
        startedAt = (Get-Date).ToUniversalTime().ToString('o')
        experimentId = $experimentId
        scenarioProfile = $Profile
        url = $url
    }
    [System.IO.File]::WriteAllText(
        $statePath,
        ($state | ConvertTo-Json -Depth 4),
        [System.Text.UTF8Encoding]::new($false)
    )

    if (-not $NoBrowser) { Start-Process $url | Out-Null }
    Write-Host "3D demo ready: $url"
    Write-Host "Server PID: $($process.Id)"
    if ($experimentId) { Write-Host "Experiment: $experimentId ($Profile, $Algorithm)" }
    Write-Host "Logs: $logDir"
}
catch {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}

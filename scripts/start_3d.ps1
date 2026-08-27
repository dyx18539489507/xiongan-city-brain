[CmdletBinding()]
param(
    [int]$BackendPort = 8013,
    [int]$FrontendPort = 5177,
    [int]$Seed = 42,
    [double]$DurationS = 1800,
    [ValidateRange(0.1, 32.0)]
    [double]$SimulationRate = 1.0,
    [string]$Algorithm = 'fixed-time',
    [ValidateSet('BASE', 'S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07')]
    [string]$Profile = 'BASE',
    [switch]$SkipExperiment,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
# PowerShell 7 may still route -Proxy $null requests through HTTP(S)_PROXY.
# Keep all local readiness and control traffic off the user-level proxy.
$env:NO_PROXY = '127.0.0.1,localhost'
$env:no_proxy = '127.0.0.1,localhost'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeDir = Join-Path $workspace 'outputs\3d\runtime'
$statePath = Join-Path $runtimeDir 'demo-processes.json'
$logDir = Join-Path $runtimeDir 'logs'

function Assert-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $owners = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
        throw "Port $Port is already listening (PID $owners). Stop that service or choose another port."
    }
}

function Wait-Http(
    [string]$Uri,
    [int]$TimeoutS = 120,
    [System.Diagnostics.Process]$Process = $null
) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    do {
        if ($Process -and $Process.HasExited) {
            throw "Process PID $($Process.Id) exited while waiting for $Uri. Check the runtime logs for details."
        }
        try {
            # Local readiness checks must not be routed through a user-level
            # HTTP proxy. A proxy returning 502 here would otherwise make a
            # healthy local service look unavailable and stop both processes.
            $response = Invoke-WebRequest -UseBasicParsing -Proxy $null -Uri $Uri -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Test-Python312([string]$PythonPath) {
    if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { return $false }
    & $PythonPath -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' *> $null
    return $LASTEXITCODE -eq 0
}

function Repair-PortableVenv([string]$VenvPython) {
    if (Test-Python312 $VenvPython) { return }

    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    $commandPythons = @(Get-Command python.exe -All -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source -Unique)
    $basePython = @($bundledPython, $localPython) + $commandPythons |
        Where-Object { Test-Python312 $_ } |
        Select-Object -First 1

    if (-not $basePython) {
        throw (
            "The project virtual environment points to an unavailable Python installation, " +
            "and no Python 3.12 interpreter was found for the current Windows account."
        )
    }

    Write-Host "Repairing project virtual environment with $basePython..."
    & $basePython -m venv --upgrade (Split-Path -Parent (Split-Path -Parent $VenvPython))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Python312 $VenvPython)) {
        throw "Failed to repair the project virtual environment with $basePython."
    }
}

function Wait-ExperimentLive(
    [string]$BackendUrl,
    [string]$ExperimentId,
    [System.Diagnostics.Process]$BackendProcess,
    [int]$TimeoutS = 360
) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    $firstSimulationTime = $null
    $lastRequestError = $null
    $lastObservation = 'no experiment status was returned'
    do {
        if ($BackendProcess.HasExited) {
            throw "Backend exited before experiment $ExperimentId produced a live SUMO frame."
        }

        try {
            $experiment = Invoke-RestMethod `
                -Proxy $null `
                -Uri "$BackendUrl/api/v1/experiments/$ExperimentId" `
                -TimeoutSec 3
            $system = Invoke-RestMethod `
                -Proxy $null `
                -Uri "$BackendUrl/api/v1/system/status" `
                -TimeoutSec 3
            $lastRequestError = $null
        } catch {
            $lastRequestError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
            continue
        }

        $lastObservation = (
            "experiment=$($experiment.status), system=$($system.status), " +
            "system_experiment=$($system.experiment_id), simulation_time=$($system.simulation_time_s)"
        )

        if ($experiment.status -eq 'failed') {
            $detail = if ($experiment.error) { [string]$experiment.error } else { 'no error detail was returned' }
            throw "Experiment $ExperimentId failed during startup: $detail"
        }
        if ($experiment.status -in @('completed', 'stopped', 'stopping', 'finalizing')) {
            throw "Experiment $ExperimentId reached '$($experiment.status)' before startup validation completed."
        }

        $isMatchingLiveFrame = (
            $experiment.status -eq 'running' -and
            $system.status -eq 'running' -and
            [string]$system.experiment_id -eq $ExperimentId -and
            $null -ne $system.simulation_time_s
        )
        if ($isMatchingLiveFrame) {
            $simulationTime = [double]$system.simulation_time_s
            if ($null -eq $firstSimulationTime) {
                $firstSimulationTime = $simulationTime
            } elseif ($simulationTime -gt $firstSimulationTime) {
                return [ordered]@{
                    simulationTimeS = $simulationTime
                    algorithm = [string]$system.algorithm
                    scenarioId = [string]$system.scenario_id
                }
            }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    $requestDetail = if ($lastRequestError) { " Last request error: $lastRequestError" } else { '' }
    throw (
        "Timed out waiting for experiment $ExperimentId to produce advancing SUMO frames. " +
        "Last observation: $lastObservation.$requestDetail"
    )
}

function Stop-StartedProcessTree([System.Diagnostics.Process]$Process) {
    if (-not $Process) { return }
    $root = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)" -ErrorAction SilentlyContinue
    if (-not $root) { return }

    $processTree = [System.Collections.Generic.List[object]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $pending.Enqueue([int]$root.ProcessId)
    while ($pending.Count -gt 0) {
        $currentPid = $pending.Dequeue()
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$currentPid" -ErrorAction SilentlyContinue
        if (-not $current) { continue }
        $processTree.Add($current)
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$currentPid" -ErrorAction SilentlyContinue
        foreach ($child in $children) { $pending.Enqueue([int]$child.ProcessId) }
    }
    for ($index = $processTree.Count - 1; $index -ge 0; $index -= 1) {
        Stop-Process -Id ([int]$processTree[$index].ProcessId) -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($previous.status -eq 'running') {
        throw "A recorded 3D session is still marked running. Run scripts\stop_3d.ps1 first."
    }
}

$venvPython = Join-Path $workspace '.venv\Scripts\python.exe'
$viteEntry = Join-Path $workspace 'apps\web-dashboard\node_modules\vite\bin\vite.js'
$scenePath = Join-Path $workspace 'generated\scenes\xiongan_rongdong_20.scene.json'
if (-not (Test-Path -LiteralPath $venvPython)) { throw "Missing virtual environment Python: $venvPython" }
Repair-PortableVenv $venvPython
if (-not (Test-Path -LiteralPath $viteEntry)) { throw "Missing Vite dependencies. Run npm install in apps\web-dashboard." }
if (-not (Test-Path -LiteralPath $scenePath)) { throw "Missing generated 3D scene. Run deployment\scripts\task.ps1 generate-3d-scene." }

$nodeCommand = (Get-Command node.exe -ErrorAction Stop).Source
$sumoRoot = $env:SUMO_HOME
if (-not $sumoRoot) {
    $workspaceSumo = Join-Path $workspace '.tools\sumo'
    $portableSumo = Join-Path $workspace 'exports\xiongan_teammate_portable_20260812\runtime\sumo'
    $portable3dSumo = Join-Path $workspace 'exports\xiongan_3d_portable_v4\xiongan_3d_portable_v4\runtime\sumo'
    $sumoRoot = if (Test-Path -LiteralPath (Join-Path $workspaceSumo 'bin\sumo.exe')) {
        $workspaceSumo
    } elseif (Test-Path -LiteralPath (Join-Path $portableSumo 'bin\sumo.exe')) {
        $portableSumo
    } elseif (Test-Path -LiteralPath (Join-Path $portable3dSumo 'bin\sumo.exe')) {
        $portable3dSumo
    } else {
        Get-ChildItem -LiteralPath (Join-Path $workspace 'exports') `
            -Filter 'sumo.exe' -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty DirectoryName |
            ForEach-Object { Split-Path -Parent $_ }
    }
}
$sumoRoot = if ($sumoRoot) { [System.IO.Path]::GetFullPath($sumoRoot) } else { '' }
$sumoBinary = Join-Path $sumoRoot 'bin\sumo.exe'
if (-not (Test-Path -LiteralPath $sumoBinary)) {
    throw "SUMO_HOME must point to a SUMO installation containing bin\sumo.exe. Checked: $sumoRoot"
}

Assert-PortFree $BackendPort
Assert-PortFree $FrontendPort
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$backendProcess = $null
$frontendProcess = $null
$experimentId = $null
try {
    $env:SUMO_HOME = $sumoRoot
    # The browser application runs one selected algorithm at a time. Keeping the
    # built-ins in-process avoids four resident Python workers on low-memory
    # presentation laptops without changing SUMO or control decisions.
    $env:TRAFFIC_PLATFORM_ISOLATE_ALGORITHMS = 'false'
    $env:VITE_API_TARGET = "http://127.0.0.1:$BackendPort"
    Write-Host 'Starting traffic backend...'
    $backendProcess = Start-Process -FilePath $venvPython `
        -ArgumentList '-m', 'traffic_platform.cli', 'serve', '--host', '127.0.0.1', '--port', $BackendPort `
        -WorkingDirectory $workspace `
        -RedirectStandardOutput (Join-Path $logDir 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'backend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$BackendPort/ready" 120 $backendProcess
    Write-Host 'Traffic backend is ready.'

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
            -Proxy $null `
            -Uri "http://127.0.0.1:$BackendPort/api/v1/experiments" `
            -ContentType 'application/json' -Body $request
        $experimentId = [string]$created.id
        $rateRequest = @{ rate = $SimulationRate } | ConvertTo-Json
        Invoke-RestMethod -Method Post `
            -Proxy $null `
            -Uri "http://127.0.0.1:$BackendPort/api/v1/experiments/$experimentId/rate" `
            -ContentType 'application/json' -Body $rateRequest | Out-Null
        Invoke-RestMethod -Method Post `
            -Proxy $null `
            -Uri "http://127.0.0.1:$BackendPort/api/v1/experiments/$experimentId/start" | Out-Null
        Write-Host "Waiting for SUMO experiment $experimentId to produce advancing frames..."
        $liveFrame = Wait-ExperimentLive `
            -BackendUrl "http://127.0.0.1:$BackendPort" `
            -ExperimentId $experimentId `
            -BackendProcess $backendProcess
    }

    # Defer the dashboard until SUMO is live. Existing browser tabs reconnect as
    # soon as Vite starts and would otherwise compete with SUMO while loading the
    # large WebGL build on presentation laptops.
    Write-Host 'Starting 3D dashboard...'
    $frontendProcess = Start-Process -FilePath $nodeCommand `
        -ArgumentList $viteEntry, '--host', '127.0.0.1', '--port', $FrontendPort `
        -WorkingDirectory (Join-Path $workspace 'apps\web-dashboard') `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'frontend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$FrontendPort/" 120 $frontendProcess

    $state = [ordered]@{
        status = 'running'
        workspace = $workspace
        startedAt = (Get-Date).ToUniversalTime().ToString('o')
        backendPid = $backendProcess.Id
        frontendPid = $frontendProcess.Id
        backendUrl = "http://127.0.0.1:$BackendPort"
        frontendUrl = "http://127.0.0.1:$FrontendPort"
        experimentId = $experimentId
        scenarioProfile = $Profile
        simulationRate = $SimulationRate
        sumoHome = $sumoRoot
        logs = $logDir
    }
    [System.IO.File]::WriteAllText(
        $statePath,
        ($state | ConvertTo-Json -Depth 5),
        [System.Text.UTF8Encoding]::new($false)
    )

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$FrontendPort/?view=3d" | Out-Null
    }
    if ($liveFrame) {
        Write-Host "SUMO live frame verified at simulation time $($liveFrame.simulationTimeS) s."
    }
    Write-Host "3D application ready: http://127.0.0.1:$FrontendPort/?view=3d"
    Write-Host "Backend PID $($backendProcess.Id), frontend PID $($frontendProcess.Id), experiment $experimentId"
    Write-Host "SUMO pacing: $SimulationRate x"
    Write-Host "Logs: $logDir"
} catch {
    $startupError = $_.Exception.Message
    Stop-StartedProcessTree $frontendProcess
    Stop-StartedProcessTree $backendProcess

    if ($backendProcess -or $frontendProcess) {
        $failedState = [ordered]@{
            status = 'failed'
            workspace = $workspace
            failedAt = (Get-Date).ToUniversalTime().ToString('o')
            backendPid = if ($backendProcess) { $backendProcess.Id } else { $null }
            frontendPid = if ($frontendProcess) { $frontendProcess.Id } else { $null }
            backendUrl = "http://127.0.0.1:$BackendPort"
            frontendUrl = "http://127.0.0.1:$FrontendPort"
            experimentId = $experimentId
            error = $startupError
            logs = $logDir
        }
        [System.IO.File]::WriteAllText(
            $statePath,
            ($failedState | ConvertTo-Json -Depth 5),
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    throw
}

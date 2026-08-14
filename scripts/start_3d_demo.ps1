[CmdletBinding()]
param(
    [int]$BackendPort = 8013,
    [int]$FrontendPort = 5177,
    [int]$Seed = 42,
    [double]$DurationS = 1800,
    [string]$Algorithm = 'fixed-time',
    [ValidateSet('BASE', 'S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07')]
    [string]$Profile = 'BASE',
    [switch]$SkipExperiment,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
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

function Wait-Http([string]$Uri, [int]$TimeoutS = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($previous.status -eq 'running') {
        throw "A recorded demo session is still marked running. Run scripts\stop_3d_demo.ps1 first."
    }
}

$venvCommand = Join-Path $workspace '.venv\Scripts\traffic-platform.exe'
$viteEntry = Join-Path $workspace 'apps\web-dashboard\node_modules\vite\bin\vite.js'
$scenePath = Join-Path $workspace 'generated\scenes\xiongan_rongdong_20.scene.json'
if (-not (Test-Path -LiteralPath $venvCommand)) { throw "Missing virtual environment command: $venvCommand" }
if (-not (Test-Path -LiteralPath $viteEntry)) { throw "Missing Vite dependencies. Run npm install in apps\web-dashboard." }
if (-not (Test-Path -LiteralPath $scenePath)) { throw "Missing generated 3D scene. Run deployment\scripts\task.ps1 generate-3d-scene." }

$nodeCommand = (Get-Command node.exe -ErrorAction Stop).Source
$sumoRoot = $env:SUMO_HOME
if (-not $sumoRoot) {
    $sumoRoot = Join-Path $env:LOCALAPPDATA 'xiongan-traffic-brain\sumo'
}
$sumoBinary = Join-Path $sumoRoot 'bin\sumo.exe'
if (-not (Test-Path -LiteralPath $sumoBinary)) {
    throw "SUMO_HOME must point to a SUMO installation containing bin\sumo.exe. Checked: $sumoRoot"
}

Assert-PortFree $BackendPort
Assert-PortFree $FrontendPort
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$backendProcess = $null
$frontendProcess = $null
try {
    $env:SUMO_HOME = $sumoRoot
    $env:VITE_API_TARGET = "http://127.0.0.1:$BackendPort"
    $backendProcess = Start-Process -FilePath $venvCommand `
        -ArgumentList 'serve', '--host', '127.0.0.1', '--port', $BackendPort `
        -WorkingDirectory $workspace `
        -RedirectStandardOutput (Join-Path $logDir 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'backend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$BackendPort/ready"

    $frontendProcess = Start-Process -FilePath $nodeCommand `
        -ArgumentList $viteEntry, '--host', '127.0.0.1', '--port', $FrontendPort `
        -WorkingDirectory (Join-Path $workspace 'apps\web-dashboard') `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'frontend.stderr.log') `
        -WindowStyle Hidden -PassThru
    Wait-Http "http://127.0.0.1:$FrontendPort/"

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
            -Uri "http://127.0.0.1:$BackendPort/api/v1/experiments" `
            -ContentType 'application/json' -Body $request
        $experimentId = [string]$created.id
        Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:$BackendPort/api/v1/experiments/$experimentId/start" | Out-Null
    }

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
        sumoHome = $sumoRoot
        logs = $logDir
    }
    [System.IO.File]::WriteAllText(
        $statePath,
        ($state | ConvertTo-Json -Depth 5),
        [System.Text.UTF8Encoding]::new($false)
    )

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$FrontendPort" | Out-Null
    }
    Write-Host "3D demo ready: http://127.0.0.1:$FrontendPort"
    Write-Host "Backend PID $($backendProcess.Id), frontend PID $($frontendProcess.Id), experiment $experimentId"
    Write-Host "Logs: $logDir"
} catch {
    if ($frontendProcess -and -not $frontendProcess.HasExited) { Stop-Process -Id $frontendProcess.Id -ErrorAction SilentlyContinue }
    if ($backendProcess -and -not $backendProcess.HasExited) { Stop-Process -Id $backendProcess.Id -ErrorAction SilentlyContinue }
    throw
}

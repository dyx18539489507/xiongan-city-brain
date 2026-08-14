[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $workspace 'outputs\3d\runtime\demo-processes.json'
if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host 'No recorded 3D demo session was found.'
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath([string]$state.workspace) -ne $workspace) {
    throw 'Refusing to stop processes from a state file owned by another workspace.'
}

if ($state.experimentId -and $state.backendUrl) {
    try {
        Invoke-RestMethod -Method Post `
            -Uri "$($state.backendUrl)/api/v1/experiments/$($state.experimentId)/stop" `
            -TimeoutSec 5 | Out-Null
        $deadline = (Get-Date).AddSeconds(15)
        do {
            $experiment = Invoke-RestMethod `
                -Uri "$($state.backendUrl)/api/v1/experiments/$($state.experimentId)" `
                -TimeoutSec 3
            if ($experiment.status -in @('stopped', 'completed', 'failed')) { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)
    } catch {
        Write-Warning "Could not stop experiment through API: $($_.Exception.Message)"
    }
}

foreach ($entry in @(
    @{Name = 'frontend'; Pid = [int]$state.frontendPid},
    @{Name = 'backend'; Pid = [int]$state.backendPid}
)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.Pid)" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if (-not ([string]$process.CommandLine).Contains($workspace)) {
        Write-Warning "Skipping $($entry.Name) PID $($entry.Pid): command line is not owned by this workspace."
        continue
    }
    Stop-Process -Id $entry.Pid -ErrorAction SilentlyContinue
    Write-Host "Stopped $($entry.Name) PID $($entry.Pid)"
}

# A force-terminated backend can leave only its own SUMO child alive. Limit the
# cleanup to SUMO command lines that explicitly reference this workspace.
$sumoChildren = Get-CimInstance Win32_Process -Filter "Name='sumo.exe'" -ErrorAction SilentlyContinue |
    Where-Object { ([string]$_.CommandLine).Contains($workspace) }
foreach ($sumoChild in $sumoChildren) {
    Stop-Process -Id $sumoChild.ProcessId -ErrorAction SilentlyContinue
    Write-Host "Stopped scoped SUMO PID $($sumoChild.ProcessId)"
}

$state.status = 'stopped'
$state | Add-Member -NotePropertyName stoppedAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
[System.IO.File]::WriteAllText(
    $statePath,
    ($state | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)
Write-Host '3D demo session stopped.'

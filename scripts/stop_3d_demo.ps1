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
    $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.Pid)" -ErrorAction SilentlyContinue
    if (-not $rootProcess) { continue }
    if (-not ([string]$rootProcess.CommandLine).Contains($workspace)) {
        Write-Warning "Skipping $($entry.Name) PID $($entry.Pid): command line is not owned by this workspace."
        continue
    }

    # Windows venv launchers keep the recorded shim process alive while the
    # base Python child owns the listening socket. Stop the complete process
    # tree, children first, after ownership has been verified at its root.
    $processTree = [System.Collections.Generic.List[object]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $pending.Enqueue([int]$rootProcess.ProcessId)
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
    Write-Host "Stopped $($entry.Name) process tree rooted at PID $($entry.Pid)"
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

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$env:NO_PROXY = '127.0.0.1,localhost'
$env:no_proxy = '127.0.0.1,localhost'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $workspace 'outputs\3d\runtime\demo-processes.json'
if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host 'No recorded 3D session was found.'
    $state = [pscustomobject]@{
        status = 'untracked'
        workspace = $workspace
        experimentId = $null
        backendUrl = $null
        frontendUrl = $null
        backendPid = 0
        frontendPid = 0
    }
} else {
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
}

if ([System.IO.Path]::GetFullPath([string]$state.workspace) -ne $workspace) {
    throw 'Refusing to stop processes from a state file owned by another workspace.'
}

if ($state.experimentId -and $state.backendUrl) {
    try {
        Invoke-RestMethod -Method Post `
            -Proxy $null `
            -Uri "$($state.backendUrl)/api/v1/experiments/$($state.experimentId)/stop" `
            -TimeoutSec 5 | Out-Null
        $deadline = (Get-Date).AddSeconds(15)
        do {
            $experiment = Invoke-RestMethod `
                -Proxy $null `
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

# A manually launched or restarted project service is not present in the state
# file. Reconcile the ports used by start.cmd, but only terminate listeners
# whose command line or process ancestry explicitly belongs to this workspace.
function Find-WorkspaceProcessAncestor([object]$Process, [string]$Workspace) {
    $current = $Process
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    while ($current -and $visited.Add([int]$current.ProcessId)) {
        $commandLine = [string]$current.CommandLine
        if ($commandLine.IndexOf($Workspace, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $current
        }
        if ([int]$current.ParentProcessId -le 0) { break }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($current.ParentProcessId)" -ErrorAction SilentlyContinue
    }
    return $null
}

$portsToCheck = @(8014, 5178)
foreach ($url in @($state.backendUrl, $state.frontendUrl)) {
    if (-not $url) { continue }
    try { $portsToCheck += ([Uri][string]$url).Port } catch { }
}
foreach ($port in ($portsToCheck | Sort-Object -Unique)) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($processId in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if (-not $listenerProcess) { continue }
        $rootProcess = Find-WorkspaceProcessAncestor $listenerProcess $workspace
        if (-not $rootProcess) {
            Write-Warning "Skipping listener PID $processId on port ${port}: process ancestry is not owned by this workspace."
            continue
        }

        $processTree = [System.Collections.Generic.List[object]]::new()
        $pending = [System.Collections.Generic.Queue[int]]::new()
        $pending.Enqueue([int]$rootProcess.ProcessId)
        while ($pending.Count -gt 0) {
            $currentPid = $pending.Dequeue()
            $current = Get-CimInstance Win32_Process -Filter "ProcessId=$currentPid" -ErrorAction SilentlyContinue
            if (-not $current) { continue }
            $processTree.Add($current)
            foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$currentPid" -ErrorAction SilentlyContinue)) {
                $pending.Enqueue([int]$child.ProcessId)
            }
        }
        for ($index = $processTree.Count - 1; $index -ge 0; $index -= 1) {
            Stop-Process -Id ([int]$processTree[$index].ProcessId) -Force -ErrorAction SilentlyContinue
        }
        Write-Host "Stopped unrecorded workspace listener PID $processId on port $port through owner PID $($rootProcess.ProcessId)"
    }

    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 200
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is still listening after the stop operation."
    }
}

$state.status = 'stopped'
$state | Add-Member -NotePropertyName stoppedAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
[System.IO.File]::WriteAllText(
    $statePath,
    ($state | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)
Write-Host '3D session stopped.'

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
$statePath = Join-Path $workspace 'runtime-state\portable-process.json'

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host 'No recorded portable 3D demo is running.'
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
$port = [int]$state.port
if ($state.experimentId) {
    try {
        Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:$port/api/v1/experiments/$($state.experimentId)/stop" `
            -TimeoutSec 5 | Out-Null
        Start-Sleep -Milliseconds 500
    }
    catch {
        Write-Warning "Could not stop the experiment through the API: $($_.Exception.Message)"
    }
}

$pidValue = [int]$state.pid
$rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
if ($rootProcess) {
    $expectedPython = [System.IO.Path]::GetFullPath((Join-Path $workspace 'runtime\python\python.exe'))
    $executablePath = [System.IO.Path]::GetFullPath([string]$rootProcess.ExecutablePath)
    $commandLine = [string]$rootProcess.CommandLine
    if ($rootProcess.Name -ne 'python.exe' -or $executablePath -ne $expectedPython -or -not $commandLine.Contains('portable_server.py')) {
        throw "PID $pidValue does not match this portable package; refusing to stop it."
    }

    $processTree = [System.Collections.Generic.List[object]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $pending.Enqueue($pidValue)
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
}

Remove-Item -LiteralPath $statePath -Force
Write-Host 'Portable 3D demo stopped.'

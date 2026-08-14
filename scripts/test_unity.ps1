$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$unityRoot = Join-Path $workspace '.tools\unity'
$unity = Join-Path $unityRoot '6000.3.9f1\Editor\Unity.exe'
$project = Join-Path $workspace 'apps\unity-digital-twin'
$logs = Join-Path $unityRoot 'logs'
$testLog = Join-Path $logs 'unity-editmode-tests.log'
$testResults = Join-Path $logs 'unity-editmode-results.xml'

if (-not (Test-Path -LiteralPath $unity)) { throw "Unity is not installed at $unity" }
New-Item -ItemType Directory -Force -Path $logs,(Join-Path $unityRoot 'cache\upm'),(Join-Path $unityRoot 'cache\npm') | Out-Null

$env:UPM_CACHE_ROOT = Join-Path $unityRoot 'cache\upm'
$env:UPM_NPM_CACHE_PATH = Join-Path $unityRoot 'cache\npm'

$unityProcess = Start-Process -FilePath $unity -ArgumentList @(
    '-batchmode',
    '-job-worker-count', '1',
    '-projectPath', "`"$project`"",
    '-runTests',
    '-testPlatform', 'EditMode',
    '-testResults', "`"$testResults`"",
    '-logFile', "`"$testLog`""
) -WindowStyle Hidden -Wait -PassThru

if ($unityProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $testResults)) {
    throw "Unity EditMode tests failed (exit=$($unityProcess.ExitCode)). See $testLog"
}

$resultsText = Get-Content -Raw -LiteralPath $testResults
$runMatch = [regex]::Match($resultsText, '<test-run\b[^>]*\bpassed="(?<passed>\d+)"[^>]*\bfailed="(?<failed>\d+)"')
if (-not $runMatch.Success) {
    throw "Unity EditMode result summary is missing. See $testResults"
}
$passed = [int]$runMatch.Groups['passed'].Value
$failed = [int]$runMatch.Groups['failed'].Value
if ($failed -ne 0 -or $passed -lt 1) {
    throw "Unity EditMode tests did not pass. See $testResults"
}

Write-Host "Unity EditMode tests passed: $passed passed, $failed failed"

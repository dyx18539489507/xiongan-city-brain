[CmdletBinding()]
param(
    [string]$Profile = 'S02',
    [string]$Algorithm = 'fixed-time',
    [int]$Seed = 91,
    [double]$DurationS = 1800,
    [int]$SampleIntervalS = 20,
    [int]$MaxWallS = 1200,
    [int]$BackendPort = 8013,
    [int]$FrontendPort = 5177,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$output = Join-Path $workspace "outputs\3d\benchmarks\stability-$timestamp.json"
$started = $false
$gpuPreferenceRegistry = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
$playwrightChrome = (& node.exe -e "const {chromium}=require('./apps/web-dashboard/node_modules/playwright'); process.stdout.write(chromium.executablePath())" 2>$null)
$gpuPreferenceExisted = $false
$previousGpuPreference = $null
if (-not $Headless -and $playwrightChrome -and (Test-Path -LiteralPath $playwrightChrome)) {
    New-Item -Path $gpuPreferenceRegistry -Force | Out-Null
    try {
        $previousGpuPreference = Get-ItemPropertyValue -Path $gpuPreferenceRegistry -Name $playwrightChrome -ErrorAction Stop
        $gpuPreferenceExisted = $true
    } catch {
        $gpuPreferenceExisted = $false
    }
    Set-ItemProperty -Path $gpuPreferenceRegistry -Name $playwrightChrome -Value 'GpuPreference=2;'
}
try {
    & (Join-Path $PSScriptRoot 'start_3d_demo.ps1') `
        -BackendPort $BackendPort `
        -FrontendPort $FrontendPort `
        -SkipExperiment `
        -NoBrowser
    $started = $true
    & node.exe (Join-Path $workspace 'tools\benchmark\run_3d_stability.mjs') `
        --frontend "http://127.0.0.1:$FrontendPort" `
        --profile $Profile `
        --algorithm $Algorithm `
        --seed ([string]$Seed) `
        --duration ([string]$DurationS) `
        --interval ([string]$SampleIntervalS) `
        --max-wall ([string]$MaxWallS) `
        --headless $Headless.IsPresent.ToString().ToLowerInvariant() `
        --output $output
    if ($LASTEXITCODE -ne 0) { throw "3D stability runner exited with $LASTEXITCODE" }
    Write-Host "Stability report: $output"
} finally {
    if ($started) {
        & (Join-Path $PSScriptRoot 'stop_3d_demo.ps1')
    }
    if (-not $Headless -and $playwrightChrome -and (Test-Path -LiteralPath $gpuPreferenceRegistry)) {
        if ($gpuPreferenceExisted) {
            Set-ItemProperty -Path $gpuPreferenceRegistry -Name $playwrightChrome -Value $previousGpuPreference
        } else {
            Remove-ItemProperty -Path $gpuPreferenceRegistry -Name $playwrightChrome -ErrorAction SilentlyContinue
        }
    }
}

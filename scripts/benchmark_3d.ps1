[CmdletBinding()]
param(
    [string[]]$Profiles = @('S01', 'S02', 'S03', 'S04', 'S05'),
    [string[]]$Conditions = @('clear', 'night', 'rain'),
    [string[]]$Views = @('overview', 'corridor', 'junction'),
    [string]$Algorithm = 'fixed-time',
    [int]$Seed = 52,
    [double]$DurationS = 900,
    [int]$WarmupS = 5,
    [int]$SampleS = 10,
    [int]$BackendPort = 8005,
    [int]$FrontendPort = 5185,
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$output = Join-Path $workspace "outputs\3d\benchmarks\matrix-$timestamp.json"
$headlessValue = $Headless.IsPresent.ToString().ToLowerInvariant()
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
    & node.exe (Join-Path $workspace 'tools\benchmark\run_3d_matrix.mjs') `
        --frontend "http://127.0.0.1:$FrontendPort" `
        --profiles ($Profiles -join ',') `
        --conditions ($Conditions -join ',') `
        --views ($Views -join ',') `
        --algorithm $Algorithm `
        --seed ([string]$Seed) `
        --duration ([string]$DurationS) `
        --warmup ([string]$WarmupS) `
        --sample ([string]$SampleS) `
        --headless $headlessValue `
        --output $output
    if ($LASTEXITCODE -ne 0) { throw "3D benchmark runner exited with $LASTEXITCODE" }
    Write-Host "Benchmark report: $output"
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

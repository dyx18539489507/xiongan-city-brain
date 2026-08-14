[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$version = '4.4.2'
$installerSha256 = '1f323b0fec19794f5e6c0425a61d4b1da396872a10be862d105f4f4b2d2957fe'
$installerUrl = "https://github.com/KhronosGroup/KTX-Software/releases/download/v$version/KTX-Software-$version-Windows-x64.exe"
$toolRoot = Join-Path $PSScriptRoot ".tools\ktx-$version"
$installRoot = Join-Path $toolRoot 'install'
$installerPath = Join-Path $toolRoot "KTX-Software-$version-Windows-x64.exe"
$toktx = Join-Path $installRoot 'bin\toktx.exe'
$ktx = Join-Path $installRoot 'bin\ktx.exe'

$input = [System.IO.Path]::GetFullPath($InputPath)
$output = [System.IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $input -PathType Leaf)) {
    throw "Input texture not found: $input"
}
if ([System.IO.Path]::GetExtension($output) -ne '.ktx2') {
    throw "Output must use the .ktx2 extension: $output"
}

if (-not (Test-Path -LiteralPath $toktx -PathType Leaf)) {
    New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    }
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $installerSha256) {
        throw "KTX-Software installer checksum mismatch: $actualHash"
    }
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
    $process = Start-Process -FilePath $installerPath -ArgumentList @('/S', "/D=$installRoot") -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $toktx -PathType Leaf)) {
        throw "KTX-Software extraction failed with exit code $($process.ExitCode)"
    }
}

$outputDirectory = Split-Path -Parent $output
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $toktx --t2 --encode etc1s --genmipmap --assign_oetf srgb --assign_primaries bt709 --clevel 3 --qlevel 160 $output $input
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw "toktx failed to encode $input"
}
& $ktx validate $output
if ($LASTEXITCODE -ne 0) {
    throw "KTX validation failed: $output"
}
$item = Get-Item -LiteralPath $output
Write-Host "Encoded and validated KTX2: $($item.FullName) ($($item.Length) bytes)"

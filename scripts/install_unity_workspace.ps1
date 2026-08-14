param(
    [switch]$SkipSignatureCheck
)

$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$root = Join-Path $workspace '.tools\unity'
$editorInstaller = Join-Path $root 'installers\UnitySetup64-6000.3.9f1.exe'
$webInstaller = Join-Path $root 'installers\UnitySetup-WebGL-Support-for-Editor-6000.3.9f1.verified.exe'
$installRoot = Join-Path $root '6000.3.9f1'
$logRoot = Join-Path $root 'logs'

$expectedLengths = @{
    $editorInstaller = [int64]4182207320
    $webInstaller = [int64]952624512
}
foreach ($installer in @($editorInstaller, $webInstaller)) {
    if (-not (Test-Path -LiteralPath $installer)) { throw "Missing verified installer: $installer" }
    $actualLength = (Get-Item -LiteralPath $installer).Length
    if ($actualLength -ne $expectedLengths[$installer]) { throw "Installer length mismatch: $installer ($actualLength)" }
    if (-not $SkipSignatureCheck) {
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid') { throw "Invalid installer signature: $installer ($($signature.Status))" }
    }
}

New-Item -ItemType Directory -Force -Path $installRoot,$logRoot | Out-Null
Write-Host "Installing Unity Editor below workspace: $installRoot"
$previousCompatibilityLayer = $env:__COMPAT_LAYER
$env:__COMPAT_LAYER = 'RunAsInvoker'
$editorProcess = Start-Process -FilePath $editorInstaller -ArgumentList @('/S', "/D=$installRoot") -WindowStyle Hidden -Wait -PassThru
if ($editorProcess.ExitCode -ne 0) { throw "Unity Editor installer exited with $($editorProcess.ExitCode)" }

$unity = Join-Path $installRoot 'Editor\Unity.exe'
if (-not (Test-Path -LiteralPath $unity)) { throw "Unity executable was not installed at $unity" }

Write-Host "Installing Web Build Support into the same workspace root"
$webProcess = Start-Process -FilePath $webInstaller -ArgumentList @('/S', "/D=$installRoot") -WindowStyle Hidden -Wait -PassThru
if ($webProcess.ExitCode -ne 0) { throw "Web Build Support installer exited with $($webProcess.ExitCode)" }
$env:__COMPAT_LAYER = $previousCompatibilityLayer

$webSupport = Join-Path $installRoot 'Editor\Data\PlaybackEngines\WebGLSupport'
if (-not (Test-Path -LiteralPath $webSupport)) { throw "Web Build Support was not installed at $webSupport" }

Write-Host "Unity workspace installation verified"
Write-Host $unity
Write-Host $webSupport

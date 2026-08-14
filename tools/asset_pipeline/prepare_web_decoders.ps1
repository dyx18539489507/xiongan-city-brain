[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$libraryRoot = Join-Path $workspace 'apps\web-dashboard\node_modules\three\examples\jsm\libs'
$publicRoot = Join-Path $workspace 'apps\web-dashboard\public\assets\decoders'
if (-not (Test-Path -LiteralPath $libraryRoot)) {
    throw 'Three.js decoder sources are missing. Run npm install in apps\web-dashboard first.'
}

$dracoTarget = Join-Path $publicRoot 'draco'
$basisTarget = Join-Path $publicRoot 'basis'
New-Item -ItemType Directory -Force -Path $dracoTarget, $basisTarget | Out-Null

foreach ($name in @('draco_decoder.js', 'draco_decoder.wasm', 'draco_wasm_wrapper.js', 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $libraryRoot "draco\$name") -Destination $dracoTarget -Force
}
foreach ($name in @('basis_transcoder.js', 'basis_transcoder.wasm', 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $libraryRoot "basis\$name") -Destination $basisTarget -Force
}
Write-Host "Prepared Draco and KTX2/Basis runtime decoders under $publicRoot"

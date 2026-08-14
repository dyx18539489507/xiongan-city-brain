param(
    [Parameter(Mandatory = $true)]
    [string]$Url,

    [Parameter(Mandatory = $true)]
    [long]$ExpectedBytes,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [int]$ChunkMiB = 64
)

$ErrorActionPreference = 'Stop'

$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$installersRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace '.tools\unity\installers'))
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $workspace $OutputPath))

if (-not $resolvedOutput.StartsWith($installersRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output must remain below $installersRoot"
}

$partRoot = "$resolvedOutput.parts"
New-Item -ItemType Directory -Force -Path $partRoot | Out-Null

$chunkBytes = [long]$ChunkMiB * 1MB
$chunkCount = [int][Math]::Ceiling($ExpectedBytes / [double]$chunkBytes)

for ($index = 0; $index -lt $chunkCount; $index++) {
    $start = [long]$index * $chunkBytes
    $end = [Math]::Min($ExpectedBytes - 1, $start + $chunkBytes - 1)
    $expectedPartBytes = $end - $start + 1
    $partPath = Join-Path $partRoot ('part-{0:D4}.bin' -f $index)

    if ((Test-Path -LiteralPath $partPath) -and (Get-Item -LiteralPath $partPath).Length -eq $expectedPartBytes) {
        Write-Host ("chunk {0}/{1} already verified" -f ($index + 1), $chunkCount)
        continue
    }

    & curl.exe -4 --ssl-no-revoke --http1.1 --silent --show-error --fail `
        --retry 8 --retry-all-errors --retry-delay 3 --connect-timeout 30 `
        --range "$start-$end" --output $partPath $Url
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed for byte range $start-$end"
    }

    $actualPartBytes = (Get-Item -LiteralPath $partPath).Length
    if ($actualPartBytes -ne $expectedPartBytes) {
        throw "Invalid chunk $index size: expected $expectedPartBytes, received $actualPartBytes"
    }
    Write-Host ("chunk {0}/{1} verified ({2:N1} MiB)" -f ($index + 1), $chunkCount, ($actualPartBytes / 1MB))
}

$output = [System.IO.File]::Open($resolvedOutput, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try {
    for ($index = 0; $index -lt $chunkCount; $index++) {
        $partPath = Join-Path $partRoot ('part-{0:D4}.bin' -f $index)
        $input = [System.IO.File]::OpenRead($partPath)
        try {
            $input.CopyTo($output)
        }
        finally {
            $input.Dispose()
        }
    }
}
finally {
    $output.Dispose()
}

$actualBytes = (Get-Item -LiteralPath $resolvedOutput).Length
if ($actualBytes -ne $ExpectedBytes) {
    throw "Merged installer size mismatch: expected $ExpectedBytes, received $actualBytes"
}

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedOutput
if ($signature.Status -ne 'Valid') {
    throw "Installer signature is not valid: $($signature.Status)"
}

Write-Host "installer verified: $resolvedOutput"
Write-Host "publisher: $($signature.SignerCertificate.Subject)"
Write-Host "bytes: $actualBytes"

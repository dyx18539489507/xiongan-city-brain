[CmdletBinding()]
param(
    [string]$OutputName = "xiongan-city-brain-docker-$(Get-Date -Format 'yyyyMMdd-HHmmss')",
    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$exportsRoot = if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    Join-Path $workspace 'exports'
}
else {
    [System.IO.Path]::GetFullPath($OutputRoot)
}
$outputPath = Join-Path $exportsRoot $OutputName
$archivePath = "$outputPath.zip"
$archiveHashPath = "$archivePath.sha256"

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$ExtraArgs = @()) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Missing source directory: $Source"
    }
    [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
    $arguments = @(
        $Source,
        $Destination,
        '/E',
        '/COPY:DAT',
        '/DCOPY:DAT',
        '/R:2',
        '/W:1',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP'
    ) + $ExtraArgs
    & robocopy.exe @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed ($LASTEXITCODE): $Source -> $Destination"
    }
}

if ((Test-Path -LiteralPath $outputPath) -or
    (Test-Path -LiteralPath $archivePath) -or
    (Test-Path -LiteralPath $archiveHashPath)) {
    throw "Output already exists; choose another OutputName: $OutputName"
}

[System.IO.Directory]::CreateDirectory($exportsRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($outputPath) | Out-Null

$rootFiles = @(
    '.dockerignore',
    '.env.example',
    'alembic.ini',
    'docker-compose.yml',
    'pyproject.toml',
    'README.md'
)
foreach ($relative in $rootFiles) {
    Copy-Item -LiteralPath (Join-Path $workspace $relative) -Destination $outputPath
}

Copy-Tree (Join-Path $workspace 'src') (Join-Path $outputPath 'src') @(
    '/XD', '__pycache__', '/XF', '*.pyc'
)
Copy-Tree (Join-Path $workspace 'specs') (Join-Path $outputPath 'specs')
Copy-Tree (Join-Path $workspace 'scenarios') (Join-Path $outputPath 'scenarios') @(
    '/XD', '__pycache__', '/XF', '*.pyc', '*.tmp*', 'statistics.xml', 'summary.xml', 'tripinfo.xml'
)
Copy-Tree (Join-Path $workspace 'generated') (Join-Path $outputPath 'generated') @(
    '/XD', '__pycache__', '/XF', '*.pyc', '*.tmp*'
)
Copy-Tree (Join-Path $workspace 'deployment') (Join-Path $outputPath 'deployment') @(
    '/XD', '__pycache__', 'portable', 'docker-delivery', '/XF', '*.pyc'
)
Copy-Tree (Join-Path $workspace 'algorithms') (Join-Path $outputPath 'algorithms')
Copy-Tree (Join-Path $workspace 'apps\web-dashboard') (Join-Path $outputPath 'apps\web-dashboard') @(
    '/XD', 'node_modules', 'dist', 'coverage', 'playwright-report', 'test-results', '/XF', '*.log'
)
Copy-Tree (Join-Path $workspace 'deployment\docker-delivery') $outputPath

Push-Location $outputPath
try {
    & docker compose --env-file .env.example config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Docker Compose configuration is invalid ($LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

$commit = (& git -C $workspace rev-parse HEAD).Trim()
$dirty = [bool](& git -C $workspace status --porcelain)
$packageInfo = @(
    "Package: $OutputName"
    "BuiltAt: $((Get-Date).ToString('o'))"
    "SourceCommit: $commit"
    "SourceWorkingTreeDirty: $dirty"
    'DeliveryMode: Docker online build'
    'Target: Windows 10/11 x64 with Docker Desktop and WSL2'
)
[System.IO.File]::WriteAllLines(
    (Join-Path $outputPath 'PACKAGE-INFO.txt'),
    $packageInfo,
    [System.Text.UTF8Encoding]::new($false)
)

& tar.exe -a -cf $archivePath -C $exportsRoot $OutputName
if ($LASTEXITCODE -ne 0) {
    throw "ZIP creation failed ($LASTEXITCODE)."
}

$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(
    $archiveHashPath,
    "$archiveHash  $([System.IO.Path]::GetFileName($archivePath))`n",
    [System.Text.UTF8Encoding]::new($false)
)

$files = Get-ChildItem -LiteralPath $outputPath -Recurse -File
$sizeMiB = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
$archiveSizeMiB = [math]::Round(((Get-Item -LiteralPath $archivePath).Length / 1MB), 1)
Write-Host "Docker delivery package: $outputPath"
Write-Host "Files: $($files.Count); unpacked size: $sizeMiB MiB"
Write-Host "Archive: $archivePath ($archiveSizeMiB MiB)"
Write-Host "SHA-256: $archiveHash"

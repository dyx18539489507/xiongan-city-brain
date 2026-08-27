[CmdletBinding()]
param(
    [string]$OutputName = "xiongan_city_brain_portable_$(Get-Date -Format 'yyyyMMdd')",
    [string]$RuntimeSource = '',
    [switch]$SkipFrontendBuild,
    [switch]$SkipDependencySync,
    [switch]$SkipArchive,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$exportsRoot = Join-Path $workspace 'exports'
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $exportsRoot $OutputName))
$archivePath = "$outputPath.zip"
$archiveHashPath = "$archivePath.sha256"

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childPath = [System.IO.Path]::GetFullPath($Child)
    if (-not $childPath.StartsWith($parentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside $Parent`: $Child"
    }
}

function Get-CompatibleRelativePath([string]$BasePath, [string]$TargetPath) {
    $normalizedBase = [System.IO.Path]::GetFullPath($BasePath).TrimEnd('\') + '\'
    $normalizedTarget = [System.IO.Path]::GetFullPath($TargetPath)
    $baseUri = [System.Uri]::new($normalizedBase)
    $targetUri = [System.Uri]::new($normalizedTarget)
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()).Replace('/', '\')
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$ExtraArgs = @()) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Missing source directory: $Source"
    }
    [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
    $arguments = @($Source, $Destination, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP') + $ExtraArgs
    & robocopy.exe @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Robocopy failed ($LASTEXITCODE): $Source -> $Destination" }
}

Assert-ChildPath $exportsRoot $outputPath

if ([string]::IsNullOrWhiteSpace($RuntimeSource)) {
    $runtimeSourcePath = Get-ChildItem -LiteralPath $exportsRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            -not [System.IO.Path]::GetFullPath($_.FullName).Equals(
                $outputPath,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            @(
                (Join-Path $_.FullName 'runtime'),
                (Join-Path (Join-Path $_.FullName $_.Name) 'runtime')
            )
        } |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_ 'python\python.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $_ 'sumo\bin\sumo.exe') -PathType Leaf)
        } |
        Select-Object -First 1
    if (-not $runtimeSourcePath) {
        throw 'No reusable portable runtime was found under exports. Pass -RuntimeSource explicitly.'
    }
}
else {
    $runtimeSourcePath = [System.IO.Path]::GetFullPath((Join-Path $workspace $RuntimeSource))
}

foreach ($runtime in @('python\python.exe', 'sumo\bin\sumo.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeSourcePath $runtime) -PathType Leaf)) {
        throw "Runtime source is incomplete: $runtimeSourcePath"
    }
}

if (Test-Path -LiteralPath $outputPath) {
    if (-not $Force) { throw "Output already exists: $outputPath. Use -Force to replace it." }
    Assert-ChildPath $exportsRoot $outputPath
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}
foreach ($existingArchive in @($archivePath, $archiveHashPath)) {
    if (Test-Path -LiteralPath $existingArchive) {
        if (-not $Force) { throw "Output already exists: $existingArchive. Use -Force to replace it." }
        Assert-ChildPath $exportsRoot $existingArchive
        Remove-Item -LiteralPath $existingArchive -Force
    }
}

if (-not $SkipFrontendBuild) {
    Push-Location (Join-Path $workspace 'apps\web-dashboard')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed with exit code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}

[System.IO.Directory]::CreateDirectory($outputPath) | Out-Null
Copy-Tree (Join-Path $runtimeSourcePath 'python') (Join-Path $outputPath 'runtime\python') @('/XD', '__pycache__', '/XF', '*.pyc')
Copy-Tree (Join-Path $runtimeSourcePath 'sumo') (Join-Path $outputPath 'runtime\sumo') @('/XD', '__pycache__', 'contributed', '/XF', '*.pyc')
Copy-Tree (Join-Path $workspace 'src') (Join-Path $outputPath 'src') @('/XD', '__pycache__', '/XF', '*.pyc')
Copy-Tree (Join-Path $workspace 'specs') (Join-Path $outputPath 'specs')
Copy-Tree (Join-Path $workspace 'generated\scenes') (Join-Path $outputPath 'generated\scenes')
Copy-Tree (Join-Path $workspace 'apps\web-dashboard\dist') (Join-Path $outputPath 'web') @('/XF', '*.map')
Copy-Tree (Join-Path $workspace 'scenarios\configs') (Join-Path $outputPath 'scenarios\configs')
Copy-Tree (Join-Path $workspace 'scenarios\disturbances') (Join-Path $outputPath 'scenarios\disturbances')
Copy-Tree (Join-Path $workspace 'scenarios\generated') (Join-Path $outputPath 'scenarios\generated') @(
    '/XD', '__pycache__',
    '/XF', '*.pyc', '*.tmp*', 'statistics.xml', 'summary.xml', 'tripinfo.xml'
)
Copy-Tree (Join-Path $workspace 'scenarios\source') (Join-Path $outputPath 'scenarios\source') @(
    '/XD', '__pycache__', '/XF', '*.pyc', '*.tmp*'
)
if (Test-Path -LiteralPath (Join-Path $workspace 'scenarios\drafts') -PathType Container) {
    Copy-Tree (Join-Path $workspace 'scenarios\drafts') (Join-Path $outputPath 'scenarios\drafts') @(
        '/XD', '__pycache__', '/XF', '*.pyc', '*.tmp*'
    )
}
Copy-Tree (Join-Path $workspace 'deployment\portable') $outputPath
Copy-Item -LiteralPath (Join-Path $workspace 'README.md') -Destination (Join-Path $outputPath 'PROJECT-README.md')
[System.IO.Directory]::CreateDirectory((Join-Path $outputPath 'results')) | Out-Null
[System.IO.Directory]::CreateDirectory((Join-Path $outputPath 'runtime-state\logs')) | Out-Null

$portablePython = Join-Path $outputPath 'runtime\python\python.exe'
$sitePackages = Join-Path $outputPath 'runtime\python\Lib\site-packages'

# Old runtime snapshots may contain editable-install metadata pointing back
# to the build machine. The portable server imports its bundled src tree.
Get-ChildItem -LiteralPath $sitePackages -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like '*iongan_traffic_platform*.dist-info' } |
    Remove-Item -Recurse -Force

if (-not $SkipDependencySync) {
    $dependencyJson = & $portablePython -c @'
import json
import sys
import tomllib

with open(sys.argv[1], "rb") as stream:
    print(json.dumps(tomllib.load(stream)["project"]["dependencies"]))
'@ (Join-Path $workspace 'pyproject.toml')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to read project dependencies.' }
    $projectDependencies = @($dependencyJson | ConvertFrom-Json)
    if ($projectDependencies.Count -gt 0) {
        & $portablePython -m pip install `
            --disable-pip-version-check `
            --no-warn-script-location `
            --timeout 120 `
            --retries 5 `
            @projectDependencies
        if ($LASTEXITCODE -ne 0) { throw "Portable dependency sync failed ($LASTEXITCODE)." }
    }
}
& $portablePython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Portable dependency check failed ($LASTEXITCODE)." }

# cmd.exe requires CRLF batch files. Re-encode the small launchers as ASCII so
# they do not depend on the target computer's active Windows code page.
foreach ($commandFile in (Get-ChildItem -LiteralPath $outputPath -Filter '*.cmd' -File)) {
    $content = [System.IO.File]::ReadAllText($commandFile.FullName)
    $content = [System.Text.RegularExpressions.Regex]::Replace($content, "\r?\n", "`r`n")
    [System.IO.File]::WriteAllText(
        $commandFile.FullName,
        $content,
        [System.Text.Encoding]::ASCII
    )
}

$commit = (& git -C $workspace rev-parse HEAD).Trim()
$dirty = [bool](& git -C $workspace status --porcelain)
$pythonVersion = (& (Join-Path $outputPath 'runtime\python\python.exe') --version 2>&1).ToString().Trim()
$sumoVersion = (& (Join-Path $outputPath 'runtime\sumo\bin\sumo.exe') --version 2>&1 | Select-Object -First 1).ToString().Trim()
$buildInfo = [ordered]@{
    package = $OutputName
    builtAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    sourceCommit = $commit
    sourceWorkingTreeDirty = $dirty
    target = 'Windows 10/11 x64'
    entrypoint = 'START_PLATFORM.cmd'
    defaultUrl = 'http://127.0.0.1:5177/?view=3d'
    python = $pythonVersion
    sumo = $sumoVersion
}
[System.IO.File]::WriteAllText(
    (Join-Path $outputPath 'BUILD-INFO.json'),
    ($buildInfo | ConvertTo-Json -Depth 4),
    [System.Text.UTF8Encoding]::new($false)
)

$criticalFiles = @(
    'START_PLATFORM.cmd',
    'START_3D_DEMO.cmd',
    'START_3D_DEMO.cmd',
    'start_portable.ps1',
    'portable_server.py',
    'runtime\python\python.exe',
    'runtime\sumo\bin\sumo.exe',
    'scenarios\source\hebei-2026-08-21.osm.pbf',
    'scenarios\source\hebei-2026-08-21-roads.sqlite',
    'scenarios\source\hebei-2026-08-21-context.sqlite',
    'web\index.html',
    'web\unity\index.html',
    'web\unity\Build\unity.loader.js',
    'generated\scenes\xiongan_rongdong_20.scene.json',
    'scenarios\generated\xiongan_rongdong_20\xiongan_rongdong_20.sumocfg'
)
foreach ($relative in $criticalFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $outputPath $relative) -PathType Leaf)) {
        throw "Built package is missing critical file: $relative"
    }
}

$longestArchiveEntry = Get-ChildItem -LiteralPath $outputPath -Recurse -File |
    ForEach-Object {
        "$OutputName/$((Get-CompatibleRelativePath $outputPath $_.FullName).Replace('\', '/'))"
    } |
    Sort-Object Length -Descending |
    Select-Object -First 1
if ($longestArchiveEntry.Length -gt 180) {
    throw "Archive contains an excessively long path ($($longestArchiveEntry.Length) characters): $longestArchiveEntry"
}

$manifestLines = [System.Collections.Generic.List[string]]::new()
$packageFiles = Get-ChildItem -LiteralPath $outputPath -Recurse -File |
    Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
    Sort-Object FullName
foreach ($file in $packageFiles) {
    $relative = (Get-CompatibleRelativePath $outputPath $file.FullName).Replace('\', '/')
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifestLines.Add("$hash  $relative")
}
[System.IO.File]::WriteAllLines(
    (Join-Path $outputPath 'SHA256SUMS.txt'),
    $manifestLines,
    [System.Text.UTF8Encoding]::new($false)
)

if (-not $SkipArchive) {
    & (Join-Path $outputPath 'runtime\python\python.exe') `
        (Join-Path $PSScriptRoot 'create_portable_zip.py') `
        --package $outputPath `
        --archive $archivePath `
        --manifest (Join-Path $outputPath 'SHA256SUMS.txt')
    if ($LASTEXITCODE -ne 0) {
        throw "Portable ZIP creation failed (exit code $LASTEXITCODE)."
    }
    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText(
        $archiveHashPath,
        "$archiveHash  $([System.IO.Path]::GetFileName($archivePath))`n",
        [System.Text.UTF8Encoding]::new($false)
    )
}

$files = Get-ChildItem -LiteralPath $outputPath -Recurse -File
$sizeMiB = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "Portable package built: $outputPath"
Write-Host "Files: $($files.Count); size: $sizeMiB MiB"
if (-not $SkipArchive) { Write-Host "Archive: $archivePath" }

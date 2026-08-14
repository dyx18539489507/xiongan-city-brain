param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "bootstrap", "validate", "generate-demo-scenario", "generate-3d-scene", "up", "down",
        "demo", "demo-gui", "benchmark", "benchmark-smoke", "fault-demo",
        "report", "test", "lint", "e2e"
    )]
    [string]$Task
)

$ErrorActionPreference = "Stop"
$python = if (Test-Path ".venv\Scripts\python.exe") {
    ".venv\Scripts\python.exe"
} else {
    "python"
}
$envFile = if (Test-Path ".env") { ".env" } else { ".env.example" }

switch ($Task) {
    "bootstrap" {
        & $python -m pip install -e ".[dev]"
        Push-Location "apps\web-dashboard"
        try { npm ci } finally { Pop-Location }
    }
    "validate" {
        & $python -m traffic_platform.cli validate
        & $python -m traffic_platform.cli generate-demo-scenario --verify-only
        Push-Location "apps\web-dashboard"
        try { npm run build } finally { Pop-Location }
    }
    "generate-demo-scenario" {
        & $python -m traffic_platform.cli generate-demo-scenario
        & $python -m traffic_platform.cli official-inventory
        & $python -m traffic_platform.cli transfer-parameters
    }
    "generate-3d-scene" {
        & $python -m traffic_platform.cli generate-3d-scene
    }
    "up" {
        $env:COMPOSE_BAKE = "false"
        $env:DOCKER_BUILDKIT = "0"
        docker compose --env-file $envFile up -d --build
    }
    "down" { docker compose --env-file $envFile down }
    "demo" { & $python -m traffic_platform.cli demo --algorithm coordinated-max-pressure --duration 30 --output results/demo }
    "demo-gui" { & $python -m traffic_platform.cli demo --algorithm coordinated-max-pressure --duration 120 --gui --output results/demo-gui }
    "benchmark" { & $python -m traffic_platform.cli benchmark --duration 1800 --seeds 11 23 37 41 59 --output results/benchmark }
    "benchmark-smoke" { & $python -m traffic_platform.cli benchmark --duration 20 --seeds 11 --output results/benchmark-smoke }
    "fault-demo" { & $python -m traffic_platform.cli demo --algorithm coordinated-max-pressure --duration 70 --cloud-outage --accelerate-disturbances --output results/fault-demo }
    "report" { & $python -m traffic_platform.cli latest-report --output results/report-latest }
    "test" {
        & $python -m pytest
        Push-Location "apps\web-dashboard"
        try { npm test } finally { Pop-Location }
    }
    "lint" {
        & $python -m ruff check src tests deployment
        & $python -m mypy src
        Push-Location "apps\web-dashboard"
        try { npm run build } finally { Pop-Location }
    }
    "e2e" {
        & $python -m pytest tests\e2e tests\chaos -m "e2e or chaos"
        Push-Location "apps\web-dashboard"
        try { npm run e2e } finally { Pop-Location }
    }
}

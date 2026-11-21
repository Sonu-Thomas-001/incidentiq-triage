# One-shot local setup (Windows PowerShell). Run from the repo root:
#   .\scripts\setup.ps1 [-DemoPassword <pw>] [-Train] [-SkipFrontend]
# -Train downloads the public datasets and trains the models (several minutes).
param(
    [string]$DemoPassword = "",
    [switch]$Train,
    [switch]$SkipFrontend
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path backend\.venv)) { python -m venv backend\.venv }
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements-lock.txt

if (-not (Test-Path backend\.env)) { Copy-Item .env.example backend\.env }
if ($DemoPassword) { $env:DEMO_PASSWORD = $DemoPassword }

Push-Location backend
& $py -m alembic upgrade head
& $py -m app.db.seed
Pop-Location

if ($Train) {
    Push-Location ml
    $env:PYTHONPATH = "src"
    & $py -m incidentiq_ml all
    Pop-Location
}
if (-not $SkipFrontend) {
    Push-Location frontend
    npm ci
    Pop-Location
}
Write-Host "Setup done. Start the app with .\scripts\dev.ps1"

# TaxKernel Production - Setup and Run Helper Script
# This script sets up a local Python virtual environment, installs dependencies, and launches the server.

$ErrorActionPreference = "Stop"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "          TaxKernel Production Edge Hub          " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Locate Python (with dynamic environment path recovery for newly installed packages)
$pythonExe = "python"
$pythonVersion = $null
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $candidateVersion = (& python --version 2>&1 | Out-String).Trim()
    if ($candidateVersion -match "^Python 3\.") {
        $pythonVersion = $candidateVersion
        Write-Host "Found Python in PATH: $pythonVersion" -ForegroundColor Green
    }
}

if (-not $pythonVersion) {
    # Check the winget user-scope install location for this account
    $candidateRoots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312")
    )
    $foundRoot = $candidateRoots | Where-Object { Test-Path (Join-Path $_ "python.exe") } | Select-Object -First 1

    if ($foundRoot) {
        Write-Host "Located newly installed Python at: $foundRoot" -ForegroundColor Green
        $env:PATH = "$foundRoot;" + (Join-Path $foundRoot "Scripts") + ";" + $env:PATH
        $pythonExe = Join-Path $foundRoot "python.exe"
    } else {
        Write-Host "[ERROR] Python was not found." -ForegroundColor Red
        Write-Host "Install it with: winget install --id Python.Python.3.11 --exact" -ForegroundColor Yellow
        Write-Host "Ensure 'Add Python to PATH' is selected during installation." -ForegroundColor Yellow
        Exit
    }
}

# 2. Setup virtual environment
$venvDir = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path $venvDir)) {
    Write-Host "Creating Python Virtual Environment in $venvDir..." -ForegroundColor Cyan
    & $pythonExe -m venv .venv
    Write-Host "Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "Using existing Virtual Environment." -ForegroundColor Green
}

# 3. Activate virtual environment
$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& $activateScript

# 4. Install dependencies
Write-Host "Checking and installing dependencies from requirements.txt..." -ForegroundColor Cyan
python -m pip install --upgrade pip
pip install -r requirements.txt
Write-Host "Dependencies successfully verified." -ForegroundColor Green

# 5. Run automated tests
Write-Host ""
Write-Host "Running automated production test suite..." -ForegroundColor Cyan
python -m unittest test_production.py
Write-Host "All tests verified successfully!" -ForegroundColor Green
Write-Host ""

# 6. Launch Uvicorn Edge Hub
Write-Host "Starting TaxKernel Edge Hub server at http://localhost:8000..." -ForegroundColor Cyan
Write-Host "Presentation surface: http://localhost:8000/present" -ForegroundColor Cyan
Write-Host "Make sure paired devices are on the same local network." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to terminate the server." -ForegroundColor Yellow
Write-Host ""

uvicorn main:app --host 0.0.0.0 --port 8000

# Start the RAG backend for Windows
# Assumes python is on the PATH

$ErrorActionPreference = "Stop"

# Get current script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Check if 'uv' is installed for ultra-fast dependency management
$hasUv = $false
try {
    & uv --version > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        $hasUv = $true
    }
} catch {}

# Create virtual environment if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    if ($hasUv) {
        & uv venv
    } else {
        python -m venv .venv
    }
}

# Determine venv execution paths
$venvPython = "$scriptDir\.venv\Scripts\python.exe"
$venvUvicorn = "$scriptDir\.venv\Scripts\uvicorn.exe"

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
if ($hasUv) {
    & uv pip install -r requirements.txt
} else {
    # Check if pip.exe is in the venv, otherwise fallback to python -m pip
    if (Test-Path "$scriptDir\.venv\Scripts\pip.exe") {
        $venvPip = "$scriptDir\.venv\Scripts\pip.exe"
        & $venvPip install -q -r requirements.txt
    } else {
        & $venvPython -m pip install -q -r requirements.txt
    }
}

# Try to start Qdrant via Docker if Docker is running
Write-Host "Checking Docker status..." -ForegroundColor Cyan
$dockerRunning = $false
try {
    # Check if docker daemon is running
    & docker ps > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dockerRunning = $true
    }
} catch {
    # Docker not installed or command failed
}

if ($dockerRunning) {
    Write-Host "Docker is running. Starting Qdrant container..." -ForegroundColor Green
    $qdrantRunning = & docker ps --format '{{.Names}}' | Select-String "^qdrant$"
    if (-not $qdrantRunning) {
        & docker run -d --name qdrant -p 6333:6333 -v "$($scriptDir)/qdrant_data:/qdrant/storage" qdrant/qdrant
        Write-Host "Qdrant started in Docker." -ForegroundColor Green
    } else {
        Write-Host "Qdrant is already running in Docker." -ForegroundColor Green
    }
} else {
    Write-Host "Docker is offline or not installed. RAG backend will use local fallback mode (SQLite persistence)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Starting RAG backend on http://localhost:8000" -ForegroundColor Cyan
Write-Host "Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

& $venvUvicorn main:app --reload --host 0.0.0.0 --port 8000

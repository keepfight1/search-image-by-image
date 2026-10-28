param(
    [ValidateSet("launcher", "backend", "frontend")]
    [string]$Mode = "launcher"
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$frontendDir = Join-Path $projectDir "frontend"
$backendDir = Join-Path $projectDir "backend"

function Get-NodeExecutable {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -ne $nodeCommand) {
        return $nodeCommand.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "nodejs\node.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return $null
}

if ($Mode -eq "backend") {
    $Host.UI.RawUI.WindowTitle = "Cat Search Platform - Backend"
    $env:BACKEND_EMBEDDING_PROVIDER = "onnx"
    $env:BACKEND_ENABLE_LEGACY = "0"
    $env:BACKEND_THRESHOLDS = '{"cat":0.45,"dog":0.68}'
    Set-Location -LiteralPath $backendDir
    & $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    exit $LASTEXITCODE
}

if ($Mode -eq "frontend") {
    $Host.UI.RawUI.WindowTitle = "Cat Search Platform - Frontend"
    $nodeExe = Get-NodeExecutable
    if ($null -eq $nodeExe) {
        throw "Node.js was not found."
    }
    Set-Location -LiteralPath $frontendDir
    & $nodeExe (Join-Path $frontendDir "node_modules\vite\bin\vite.js") --host 127.0.0.1
    exit $LASTEXITCODE
}

function Test-ListeningPort {
    param([int]$Port)

    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-WithMessage {
    param([string]$Message)

    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

Write-Host "Checking the local environment..." -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    Stop-WithMessage "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules") -PathType Container)) {
    Stop-WithMessage "Frontend dependencies are missing. Run npm install in $frontendDir first."
}

if (-not (Test-Path -LiteralPath (Join-Path $projectDir "models\pet-recognition-base.onnx") -PathType Leaf)) {
    Stop-WithMessage "Missing models\pet-recognition-base.onnx"
}

if (-not (Test-Path -LiteralPath (Join-Path $projectDir "models\rfdetr-nano.onnx") -PathType Leaf)) {
    Stop-WithMessage "Missing models\rfdetr-nano.onnx"
}

$nodeExe = Get-NodeExecutable
if ($null -eq $nodeExe) {
    Stop-WithMessage "Node.js was not found. Install Node.js and try again."
}

$scriptPath = $PSCommandPath

if (Test-ListeningPort -Port 8000) {
    Write-Host "Backend port 8000 is already running; skipped duplicate startup."
} else {
    Write-Host "Starting backend at http://127.0.0.1:8000"
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$scriptPath`"",
        "-Mode", "backend"
    )
}

if (Test-ListeningPort -Port 5173) {
    Write-Host "Frontend port 5173 is already running; skipped duplicate startup."
} else {
    Write-Host "Starting frontend at http://127.0.0.1:5173"
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$scriptPath`"",
        "-Mode", "frontend"
    )
}

Write-Host "Waiting for the web page..."
$deadline = (Get-Date).AddSeconds(20)
do {
    if (Test-ListeningPort -Port 5173) {
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

Start-Process "http://127.0.0.1:5173/"
Write-Host "Startup complete. Close the backend and frontend windows to stop the platform." -ForegroundColor Green

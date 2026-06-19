# YE AI Coding Assistant — Windows Installer
# Usage: .\install.ps1
# Run in PowerShell: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned (if needed)

$ErrorActionPreference = "Stop"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $BackendDir ".venv"
$EnvFile = Join-Path $BackendDir ".env"

function Write-Info($msg)  { Write-Host "[YE] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[YE] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[YE] $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "[YE] $msg" -ForegroundColor Red }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  YE AI Coding Assistant - Installer" -ForegroundColor White
Write-Host "  ------------------------------------" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Check Python ──────────────────────────────────────────────────────────
Write-Info "Checking Python..."

$py = $null
$candidates = @("python", "python3", "py")

foreach ($cmd in $candidates) {
    try {
        $ver = & $cmd --version 2>&1 | Select-String -Pattern "(\d+)\.(\d+)"
        if ($ver) {
            $major = [int]$ver.Matches[0].Groups[1].Value
            $minor = [int]$ver.Matches[0].Groups[2].Value
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $py = $cmd
                Write-Ok "Found Python: $py ($(& $py --version 2>&1))"
                break
            }
        }
    } catch { }
}

if (-not $py) {
    Write-Err "Python >= 3.10 not found."
    Write-Host ""
    Write-Info "Install Python 3.10+:"
    Write-Info "  Download from: https://www.python.org/downloads/"
    Write-Info "  Or use winget:  winget install Python.Python.3.12"
    exit 1
}

# ── 2. Create venv ───────────────────────────────────────────────────────────
if (Test-Path $VenvDir) {
    Write-Info "Virtual environment already exists at $VenvDir"
} else {
    Write-Info "Creating virtual environment..."
    & $py -m venv $VenvDir
    Write-Ok "Virtual environment created."
}

# ── 3. Install dependencies ──────────────────────────────────────────────────
Write-Info "Installing dependencies (this may take a minute)..."
$pip = Join-Path $VenvDir "Scripts\pip.exe"
& $pip install --upgrade pip --quiet 2>&1 | Out-Null
& $pip install -e $BackendDir 2>&1 | Select-String -Pattern "(Successfully|ERROR|error)" | ForEach-Object { Write-Host "  $_" }
Write-Ok "Dependencies installed."

# ── 4. Setup .env ────────────────────────────────────────────────────────────
if ((Test-Path $EnvFile) -and ((Get-Content $EnvFile -Raw) -match "ZHIPU_API_KEY=.+") -and (-not (Get-Content $EnvFile -Raw).Contains("your-api-key-here"))) {
    Write-Ok ".env already configured with API key."
} else {
    Write-Host ""
    Write-Warn "ZHIPU_API_KEY is required to use YE."
    Write-Info "Get your API key from: https://open.bigmodel.cn/"
    Write-Host ""
    $apiKey = Read-Host "[YE] Enter your ZHIPU_API_KEY (or press Enter to skip)"

    if (-not $apiKey) { $apiKey = "your-api-key-here" }

    $secretKey = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 32 | ForEach-Object { [char]$_ })

    @"
# YE AI Coding Assistant Configuration
# Get your API key from https://open.bigmodel.cn/

ZHIPU_API_KEY=$apiKey
ZHIPU_MODEL=glm-5.1
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4/

# Server
HOST=0.0.0.0
PORT=8765

# Security (change in production)
SECRET_KEY=$secretKey

# Data directory
DATA_DIR=./data
"@ | Set-Content -Path $EnvFile -Encoding UTF8

    if ($apiKey -eq "your-api-key-here") {
        Write-Warn "No API key provided. Edit $EnvFile before running ye."
    } else {
        Write-Ok ".env configured."
    }
}

# ── 5. Print success ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ====================================  " -ForegroundColor Green
Write-Host "       YE installed successfully!        " -ForegroundColor Green
Write-Host "  ====================================  " -ForegroundColor Green
Write-Host ""
Write-Host "  Start YE:"
Write-Host "    cd $BackendDir" -ForegroundColor Cyan
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "    ye" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quick test:"
Write-Host "    ye -p `"Hello, introduce yourself`"" -ForegroundColor Cyan
Write-Host ""

if ((Test-Path $EnvFile) -and ((Get-Content $EnvFile -Raw).Contains("your-api-key-here"))) {
    Write-Host "  Don't forget to set ZHIPU_API_KEY in $EnvFile" -ForegroundColor Yellow
    Write-Host ""
}

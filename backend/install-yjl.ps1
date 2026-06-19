# YE AI Coding Assistant — install the `yjl` terminal command (Windows)
#
# Creates a `yjl.bat` wrapper in a directory that is already on your PATH,
# so you can launch the LATEST source tree from anywhere with:  yjl
#
# Unlike the old bundled ye.exe (a 143 MB PyInstaller snapshot frozen at build
# time), `yjl` always runs the current app/ source via `python -m app.cli.main`.
#
# Usage:
#   .\install-yjl.ps1             # auto-pick a writable PATH dir
#   .\install-yjl.ps1 -TargetDir "G:\ye-bin"
#   .\install-yjl.ps1 -Uninstall  # remove the wrapper

param(
    [string]$TargetDir = "",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$WrapperName = "yjl.bat"

function Write-Info($m) { Write-Host "[yjl] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[yjl] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[yjl] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[yjl] $m" -ForegroundColor Red }

# --- Uninstall mode -----------------------------------------------------------
if ($Uninstall) {
    $removed = @()
    foreach ($dir in ($env:Path -split ';')) {
        if (-not $dir) { continue }
        $candidate = Join-Path $dir $WrapperName
        if (Test-Path $candidate) {
            try {
                Remove-Item $candidate -Force
                $removed += $candidate
            } catch { }
        }
    }
    if ($removed.Count) {
        Write-Ok "Removed wrapper(s):"
        $removed | ForEach-Object { Write-Host "  - $_" }
    } else {
        Write-Warn "No '$WrapperName' found on PATH. Nothing to remove."
    }
    return
}

# --- Locate python ------------------------------------------------------------
$py = $null
foreach ($cmd in @("py", "python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python\s+(\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $py = $cmd
                break
            }
        }
    } catch { }
}
if (-not $py) {
    Write-Err "Python >= 3.10 not found. Install it first."
    exit 1
}

# Verify the `app` package is importable (editable install must be present).
$importCheck = & $py -c "import app.cli.main" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "The `app` package is not importable by '$py'."
    Write-Err "Run the main installer first:  .\install.ps1"
    Write-Err $importCheck
    exit 1
}
Write-Ok "Using launcher: $py (can import app.cli.main)"

# --- Pick a writable target directory ----------------------------------------
# Preference order:
#   1. -TargetDir (explicit)
#   2. Any PATH dir that already contains ye.exe / ye.bat (siblings)
#   3. Any PATH dir whose name suggests it (contains "ye-bin" or "ye")
#   4. The first writable dir on PATH
#   5. A freshly-created ~/bin
$candidates = @()
if ($TargetDir) {
    $candidates += $TargetDir
} else {
    foreach ($d in ($env:Path -split ';')) {
        if (-not $d -or -not (Test-Path $d)) { continue }
        if ((Test-Path (Join-Path $d "ye.exe")) -or (Test-Path (Join-Path $d "ye.bat"))) {
            $candidates += $d
        }
    }
    foreach ($d in ($env:Path -split ';')) {
        if (-not $d -or -not (Test-Path $d)) { continue }
        if ($d -match "ye") { $candidates += $d }
    }
    foreach ($d in ($env:Path -split ';')) {
        if ($d -and (Test-Path $d)) { $candidates += $d }
    }
    $candidates += @(
        "$env:USERPROFILE\bin",
        "$env:LOCALAPPDATA\Programs\yjl"
    )
}
# De-duplicate while preserving order.
$seen = @{} ; $candidates = @($candidates | Where-Object { $_ -and -not $seen.ContainsKey($_) -and ($seen[$_]=$true) })

$targetDir = $null
foreach ($d in $candidates) {
    try {
        $test = Join-Path $d ".yjl-write-test"
        [IO.File]::WriteAllText($test, "x")
        Remove-Item $test -Force
        $targetDir = $d
        break
    } catch { }
}
if (-not $targetDir) {
    # Last resort: create a user bin dir and add it to PATH.
    $targetDir = "$env:USERPROFILE\bin"
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$targetDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$targetDir", "User")
        Write-Warn "Created $targetDir and added it to your User PATH."
        Write-Warn "Open a NEW terminal for PATH changes to take effect."
    }
}

# --- Write the wrapper --------------------------------------------------------
$wrapperPath = Join-Path $targetDir $WrapperName

# Build the batch body. %* forwards all args (quotes preserved by CMD).
# We prefer `py -3` when available, else fall back to `python`.
$body = @"
@echo off
rem Auto-generated wrapper for the YE AI coding assistant (yjl).
rem Runs the live app/ source tree via `python -m app.cli.main`.
rem Regenerate with:  install-yjl.ps1
setlocal
set "YE_PY=py"
set "YE_CMD=yjl"
rem Force UTF-8 so box-drawing glyphs and the spinner render correctly in CMD.
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
where py >nul 2>nul
if errorlevel 1 set "YE_PY=python"
"%YE_PY%" -m app.cli.main %*
endlocal
"@

[IO.File]::WriteAllText($wrapperPath, $body, [Text.Encoding]::ASCII)
Write-Ok "Installed: $wrapperPath"
Write-Host ""
Write-Host "  Now run from any directory:" -ForegroundColor White
Write-Host "    yjl                       " -ForegroundColor Cyan
Write-Host "    yjl --version             " -ForegroundColor Cyan
Write-Host "    yjl -p `"Hello`"           " -ForegroundColor Cyan
Write-Host "    yjl -r                    (resume last session)" -ForegroundColor Cyan
Write-Host ""
if ($targetDir -notin ($env:Path -split ';')) {
    Write-Warn "$targetDir is not on the current PATH."
    Write-Warn "Open a NEW terminal, or add it manually."
}
Write-Host "  Tip: the same `ye` console-script is also registered by install.ps1." -ForegroundColor DarkGray
Write-Host "  To remove: .\install-yjl.ps1 -Uninstall" -ForegroundColor DarkGray

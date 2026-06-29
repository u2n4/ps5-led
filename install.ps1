# ============================================================
#  DualLED Pro - one-shot installer for Windows (PowerShell)
#  Installs Python (if missing) + dependencies, then launches.
#  Usage (paste in PowerShell):
#    irm https://raw.githubusercontent.com/u2n4/dualled-pro/main/install.ps1 | iex
# ============================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster downloads

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }

Write-Host @"
============================================
   DualLED Pro - automatic installer
   PS5 DualSense / PS4 DualShock 4 RGB
============================================
"@ -ForegroundColor Magenta

# --- 0. Where to install -----------------------------------------------------
$InstallDir = Join-Path $env:LOCALAPPDATA "DualLED-Pro"
$AppFile    = Join-Path $InstallDir "dualled_pro.py"
$ReqFile    = Join-Path $InstallDir "requirements.txt"
$RawBase    = "https://raw.githubusercontent.com/u2n4/dualled-pro/main"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# --- helper: refresh PATH so a freshly-installed python is visible -----------
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine, $user | Where-Object { $_ }) -join ";"
}

# --- helper: find a working python command -----------------------------------
function Get-PythonCmd {
    foreach ($c in @("python", "py")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $v = & $c --version 2>&1
                if ($v -match "Python 3\.(8|9|1[0-9])") { return $c }
            } catch { }
        }
    }
    return $null
}

# --- 1. Ensure Python --------------------------------------------------------
Write-Step "Checking for Python 3.8+ ..."
$py = Get-PythonCmd
if (-not $py) {
    Write-Warn "Python not found. Installing it for you (this may take a minute)..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Python.Python.3.12 --exact --silent `
            --accept-package-agreements --accept-source-agreements --scope user
    } else {
        Write-Warn "winget not available. Downloading the official Python installer..."
        $tmp = Join-Path $env:TEMP "python-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $tmp
        Start-Process -FilePath $tmp -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
    }
    Refresh-Path
    $py = Get-PythonCmd
    if (-not $py) {
        Write-Warn "Python installed but not visible in this window."
        Write-Warn "CLOSE PowerShell, open a NEW PowerShell window, and paste the command again."
        return
    }
}
Write-Ok ("Using " + (& $py --version 2>&1))

# --- 2. Download the app -----------------------------------------------------
Write-Step "Downloading DualLED Pro ..."
Invoke-WebRequest -Uri "$RawBase/dualled_pro.py"   -OutFile $AppFile
Invoke-WebRequest -Uri "$RawBase/requirements.txt" -OutFile $ReqFile
Write-Ok "Downloaded to $InstallDir"

# --- 3. Install dependencies -------------------------------------------------
Write-Step "Installing dependencies (psutil, hidapi, pydualsense) ..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install --user -r $ReqFile --quiet
Write-Ok "Dependencies installed"

# --- 4. Launch ---------------------------------------------------------------
Write-Step "Launching DualLED Pro ..."
Write-Ok "Done! The app window should open now."
Write-Host "`n    To run it again later, paste:" -ForegroundColor DarkGray
Write-Host "    & '$py' '$AppFile'`n" -ForegroundColor White
& $py $AppFile

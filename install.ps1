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
$IcoFile    = Join-Path $InstallDir "app.ico"
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
        winget install --id Python.Python.3.12 --exact --version 3.12.7 --silent `
            --accept-package-agreements --accept-source-agreements --scope user
    } else {
        Write-Warn "winget not available. Downloading the official Python installer..."
        # Random temp name closes the predictable-path TOCTOU swap window.
        $tmp = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + ".exe")
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $tmp
        # Verify the installer is Authenticode-signed by the Python Software Foundation
        # before running it silently — refuse a tampered/unsigned binary.
        $sig = Get-AuthenticodeSignature $tmp
        if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            Write-Warn "Python installer failed signature verification — aborting for your safety."
            Write-Warn "Please install Python 3.12 manually from https://www.python.org and re-run this command."
            return
        }
        Start-Process -FilePath $tmp -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
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
# App icon for the Desktop shortcuts + window (best-effort; shortcuts fall back to python's icon).
try { Invoke-WebRequest -Uri "$RawBase/assets/app.ico" -OutFile $IcoFile } catch { Write-Warn "Icon download skipped." }
Write-Ok "Downloaded to $InstallDir"

# --- 3. Install dependencies -------------------------------------------------
Write-Step "Installing dependencies (psutil, hidapi, pydualsense) ..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install --user -r $ReqFile --quiet
Write-Ok "Dependencies installed"

# --- 4. Create Desktop shortcuts ---------------------------------------------
# WScript.Shell's COM .Save() corrupts Unicode (e.g. Arabic) destination paths —
# common on OneDrive desktops like "...\OneDrive\سطح المكتب" — so we create each
# .lnk in an ASCII temp folder and then Move-Item it to the real Desktop (the
# .NET move is Unicode-safe and the .lnk is self-contained).
function New-DLShortcut {
    param([string]$Name, [string]$Target, [string]$Arguments, [int]$WindowStyle, [string]$Description, [string]$IconPath)
    $desktop = [Environment]::GetFolderPath("Desktop")
    $tmpDir  = Join-Path $env:TEMP ("dlb_" + [guid]::NewGuid().ToString("N").Substring(0,8))
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    $tmpLnk  = Join-Path $tmpDir "s.lnk"
    try {
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($tmpLnk)
        $sc.TargetPath       = $Target
        $sc.Arguments        = $Arguments
        $sc.WorkingDirectory = $InstallDir
        $sc.WindowStyle      = $WindowStyle
        $sc.Description       = $Description
        if ($IconPath -and (Test-Path $IconPath)) { $sc.IconLocation = $IconPath }
        $sc.Save()
        $final = Join-Path $desktop ($Name + ".lnk")
        Move-Item -LiteralPath $tmpLnk -Destination $final -Force
        return $true
    } finally {
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Step "Creating Desktop shortcuts ..."
try {
    # Prefer pythonw.exe (runs with no black console window)
    $pyExe = (Get-Command $py -ErrorAction Stop).Source
    $pyDir = Split-Path $pyExe -Parent
    $pyw   = Join-Path $pyDir "pythonw.exe"
    $launcher = if (Test-Path $pyw) { $pyw } else { $pyExe }
    $iconArg  = if (Test-Path $IcoFile) { $IcoFile } else { "$launcher,0" }

    # ONE shortcut. Background + stop live INSIDE the app now (the "Run in
    # background" button hides the window to the tray while the lightbar keeps
    # running; closing/Stop turns it off) — no extra Desktop icons.
    New-DLShortcut -Name "DualLED Pro" -Target $launcher `
        -Arguments ('"' + $AppFile + '"') -WindowStyle 1 `
        -Description "DualLED Pro - PS5/PS4 RGB lightbar control" -IconPath $iconArg | Out-Null
    Write-Ok "Shortcut created on your Desktop: 'DualLED Pro'"

    # Clean up the old multi-shortcut layout from previous installs, if present.
    $desktop = [Environment]::GetFolderPath("Desktop")
    foreach ($old in @("DualLED Pro (Background).lnk", "Stop DualLED Background.lnk")) {
        $p = Join-Path $desktop $old
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
} catch {
    Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message)). You can still run the app from PowerShell."
}

# --- 5. Launch ---------------------------------------------------------------
Write-Step "Launching DualLED Pro ..."
Write-Ok "Done! The app window should open now."
Write-Host "`n    Next time, just double-click 'DualLED Pro' on your Desktop." -ForegroundColor DarkGray
Write-Host "    To run it in the background, use the 'Run in background' button inside the app." -ForegroundColor DarkGray
& $py $AppFile

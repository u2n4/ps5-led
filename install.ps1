# ============================================================
#  DualLED Pro - one-shot installer for Windows (PowerShell)
#  Preferred path: portable single EXE (NO Python needed).
#  Fallback path : Python (minimal footprint) + 3 small deps.
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
$ExeFile    = Join-Path $InstallDir "DualLED-Pro.exe"
$RawBase    = "https://raw.githubusercontent.com/u2n4/dualled-pro/main"
$ExeUrl     = "https://github.com/u2n4/dualled-pro/releases/latest/download/DualLED-Pro.exe"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# --- helper: Desktop shortcut (Unicode-safe move; see note below) -------------
# WScript.Shell's COM .Save() corrupts Unicode (e.g. Arabic) destination paths -
# common on OneDrive desktops like "...\OneDrive\<arabic>" - so we create each
# .lnk in an ASCII temp folder and then Move-Item it to the real Desktop.
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
        $sc.Description      = $Description
        if ($IconPath -and (Test-Path $IconPath)) { $sc.IconLocation = $IconPath }
        $sc.Save()
        $final = Join-Path $desktop ($Name + ".lnk")
        Move-Item -LiteralPath $tmpLnk -Destination $final -Force
        return $true
    } finally {
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Remove-OldShortcuts {
    $desktop = [Environment]::GetFolderPath("Desktop")
    foreach ($old in @("DualLED Pro (Background).lnk", "Stop DualLED Background.lnk")) {
        $p = Join-Path $desktop $old
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
}

# ==============================================================================
#  PATH A - portable EXE (preferred): one file, zero dependencies, no Python.
# ==============================================================================
Write-Step "Downloading DualLED Pro portable (no Python needed) ..."
$exeOk = $false
try {
    Invoke-WebRequest -Uri $ExeUrl -OutFile $ExeFile
    if ((Get-Item $ExeFile).Length -gt 5MB) { $exeOk = $true }
} catch { }

if ($exeOk) {
    Write-Ok "Portable app downloaded ($([math]::Round((Get-Item $ExeFile).Length / 1MB, 1)) MB)"
    try { Invoke-WebRequest -Uri "$RawBase/assets/app.ico" -OutFile $IcoFile } catch { }
    $iconArg = if (Test-Path $IcoFile) { $IcoFile } else { "$ExeFile,0" }

    Write-Step "Creating Desktop shortcut ..."
    try {
        New-DLShortcut -Name "DualLED Pro" -Target $ExeFile -Arguments "" -WindowStyle 1 `
            -Description "DualLED Pro - PS5/PS4 RGB lightbar control" -IconPath $iconArg | Out-Null
        Remove-OldShortcuts
        Write-Ok "Shortcut created on your Desktop: 'DualLED Pro'"
    } catch {
        Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message))."
    }

    Write-Step "Launching DualLED Pro ..."
    Write-Ok "Done! The app window should open now."
    Write-Host "`n    Next time, just double-click 'DualLED Pro' on your Desktop." -ForegroundColor DarkGray
    Start-Process -FilePath $ExeFile -WorkingDirectory $InstallDir
    return
}

Write-Warn "Portable EXE unavailable - falling back to the Python-based install."

# ==============================================================================
#  PATH B - Python fallback (minimal footprint)
# ==============================================================================

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
    # Minimal footprint: keep only what the app actually needs -
    # core + pip + tcl/tk (Tkinter GUI). No docs, no tests, no IDLE, no dev headers.
    $pyArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=1 " +
              "Include_doc=0 Include_test=0 Include_idle=0 Include_dev=0 " +
              "Include_debug=0 Include_symbols=0 Include_launcher=1"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Python.Python.3.12 --exact --version 3.12.7 --silent `
            --accept-package-agreements --accept-source-agreements --scope user `
            --override $pyArgs
    } else {
        Write-Warn "winget not available. Downloading the official Python installer..."
        # Random temp name closes the predictable-path TOCTOU swap window.
        $tmp = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + ".exe")
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $tmp
        # Verify the installer is Authenticode-signed by the Python Software Foundation
        # before running it silently - refuse a tampered/unsigned binary.
        $sig = Get-AuthenticodeSignature $tmp
        if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            Write-Warn "Python installer failed signature verification - aborting for your safety."
            Write-Warn "Please install Python 3.12 manually from https://www.python.org and re-run this command."
            return
        }
        Start-Process -FilePath $tmp -ArgumentList $pyArgs -Wait
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
# DualSense SVG asset - required for the accurate PS5 controller view.
$AssetsDir = Join-Path $InstallDir "assets"
New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null
try {
    Invoke-WebRequest -Uri "$RawBase/assets/dualsense-svgrepo.svg" -OutFile (Join-Path $AssetsDir "dualsense-svgrepo.svg")
} catch { Write-Warn "DualSense SVG skipped (app falls back to the generic view)." }
# App icon for the Desktop shortcuts + window (best-effort).
try { Invoke-WebRequest -Uri "$RawBase/assets/app.ico" -OutFile $IcoFile } catch { Write-Warn "Icon download skipped." }
Write-Ok "Downloaded to $InstallDir"

# --- 3. Install dependencies -------------------------------------------------
# --no-cache-dir keeps pip from writing a wheel cache to disk;
# no pip self-upgrade - the bundled pip installs these 3 small packages fine.
Write-Step "Installing dependencies (psutil, hidapi, pydualsense) ..."
& $py -m pip install --user -r $ReqFile --quiet --no-cache-dir --no-warn-script-location
Write-Ok "Dependencies installed"

# --- 4. Create Desktop shortcut ----------------------------------------------
Write-Step "Creating Desktop shortcut ..."
try {
    # Prefer pythonw.exe (runs with no black console window)
    $pyExe = (Get-Command $py -ErrorAction Stop).Source
    $pyDir = Split-Path $pyExe -Parent
    $pyw   = Join-Path $pyDir "pythonw.exe"
    $launcher = if (Test-Path $pyw) { $pyw } else { $pyExe }
    $iconArg  = if (Test-Path $IcoFile) { $IcoFile } else { "$launcher,0" }

    New-DLShortcut -Name "DualLED Pro" -Target $launcher `
        -Arguments ('"' + $AppFile + '"') -WindowStyle 1 `
        -Description "DualLED Pro - PS5/PS4 RGB lightbar control" -IconPath $iconArg | Out-Null
    Remove-OldShortcuts
    Write-Ok "Shortcut created on your Desktop: 'DualLED Pro'"
} catch {
    Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message)). You can still run the app from PowerShell."
}

# --- 5. Launch ---------------------------------------------------------------
Write-Step "Launching DualLED Pro ..."
Write-Ok "Done! The app window should open now."
Write-Host "`n    Next time, just double-click 'DualLED Pro' on your Desktop." -ForegroundColor DarkGray
& $py $AppFile

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

# --- 4. Launch ---------------------------------------------------------------
# --- 4. Create a Desktop shortcut -------------------------------------------
Write-Step "Creating a Desktop shortcut ..."
try {
    # Prefer pythonw.exe (runs with no black console window)
    $pyExe = (Get-Command $py -ErrorAction Stop).Source
    $pyDir = Split-Path $pyExe -Parent
    $pyw   = Join-Path $pyDir "pythonw.exe"
    $launcher = if (Test-Path $pyw) { $pyw } else { $pyExe }

    $desktop  = [Environment]::GetFolderPath("Desktop")
    $lnkPath  = Join-Path $desktop "DualLED Pro.lnk"

    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnkPath)
    $sc.TargetPath       = $launcher
    $sc.Arguments        = '"' + $AppFile + '"'
    $sc.WorkingDirectory = $InstallDir
    $sc.WindowStyle      = 1
    $sc.Description       = "DualLED Pro - PS5/PS4 RGB lightbar control"
    # Use the app icon if present, else fall back to python's icon
    $icoFile = Join-Path $InstallDir "app.ico"
    if (Test-Path $icoFile)      { $sc.IconLocation = $icoFile }
    elseif (Test-Path $launcher) { $sc.IconLocation = "$launcher,0" }
    $sc.Save()
    Write-Ok "Shortcut created on your Desktop: 'DualLED Pro'"

    # Second shortcut: silent background mode (no window at all — just drives the lightbar).
    # Uses pythonw.exe (never a console) + --background (no Tk UI). Lightweight.
    if (Test-Path $pyw) {
        $bgLnk = Join-Path $desktop "DualLED Pro (Background).lnk"
        $sb = $shell.CreateShortcut($bgLnk)
        $sb.TargetPath       = $pyw
        $sb.Arguments        = '"' + $AppFile + '" --background'
        $sb.WorkingDirectory = $InstallDir
        $sb.WindowStyle      = 7          # minimized; pythonw shows nothing anyway
        $sb.Description       = "DualLED Pro - run silently in the background (no window)"
        if (Test-Path $icoFile)      { $sb.IconLocation = $icoFile }
        elseif (Test-Path $pyw)      { $sb.IconLocation = "$pyw,0" }
        $sb.Save()
        Write-Ok "Background shortcut created: 'DualLED Pro (Background)' (runs with no window)"

        # Third shortcut: stop the silent background process cleanly (so it is
        # never an unstoppable hidden process — addresses the no-off-switch risk).
        $stopLnk = Join-Path $desktop "Stop DualLED Background.lnk"
        $st = $shell.CreateShortcut($stopLnk)
        $st.TargetPath       = $pyw
        $st.Arguments        = '"' + $AppFile + '" --stop'
        $st.WorkingDirectory = $InstallDir
        $st.WindowStyle      = 7
        $st.Description       = "DualLED Pro - stop the background process and turn the lightbar off"
        if (Test-Path $icoFile)      { $st.IconLocation = $icoFile }
        elseif (Test-Path $pyw)      { $st.IconLocation = "$pyw,0" }
        $st.Save()
        Write-Ok "Stop shortcut created: 'Stop DualLED Background'"
    }
} catch {
    Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message)). You can still run the app from PowerShell."
}

# --- 5. Launch ---------------------------------------------------------------
Write-Step "Launching DualLED Pro ..."
Write-Ok "Done! The app window should open now."
Write-Host "`n    Next time, just double-click 'DualLED Pro' on your Desktop." -ForegroundColor DarkGray
Write-Host "    For SILENT background (no window): double-click 'DualLED Pro (Background)'." -ForegroundColor DarkGray
$pywExe = Join-Path (Split-Path (Get-Command $py).Source -Parent) "pythonw.exe"
if (Test-Path $pywExe) {
    Write-Host "    Or paste (silent):  & '$pywExe' '$AppFile' --background`n" -ForegroundColor White
}
& $py $AppFile

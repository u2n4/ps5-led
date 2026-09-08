# ============================================================
#  PS5 LED - one-shot installer for Windows (PowerShell)
#  Preferred path: portable single EXE (NO Python needed).
#  Fallback path : Python + two embedded OpenGL viewer packages.
#  Usage (paste in PowerShell):
#    irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | iex
# ============================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster downloads

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }

Write-Host @"
============================================
   PS5 LED - automatic installer
   PS5 DualSense / PS4 DualShock 4 RGB
============================================
"@ -ForegroundColor Magenta

# --- 0. Where to install -----------------------------------------------------
$InstallDir = Join-Path $env:LOCALAPPDATA "DualLED-Pro"
$AppFile    = Join-Path $InstallDir "dualled_pro.py"
$ReqFile    = Join-Path $InstallDir "requirements.txt"
$IcoFile    = Join-Path $InstallDir "app.ico"
$ExeFile    = Join-Path $InstallDir "PS5-LED.exe"
$RawBase    = "https://raw.githubusercontent.com/u2n4/ps5-led/main"
$ExeUrl     = "https://github.com/u2n4/ps5-led/releases/latest/download/PS5-LED.exe"
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
    foreach ($old in @("DualLED Pro.lnk", "DualLED Pro (Background).lnk", "Stop DualLED Background.lnk")) {
        $p = Join-Path $desktop $old
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
    }
}

# ==============================================================================
#  PATH A - portable EXE (preferred): one file, zero dependencies, no Python.
# ==============================================================================
Write-Step "Downloading PS5 LED portable (no Python needed) ..."
$exeOk = $false
# Retry: a single DNS or connection blip is not a reason to fall back to a
# completely different install strategy. Seen in testing -- one lookup failed
# and the installer went off to install a Python runtime instead.
$attempt = 0
while (-not $exeOk -and $attempt -lt 3) {
    $attempt++
    if ($attempt -gt 1) {
        Write-Warn "Download attempt $($attempt - 1) failed; retrying ..."
        Start-Sleep -Seconds 3
    }
    try {
        Invoke-WebRequest -Uri $ExeUrl -OutFile $ExeFile
        if ((Get-Item $ExeFile).Length -gt 5MB) { $exeOk = $true }
    } catch { }
}
try {
    # Integrity: verify against the SHA256 manifest published with the release.
    # Manifest missing (older releases) -> skip; hash mismatch -> reject the EXE.
    if ($exeOk) {
        try {
            $manifest = (Invoke-WebRequest -Uri "$ExeUrl.sha256").Content
            if ($manifest -is [byte[]]) { $manifest = [System.Text.Encoding]::UTF8.GetString($manifest) }
            $expected = ($manifest.Trim() -split "\s+")[0].ToLower()
            $actual = (Get-FileHash $ExeFile -Algorithm SHA256).Hash.ToLower()
            if ($expected.Length -eq 64 -and $actual -ne $expected) {
                Write-Warn "Portable EXE failed SHA256 verification - discarding it."
                Remove-Item $ExeFile -Force -ErrorAction SilentlyContinue
                $exeOk = $false
            }
        } catch { }
    }
} catch { }

if ($exeOk) {
    Write-Ok "Portable app downloaded ($([math]::Round((Get-Item $ExeFile).Length / 1MB, 1)) MB)"
    # The EXE carries its own icon, so the shortcut points at it. Downloading a
    # separate .ico fetched a second file to get a picture the first one
    # already had -- and on this path the whole point is that nothing else
    # comes down.
    $iconArg = "$ExeFile,0"

    Write-Step "Creating Desktop shortcut ..."
    try {
        New-DLShortcut -Name "PS5 LED" -Target $ExeFile -Arguments "" -WindowStyle 1 `
            -Description "PS5 LED - PS5/PS4 RGB lightbar control" -IconPath $iconArg | Out-Null
        Remove-OldShortcuts
        Write-Ok "Shortcut created on your Desktop: 'PS5 LED'"
    } catch {
        Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message))."
    }

    Write-Step "Launching PS5 LED ..."
    Write-Ok "Done! The app window should open now."
    Write-Host "`n    Next time, just double-click 'PS5 LED' on your Desktop." -ForegroundColor DarkGray
    Start-Process -FilePath $ExeFile -WorkingDirectory $InstallDir
    return
}

# Opt-in only. Installing a Python runtime is a much bigger thing than the app
# asked for, and doing it silently after a failed download is how people end up
# with a broken environment they never chose. Default is to stop and say what
# to do.
if (-not $env:PS5LED_ALLOW_PYTHON_INSTALL) {
    Write-Warn ""
    Write-Warn "Could not download the portable app after 3 attempts."
    Write-Warn "Nothing has been installed."
    Write-Warn ""
    Write-Warn "Download it by hand instead - it is one file, about 11 MB:"
    Write-Warn "    https://github.com/u2n4/ps5-led/releases/latest"
    Write-Warn ""
    Write-Warn "Save PS5-LED.exe anywhere and double-click it. Nothing else is needed."
    Write-Warn "(To install from source with Python instead, set"
    Write-Warn " PS5LED_ALLOW_PYTHON_INSTALL=1 and run this again.)"
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
Write-Step "Downloading PS5 LED ..."
Invoke-WebRequest -Uri "$RawBase/dualled_pro.py"   -OutFile $AppFile
Invoke-WebRequest -Uri "$RawBase/requirements.txt" -OutFile $ReqFile
# Keep the native HID package with the Tk application; no driver package needed.
$HidDir = Join-Path $InstallDir "ps5led"
New-Item -ItemType Directory -Force -Path $HidDir | Out-Null
foreach ($module in @("__init__", "hid_win", "dualsense", "dualshock4", "crc", "device")) {
    Invoke-WebRequest -Uri "$RawBase/ps5led/$module.py" -OutFile (Join-Path $HidDir "$module.py")
}
Invoke-WebRequest -Uri "$RawBase/controller_gl.py" -OutFile (Join-Path $InstallDir "controller_gl.py")
Invoke-WebRequest -Uri "$RawBase/ATTRIBUTION.md" -OutFile (Join-Path $InstallDir "ATTRIBUTION.md")
$AssetsDir = Join-Path $InstallDir "assets"
New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null
Invoke-WebRequest -Uri "$RawBase/assets/dualsense.mesh.json.gz" -OutFile (Join-Path $AssetsDir "dualsense.mesh.json.gz")
# SVG is retained for the existing fallback when OpenGL is unavailable.
try {
    Invoke-WebRequest -Uri "$RawBase/assets/dualsense-svgrepo.svg" -OutFile (Join-Path $AssetsDir "dualsense-svgrepo.svg")
} catch { Write-Warn "DualSense SVG skipped (app falls back to the generic view)." }
# App icon for the Desktop shortcuts + window (best-effort).
try { Invoke-WebRequest -Uri "$RawBase/assets/app.ico" -OutFile $IcoFile } catch { Write-Warn "Icon download skipped." }
Write-Ok "Downloaded to $InstallDir"

# --- 3. Optional: the hardware-accelerated 3D viewer -------------------------
# The app REQUIRES nothing. Controller access is the Windows HID driver through
# ctypes, and the preview falls back to the built-in drawing on its own. These
# two packages only upgrade that preview to the real 3D model.
#
# So this is best effort and never fatal. It used to install from
# requirements.txt (which now carries no packages at all, by design) and to
# throw when pip returned non-zero -- which turned "a pip package did not land"
# into "the install failed", the exact failure that used to leave the lightbar
# dead after a PowerShell install.
#
# --no-cache-dir keeps pip from leaving a wheel cache behind.
Write-Step "Installing the optional 3D viewer (PyOpenGL, pyopengltk) ..."
& $py -m pip install --user --quiet --no-cache-dir --no-warn-script-location `
    "PyOpenGL==3.1.10" "pyopengltk==0.0.4"
if ($LASTEXITCODE -eq 0) {
    Write-Ok "3D viewer ready"
} else {
    Write-Warn "Optional 3D viewer not installed. The app still works and still"
    Write-Warn "drives the lightbar; the preview uses the built-in drawing."
}

# --- 4. Create Desktop shortcut ----------------------------------------------
Write-Step "Creating Desktop shortcut ..."
try {
    # Prefer pythonw.exe (runs with no black console window)
    $pyExe = (Get-Command $py -ErrorAction Stop).Source
    $pyDir = Split-Path $pyExe -Parent
    $pyw   = Join-Path $pyDir "pythonw.exe"
    $launcher = if (Test-Path $pyw) { $pyw } else { $pyExe }
    $iconArg  = if (Test-Path $IcoFile) { $IcoFile } else { "$launcher,0" }

    New-DLShortcut -Name "PS5 LED" -Target $launcher `
        -Arguments ('"' + $AppFile + '"') -WindowStyle 1 `
        -Description "PS5 LED - PS5/PS4 RGB lightbar control" -IconPath $iconArg | Out-Null
    Remove-OldShortcuts
    Write-Ok "Shortcut created on your Desktop: 'PS5 LED'"
} catch {
    Write-Warn "Could not create the Desktop shortcut ($($_.Exception.Message)). You can still run the app from PowerShell."
}

# --- 5. Launch ---------------------------------------------------------------
Write-Step "Launching PS5 LED ..."
Write-Ok "Done! The app window should open now."
Write-Host "`n    Next time, just double-click 'PS5 LED' on your Desktop." -ForegroundColor DarkGray
& $py $AppFile

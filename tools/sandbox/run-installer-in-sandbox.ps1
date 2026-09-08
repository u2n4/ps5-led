# Runs the REAL one-liner install on a clean Windows and records exactly what
# lands on disk.
#
# The claim being tested is Ali's: that taking the portable path pulls down one
# EXE and nothing else -- no Python, no pip packages. Reading install.ps1 says
# so; running it on a machine that has never had Python says so with evidence.
#
# Networking is ON here, unlike the other sandbox run: the installer has to
# reach GitHub. Everything it fetches is therefore visible in what it leaves
# behind.

$ErrorActionPreference = 'Continue'
$share  = 'C:\host'
$out    = Join-Path $share 'installer-result'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$report = Join-Path $out 'report.txt'
Set-Content -Path $report -Value "" -Encoding UTF8

function Say($text) {
    $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $text
    Write-Output $line
    Add-Content -Path $report -Value $line -Encoding UTF8
}

Say "Real installer run, clean Windows"
Say ("OS: " + (Get-CimInstance Win32_OperatingSystem).Caption)
$py = Get-Command python -ErrorAction SilentlyContinue
Say ("python before : " + $(if ($py) { $py.Source } else { "not installed" }))

# LogonCommand fires the moment the desktop appears, which is before the
# sandbox's network stack is up: the first attempt failed on DNS one second
# after boot. Wait for name resolution rather than for a fixed number of
# seconds, so a slow start is tolerated and a fast one is not punished.
$netDeadline = (Get-Date).AddSeconds(120)
$online = $false
while ((Get-Date) -lt $netDeadline) {
    try {
        if (Resolve-DnsName 'raw.githubusercontent.com' -ErrorAction Stop) { $online = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
Say ("network ready : " + $online)
if (-not $online) {
    Say "VERDICT: the sandbox never got networking, so the installer was not tested"
    Say "done - results are in the mapped folder"
    exit 1
}

# The exact command a person is told to paste.
Say "running: irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | iex"
$transcript = Join-Path $out 'installer-output.txt'
try {
    Start-Transcript -Path $transcript -Force | Out-Null
    Invoke-RestMethod https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | Invoke-Expression
} catch {
    Say ("installer threw: " + $_.Exception.Message)
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}

Start-Sleep -Seconds 8

# What did it actually put on disk?
# install.ps1 uses LOCALAPPDATA\DualLED-Pro. Guessing 'PS5-LED' listed an
# empty directory and reported "never created" on a run that had in fact
# installed correctly.
$installDir = Join-Path $env:LOCALAPPDATA 'DualLED-Pro'
Say ("install dir : " + $installDir)
if (Test-Path $installDir) {
    Say "--- files it downloaded ---"
    $files = Get-ChildItem $installDir -Recurse -File | Sort-Object FullName
    foreach ($f in $files) {
        Say ("   {0,10:N0}  {1}" -f $f.Length, $f.FullName.Replace($installDir, ''))
    }
    Say ("file count : " + $files.Count)
    Say ("total size : {0:N2} MB" -f (($files | Measure-Object Length -Sum).Sum / 1MB))
} else {
    Say "install directory was never created"
}

# Did it install Python or any pip package behind our back?
$pyAfter = Get-Command python -ErrorAction SilentlyContinue
Say ("python after  : " + $(if ($pyAfter) { $pyAfter.Source } else { "still not installed" }))
$sitePkgs = @()
foreach ($root in @("$env:LOCALAPPDATA\Programs\Python", "$env:APPDATA\Python", "C:\Program Files\Python*")) {
    if (Test-Path $root) { $sitePkgs += $root }
}
Say ("python folders created : " + $(if ($sitePkgs) { $sitePkgs -join ', ' } else { "none" }))

# Is it actually running, and did the 3D come up?
$proc = Get-Process 'PS5-LED' -ErrorAction SilentlyContinue
Say ("app running : " + [bool]$proc)
$log = Join-Path $env:APPDATA 'DualLED_Pro\app.log'
$backend = $null
$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline -and -not $backend) {
    if (Test-Path $log) {
        $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
        if ($text -match 'preview: (OpenGL|built-in drawing)') { $backend = $Matches[1] }
    }
    if (-not $backend) { Start-Sleep -Milliseconds 700 }
}
Say ("preview backend : " + $(if ($backend) { $backend } else { "never logged" }))
if (Test-Path $log) { Copy-Item $log (Join-Path $out 'app.log') -Force }

# Desktop shortcut?
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PS5 LED.lnk'
Say ("desktop shortcut : " + (Test-Path $lnk))

try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    Start-Sleep -Seconds 2
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $out 'installed-screen.png'))
    Say "screenshot saved"
} catch { Say ("screenshot failed: " + $_.Exception.Message) }

Say ""
if ($backend -eq 'OpenGL' -and -not $pyAfter -and -not $sitePkgs) {
    Say "VERDICT: one EXE, no Python, no pip - and the 3D preview came up"
} elseif ($pyAfter -or $sitePkgs) {
    Say "VERDICT: it installed Python or pip packages - the portable path did NOT hold"
} else {
    Say "VERDICT: nothing extra was installed, but the 3D preview did not come up"
}
Say "done - results are in the mapped folder"

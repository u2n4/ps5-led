# Runs inside Windows Sandbox, as a machine that has never had anything
# installed: no Python, no PyOpenGL, no controller driver, no registry history.
#
# Stripping PATH on the build machine proves the EXE carries its own Python.
# It does NOT prove the EXE is free of everything else this machine has
# accumulated -- installed DLLs, drivers, registry keys. Only a fresh Windows
# does, which is what this is for.
#
# Writes its findings to the mapped folder so the host can read them after the
# sandbox is thrown away.

$ErrorActionPreference = 'Continue'
$share  = 'C:\host'
$out    = Join-Path $share 'sandbox-result'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$report = Join-Path $out 'report.txt'

function Say($text) {
    $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $text
    Write-Output $line
    Add-Content -Path $report -Value $line -Encoding UTF8
}

Set-Content -Path $report -Value "" -Encoding UTF8
Say "Windows Sandbox run"
Say ("OS: " + (Get-CimInstance Win32_OperatingSystem).Caption)

# Prove the sandbox really is bare, so a pass cannot be explained away.
$py = Get-Command python -ErrorAction SilentlyContinue
Say ("python present : " + $(if ($py) { $py.Source } else { "no (as expected)" }))
$pyi = Test-Path 'C:\Program Files\Python*'
Say ("Python install dir present : " + $pyi)

$exe = Join-Path $share 'PS5-LED.exe'
if (-not (Test-Path $exe)) { Say "FAIL: PS5-LED.exe not found in the mapped folder"; exit 1 }
Say ("EXE size : {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
Say ("EXE bytes : " + (Get-Item $exe).Length)
Say ("EXE SHA256 : " + (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash)

# Its config and log land in the sandbox's own AppData, which starts empty.
$appdata = Join-Path $env:APPDATA 'DualLED_Pro'
Say "launching ..."
$proc = Start-Process -FilePath $exe -PassThru

$log = Join-Path $appdata 'app.log'
$deadline = (Get-Date).AddSeconds(60)
$backend = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) { break }
    if (Test-Path $log) {
        $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
        $previews = [regex]::Matches($text, 'preview: (OpenGL|built-in drawing)')
        if ($previews.Count -gt 0) {
            $backend = $previews[$previews.Count - 1].Groups[1].Value
            # A widget can log OpenGL before its context initializes. Allow
            # startup failures to reach the log before accepting that backend.
            if ((Get-Date) -gt $deadline.AddSeconds(-45)) { break }
        }
    }
}

Say ("still running : " + (-not $proc.HasExited))
if ($proc.HasExited) { Say ("exit code : " + $proc.ExitCode) }
Say ("preview backend : " + $(if ($backend) { $backend } else { "never logged" }))

if (Test-Path $log) {
    Copy-Item $log (Join-Path $out 'app.log') -Force
    Say "--- app.log ---"
    Get-Content $log | ForEach-Object { Add-Content -Path $report -Value $_ -Encoding UTF8 }
}

# A picture of the window, so "it ran" is not taken on trust.
try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    Start-Sleep -Seconds 3
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $out 'sandbox-screen.png'))
    Say "screenshot saved"
} catch { Say ("screenshot failed: " + $_.Exception.Message) }

$wasRunning = -not $proc.HasExited
if ($wasRunning) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }

if (-not $wasRunning) {
    Say "VERDICT: the app exited during the test"
} elseif ($backend -eq 'OpenGL') {
    Say "VERDICT: runs on a clean Windows with the 3D preview"
} elseif ($backend -eq 'built-in drawing') {
    Say "VERDICT: runs, but WITHOUT the 3D - the bundled OpenGL did not load here"
} else {
    Say "VERDICT: did not start, or never reported a preview backend"
}
Say "done - close the sandbox; results are in the mapped folder"

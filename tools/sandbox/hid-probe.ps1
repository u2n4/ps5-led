# Can anything inside Windows Sandbox see the controller?
#
# The .wsb schema has no USB or HID element -- it covers vGPU, Networking,
# MappedFolders, LogonCommand, AudioInput, VideoInput, ProtectedClient,
# PrinterRedirection, ClipboardRedirection and MemoryInMB, and nothing else.
# Rather than assert that from documentation, this counts the HID devices the
# sandbox actually exposes and looks for Sony's vendor id, so the answer is a
# measurement.
#
# Run the same script on the host for the comparison.

$out = 'C:\host\hid-result'
if (-not (Test-Path 'C:\host')) { $out = Join-Path $env:TEMP 'hid-result' }
New-Item -ItemType Directory -Force -Path $out | Out-Null
$report = Join-Path $out 'hid-report.txt'
Set-Content -Path $report -Value "" -Encoding UTF8

function Say($t) {
    $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $t
    Write-Output $line
    Add-Content -Path $report -Value $line -Encoding UTF8
}

Say ("machine : " + $env:COMPUTERNAME)
Say ("OS      : " + (Get-CimInstance Win32_OperatingSystem).Caption)
$inSandbox = $env:COMPUTERNAME -like '*' -and (Test-Path 'C:\host')
Say ("context : " + $(if ($inSandbox) { "inside Windows Sandbox" } else { "host" }))

# Every HID-class device Windows knows about.
$hid = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
         Where-Object { $_.PNPClass -eq 'HIDClass' -or $_.DeviceID -like 'HID\*' })
Say ("HID devices visible : " + $hid.Count)
foreach ($d in $hid | Select-Object -First 25) {
    Say ("   " + $d.DeviceID)
}

# Sony's vendor id is 054C; the DualSense is PID 0CE6.
$sony = @($hid | Where-Object { $_.DeviceID -match 'VID[_&]0*054C' -or $_.DeviceID -match '054c' })
Say ("Sony (VID 054C) devices : " + $sony.Count)
foreach ($d in $sony) { Say ("   SONY: " + $d.DeviceID) }

# USB controllers at all?
$usb = @(Get-CimInstance Win32_USBControllerDevice -ErrorAction SilentlyContinue)
Say ("USB controller bindings : " + $usb.Count)

# Bluetooth radio?
$bt = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.PNPClass -eq 'Bluetooth' })
Say ("Bluetooth devices : " + $bt.Count)

Say ""
if ($sony.Count -gt 0) {
    Say "VERDICT: a Sony controller IS visible here"
} elseif ($hid.Count -eq 0) {
    Say "VERDICT: no HID devices at all - nothing is passed through"
} else {
    Say "VERDICT: HID exists but no Sony controller - the physical pad is not passed through"
}

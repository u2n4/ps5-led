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
$inSandbox = (Get-CimInstance Win32_ComputerSystem).UserName -like '*WDAGUtilityAccount*'
Say ("context : " + $(if ($inSandbox) { "inside Windows Sandbox" } else { "host" }))

# A CIM query that fails is reported as FAILED, never as zero devices.
# Every HID-class device Windows knows about.
$hidOk = $true
try {
    $hid = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
             Where-Object { $_.PNPClass -eq 'HIDClass' -or $_.DeviceID -like 'HID\*' })
} catch {
    $hidOk = $false
    Say ("FAIL: HID device query failed : " + $_.Exception.Message)
}
if ($hidOk) {
    Say ("HID devices visible : " + $hid.Count)
    foreach ($d in $hid | Select-Object -First 25) {
        Say ("   " + $d.DeviceID)
    }
} else {
    Say "HID devices visible : FAILED (see the FAIL line above)"
}

# Sony's vendor id is 054C; the DualSense is PID 0CE6.
# Bluetooth IDs carry the vendor id as VID&0002054C, so allow up to six hex digits before it.
# No loose "054c" match: instance ids contain random hex that can spell it.
if ($hidOk) {
    $sony = @($hid | Where-Object { $_.DeviceID -match 'VID[_&][0-9A-F]{0,6}054C' })
    Say ("Sony (VID 054C) devices : " + $sony.Count)
    foreach ($d in $sony) { Say ("   SONY: " + $d.DeviceID) }
} else {
    Say "Sony (VID 054C) devices : FAILED (see the FAIL line above)"
}

# USB devices bound to a USB controller. Each association's Dependent is a
# Win32_PnPEntity instance, so its DeviceID is read directly.
try {
    $usb = @(Get-CimInstance Win32_USBControllerDevice -ErrorAction Stop |
             ForEach-Object { $_.Dependent.DeviceID } | Where-Object { $_ })
    Say ("USB devices bound to a controller : " + $usb.Count)
    foreach ($id in $usb | Select-Object -First 25) { Say ("   " + $id) }
} catch {
    Say ("FAIL: USB device query failed : " + $_.Exception.Message)
}

# Bluetooth radio?
try {
    $bt = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
            Where-Object { $_.PNPClass -eq 'Bluetooth' })
    Say ("Bluetooth devices : " + $bt.Count)
} catch {
    Say ("FAIL: Bluetooth device query failed : " + $_.Exception.Message)
}

Say ""
if (-not $hidOk) {
    Say "VERDICT: not decided - the HID device query failed"
} elseif ($sony.Count -gt 0) {
    Say "VERDICT: a Sony controller IS visible here"
} elseif ($hid.Count -eq 0) {
    Say "VERDICT: no HID devices at all - nothing is passed through"
} else {
    Say "VERDICT: HID exists but no Sony controller - the physical pad is not passed through"
}

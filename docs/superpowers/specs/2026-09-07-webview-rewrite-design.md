# PS5 LED v3 — WebView rewrite design

**Date:** 2026-09-07
**Status:** approved for implementation
**Supersedes:** the single-file Tkinter app (`dualled_pro.py`, 2200 lines, v2.3.0)

---

## 1. Why

Four problems drove this rewrite. Each is a measured fact, not a guess.

**1. The LED backend is a fragile dependency chain.** `pydualsense` imports the
top-level `hidapi` module, which calls `cffi.dlopen("hidapi.dll")`. That call
resolves only because `pydualsense/pydualsense.py:7` injects its own package
directory into `os.environ["PATH"]`. On this machine `import hidapi` alone fails
with `OSError: Could not find any hidapi library`; it succeeds only as a side
effect of importing `pydualsense` first. Every link in that chain — a PyPI wheel,
a bundled native DLL, a cffi build, a PyInstaller `collect_all` — is a way for
the lightbar to go dead with no error the user can see.

**2. The installer reports success when pip fails.** `install.ps1:203` runs
`pip install` and then unconditionally prints `[OK] Dependencies installed`.
PowerShell does not raise on a native executable's non-zero exit code, and
`$LASTEXITCODE` is never checked. A failed dependency install is indistinguishable
from a successful one.

**3. `requirements.txt` names the wrong package.** It lists `hidapi>=0.12.0`
(cython-hidapi, which provides the `hid` module used for DualShock 4).
`pydualsense` actually requires `hidapi-usb`, which provides the top-level
`hidapi` module. The two are different distributions with confusingly similar
names.

**4. Tkinter cannot render what the app should look like.** A real 3D controller
model, gyro-driven orientation, a particle field that reacts to the cursor only
near the edges, and a genuinely translucent centre panel are all routine in a
browser and either impossible or ugly on a `tk.Canvas`.

The single fix for 1–3 is to remove the third-party HID stack entirely and talk
to Windows' own `hid.dll` through `ctypes`. The fix for 4 is to render the UI in
a browser window that the app owns.

---

## 2. Principle

**Python is the engine and owns no UI. The browser window is the UI and owns no
hardware.** They communicate over local HTTP.

No pip packages. No tkinter. No third-party DLLs. Python standard library and
`ctypes` only.

---

## 3. Verification already performed

These were proven with throwaway spikes before the design was accepted. The
spike scripts were discarded; the facts are kept.

| Claim | Result |
|---|---|
| ctypes over `setupapi` + `hid.dll` finds the controller | `DualSense Wireless Controller`, VID `054c`, PID `0ce6` |
| `HidP_GetCaps` reports a usable `InputReportByteLength` | `64` on the USB DualSense |
| Gyro calibration is readable via feature report `0x05` | scale `0.061 °/s` per LSB (≈ 1/16.4) |
| Input report offsets are right | `\|accel\|/8192 = 0.992 g` — gravity vector lands where it should |
| Battery is at struct offset 52 | byte `0x2a` → 100 %, charging |
| Edge `--app` with a private `--user-data-dir` yields a process we own | PID stays alive exactly as long as the window |
| WebGL2 is available in that window | `ANGLE … RTX 3070 … D3D11` |
| SSE sustains sensor rate | 30 events, mean gap **17.3 ms** (≈ 58 Hz) |
| `Origin` is checkable | page sends `Origin: http://127.0.0.1:<port>` |
| Model compresses | 6 658 KB → **≈ 1 150 KB** (meshopt + WebP) |

Not yet verified live: **Bluetooth**. The controller was on USB throughout. The
Bluetooth path is specified from the Linux `hid-playstation` driver and must be
tested on real hardware before release (§12).

**Inferred, not observed — the transport map.** `hid_win._TRANSPORT_BY_INPUT_LENGTH`
maps `InputReportByteLength` 64 → `usb` and 78 → `bt`. Only the 64 was measured,
on the USB DualSense above. The 78 is deduced from the DualSense's Bluetooth
input report size in `hid-playstation`, and it gates the whole untested
Bluetooth path: `device.choose_device` skips any interface whose transport is
neither `usb` nor `bt`, so a pad reporting some third length is not
mis-driven — it is not driven at all.

Two reasons to keep the "inferred" label until someone measures it:
`InputReportByteLength` is the **maximum** over every input report in the
collection, not the size of the one report we parse; and the DualShock 4's
Bluetooth descriptor declares large audio reports, which is why DS4Windows pins
the DS4 Bluetooth input report at **547**, not 78. The DS4 over Bluetooth is
therefore the likeliest of the four combinations to land on `unknown`.

That outcome is the design working, not a defect: `--doctor` lists every Sony
interface it found with its `transport=` value, then says the interface was
listed but could not be driven. The number needed to add a mapping is printed
on the line above the failure.

### 3.1 Live proof — `tools/live_check.py` (2026-09-07)

Task 6 wrote an operator tool that drives the real HID stack end to end
(`enumerate_devices` → `HidDevice.open` → `get_feature`/`write`/`read` →
`dualsense.build_output`/`parse_input`/`parse_calibration`) and ran it against
a real DualSense.

**USB — run, verified:**

```
Sony HID interfaces present:
  DualSense Wireless Controller  pid=0x0ce6  in=64 out=48 feat=64  transport=usb

using DualSense Wireless Controller over usb

calibration: scales (0.06101350206203039, 0.060982495765104464, 0.06092401421560332)
wrote red       (255, 0, 0)  (48 bytes: 020004...ff0000)
wrote green     (0, 255, 0)  (48 bytes: 020004...00ff00)
wrote blue      (0, 0, 255)  (48 bytes: 020004...0000ff)
wrote restored  (0, 170, 255)  (48 bytes: 020004...00aaff)

watching for 10 s -- move the controller
batt 100% state 2  gyro   ...  deg/s   (streamed continuously, gyro settling near 0 at rest)
```

All four `dev.write()` calls returned success with zero `HidError`s. Every RGB
byte landed where §7.1 says it should: **absolute indices 45, 46, 47** of the
48-byte USB report — §7.1's `44–46` are offsets *within* the common block, and
the block starts at index 1 over USB. The hex above confirms it, with each
colour occupying the final three bytes (`…ff0000`, `…00ff00`, `…0000ff`,
`…00aaff`). Calibration returned three scales of 0.0610, 0.0610 and 0.0609,
consistent with §3's `0.061 °/s` — §3 states two significant figures, so that is
the precision the agreement can be claimed at, not four. The same handle then received
continuous full 64-byte input reports (not the reduced report) with battery
100% and gyro values that tracked near zero while the controller sat still —
proof of live bidirectional USB HID communication, not just an accepted write.

Caveat honestly noted: the process running this check has no camera and cannot
itself see the physical lightbar. The evidence above (byte-correct writes
accepted with no I/O error, plus live sensor read-back over the same open
handle) is the strongest verification available without a human eyewitness;
the operator should confirm the visible red → green → blue → cyan cycle by eye
on the next run.

**Bluetooth — not run.** This requires unplugging the USB cable and re-pairing
the controller over Bluetooth by hand, a physical step no automated agent can
perform. `tools/live_check.py` handles both transports (`info.transport` from
`HidP_GetCaps`, `BT_OUTPUT_SIZE`/`BT_INPUT_SIZE` branches, CRC32 append/check),
but the Bluetooth path remains unverified live and must be run by a person
before it can be marked passed, per §12.

**DualShock 4 — not run**, no DS4 unit was on hand. `dualshock4.build_output`
was exercised standalone for both transports (`usb` → 32 bytes, `bt` → 78
bytes, correct report IDs and CRC) to confirm the call `tools/live_check.py`
makes is syntactically correct; it was never written to a real DS4.

---

## 4. File layout

```
ps5-led/
├─ ps5led/
│  ├─ __init__.py           VERSION
│  ├─ __main__.py           python -m ps5led → cli.main()
│  ├─ cli.py                --background --stop --doctor --port --no-browser
│  ├─ hid_win.py            ctypes: enumerate/open/read/write/get_feature
│  ├─ crc.py                CRC32 with seed byte (0xA1 in, 0xA2 out, 0xA3 feature)
│  ├─ dualsense.py          DS5 build_output() / parse_input() / parse_calibration()
│  ├─ dualshock4.py         DS4 USB 0x05 + BT 0x11
│  ├─ device.py             DeviceManager: scan, connect, reader thread, reconnect
│  ├─ engine.py             lighting modes → RGB at 30 Hz
│  ├─ state.py              AppState: lock + seq + snapshot()
│  ├─ bridge.py             http.server: static files, /api/*, SSE
│  ├─ launcher.py           Edge → Chrome → default browser; waits for close
│  ├─ tray.py               existing Win32 TrayIcon, moved unchanged
│  ├─ instance.py           existing mutex + event single-instance code
│  ├─ config.py             existing load/save/throttle + key migration
│  └─ i18n.py               ar/en strings, served to the page as JSON
├─ web/
│  ├─ index.html
│  ├─ css/app.css
│  ├─ js/{app,bridge,scene,orientation,particles,ui,i18n}.js
│  ├─ vendor/three/         three@0.180.0 from npm (MIT)
│  ├─ vendor/meshopt_decoder.js
│  ├─ assets/dualsense.glb  packed model — see §10
│  └─ ATTRIBUTION.md
├─ tests/
│  ├─ test_crc.py  test_dualsense.py  test_dualshock4.py  test_bridge.py
│  └─ fixtures/packets.json
├─ tools/
│  ├─ gen_fixtures.mjs      reference packet generator (manual, not CI)
│  └─ pack_model.mjs        gltfpack + ffmpeg WebP pipeline
├─ PS5-LED.spec  install.ps1
└─ ATTRIBUTION.md  README.md  CHANGELOG.md  LICENSE
```

Every Python module stays under ~250 lines with one responsibility. The 2200-line
single file is retired.

---

## 5. Threads

| Thread | Responsibility | Touches |
|---|---|---|
| **main** | build `AppState`, start the others, launch the browser, wait for it to close, drain the tray command queue | all |
| **reader** | overlapped `ReadFile` loop; decode each report into `state.sensor`; on device error, close and rescan every 2 s | `device`, `state` |
| **engine** | every 33 ms compute RGB for the active mode; write only when the value changed; publish to `state.rgb` | `device`, `state` |
| **http** | `ThreadingHTTPServer`, one thread per request; the SSE thread reads `state.snapshot()` every 16 ms and emits only when `seq` advanced | `state`, `engine` |
| **tray** | Win32 message loop; never touches anything, only puts `("open"\|"profile:X"\|"off"\|"quit")` on a `queue.Queue` | queue |

One rule: `AppState` is the only shared object. It holds a `threading.Lock` and a
monotonic `seq` counter that advances on every mutation. Readers call
`snapshot()` and get a plain copy. No cross-thread callbacks anywhere.

---

## 6. HID layer (`hid_win.py`)

Enumeration walks `SetupDiGetClassDevsW` / `SetupDiEnumDeviceInterfaces` /
`SetupDiGetDeviceInterfaceDetailW` over the HID class GUID, opens each interface
with `CreateFileW`, and keeps the ones whose `HidD_GetAttributes` reports vendor
`0x054C`.

Every `ctypes` prototype declares `argtypes` and `restype`. Handles are
`c_void_p`. This is not optional on 64-bit: an undeclared handle return defaults
to `c_int` and truncates above 4 GB.

Three decisions come from Microsoft's own guidance and from measurement:

**Write with `WriteFile`, never `HidD_SetOutputReport`.** Microsoft documents that
some devices become unresponsive when driven through `HidD_SetXxx`. `WriteFile`
uses the interrupt OUT endpoint when the device has one.

**The buffer length is always `HIDP_CAPS.OutputReportByteLength`.** Never a
literal. Linux defines the DualSense USB output report as 63 bytes; Windows
reports 48 for the same controller. Both are correct for their stack, and the
lightbar fields fit inside either. Reading the cap makes the difference
irrelevant.

**Open with `FILE_FLAG_OVERLAPPED`.** A blocking read cannot be cancelled at
shutdown and cannot time out, so a Bluetooth controller that went to sleep would
hang the reader thread forever. Overlapped reads use a per-thread `OVERLAPPED`
plus event, `WaitForSingleObject` with a timeout, then `GetOverlappedResult`.
The reader and the engine share the handle but never share an `OVERLAPPED`.

---

## 7. DualSense protocol

Authority: `drivers/hid/hid-playstation.c` in the Linux kernel. Offsets below are
byte positions inside the common structure, which begins at buffer index 1 for
USB and index 2 for Bluetooth (the report ID, and for Bluetooth a sequence byte,
precede it).

### 7.1 Output — `dualsense_output_report_common`, 47 bytes

| Offset | Field | Use |
|---|---|---|
| 0 | `valid_flag0` | left 0 — no rumble |
| 1 | `valid_flag1` | `0x04` lightbar, `\|0x10` player LEDs, `\|0x01` mic LED |
| 8 | `mute_button_led` | microphone LED |
| 38 | `valid_flag2` | `0x02` = lightbar-setup enable |
| 41 | `lightbar_setup` | `0x02` = leave the boot animation |
| 42 | `led_brightness` | |
| 43 | `player_leds` | 5-bit mask |
| 44–46 | `lightbar_red/green/blue` | |

Framing:

| | USB | Bluetooth |
|---|---|---|
| Report ID | `0x02` | `0x31` |
| Common starts at | index 1 | index 3 |
| Header | — | `[1] = seq << 4`, `[2] = 0x10` |
| Total length | `OutputReportByteLength` (48 or 63) | 78 |
| CRC32 | none | over `[0xA2] + buf[0 : len-4]`, little-endian in the last 4 bytes |

A setup packet (`valid_flag2 = 0x02`, `lightbar_setup = 0x02`) must be sent once
per connection before the first colour, or the controller stays in its power-on
animation and ignores RGB.

### 7.2 Input — `dualsense_input_report`, 63 bytes

| Offset | Field |
|---|---|
| 0–3 | left/right stick X, Y |
| 4, 5 | L2, R2 analogue |
| 6 | sequence |
| 7–10 | buttons, 4 bytes (D-pad nibble, face, shoulders, PS/touch/mute) |
| 15, 17, 19 | gyro X/Y/Z, `int16` LE × calibration scale |
| 21, 23, 25 | accel X/Y/Z, `int16` LE ÷ 8192 |
| 27–30 | timestamp, `uint32` LE; `dt = Δ / 3e6` seconds |
| 32–35, 36–39 | touch points, active bit + 12-bit X/Y |
| 52 | status: `& 0x0F` × 10 = battery %, `>> 4` = charge state |

USB delivers this as report `0x01`, 64 bytes total. Bluetooth delivers report
`0x31`, 78 bytes, whose last 4 bytes are a CRC32 with seed `0xA1`.

### 7.3 The Bluetooth report switch

Over Bluetooth the DualSense emits a reduced 10-byte `0x01` report — no motion,
no battery — until a feature report is read from it. Reading feature `0x05`
(calibration, 41 bytes, CRC seed `0xA3`) switches it to the full `0x31` report.
The calibration read is required anyway, so this costs nothing: connect → read
`0x05` → send setup packet → send colour.

### 7.4 DualShock 4

| | USB | Bluetooth |
|---|---|---|
| Report ID | `0x05` | `0x11` |
| Total length | 32 | 78 |
| `hw_control` | — | index 1 must be `0xC0` (`HID` \| `CRC32`); without it the controller discards the report |
| `valid_flag0` | `\|0x02` for LED | same |
| RGB | indices 6, 7, 8 | indices 8, 9, 10 |
| CRC32 | none | seed `0xA2`, same construction as the DualSense |

DS4 has the same minimal-Bluetooth-report behaviour and the same cure.

---

## 8. Bridge (`bridge.py`)

`ThreadingHTTPServer` bound to `127.0.0.1` on an ephemeral port.

Every request must satisfy all three checks or receive `403`:

- `?t=` equals a 128-bit token regenerated each launch
- `Host` equals `127.0.0.1:<port>`
- `Origin` is absent or equals `http://127.0.0.1:<port>`

| Route | Method | Purpose |
|---|---|---|
| `/`, `/css/*`, `/js/*`, `/vendor/*`, `/assets/*` | GET | static files, served from `sys._MEIPASS/web` inside the EXE, `Cache-Control: no-store` |
| `/api/boot` | GET | once on load: `{config, i18n, version, device}` |
| `/api/stream` | GET | SSE. Event `state` at 30 Hz (rgb, mode, battery, connected, transport); event `sensor` at 60 Hz (gyro, accel, timestamp, buttons, touch) |
| `/api/cmd` | POST | `set_color`, `set_mode`, `set_speed`, `set_flash`, `set_brightness`, `profile_save/load/delete`, `shell_color`, `lang`, `sleep`, `off`, `visible` |
| `/api/doctor` | GET | same payload as `--doctor`: devices, transport, report lengths, last write error |

When the page reports `visible: false`, the SSE thread stops `sensor` entirely
and drops `state` to 2 Hz. During a game the window is normally closed, so the
server has no client at all.

---

## 9. Web layer

**`scene.js`** — `GLTFLoader` with `MeshoptDecoder`; `RoomEnvironment` through
`PMREMGenerator` for reflections; one soft directional light; ACES Filmic tone
mapping. Lightbar meshes are resolved once at load and their `emissive` is driven
from `state.rgb`; glow is a translucent sprite behind the strip rather than a
bloom pass, which costs nothing. Shell colour changes recolour the body material.
`setPixelRatio(min(devicePixelRatio, 1.5))`. Rendering is `requestAnimationFrame`
only, which Chromium suspends when the window is hidden.

**`orientation.js`** — integrates `{gyro, accel, dt}` into a quaternion, corrects
pitch and roll against the gravity vector with a complementary filter (α = 0.98),
and leaves yaw to integration plus an explicit Recenter control. The rendered
orientation `slerp`s toward the target each frame. If no `sensor` event arrives
for 250 ms the model eases back to the front view.

Buttons, sticks and touch ride the same report and cost nothing extra: a pressed
button glows, a stick tilts, a finger shows as a dot on the touchpad. That is
what makes the model read as live rather than as a screensaver.

**`particles.js`** — a full-window 2D canvas behind everything, `pointer-events:
none`, about 140 particles. Each carries `edgeWeight = smoothstep(0.55, 0.85,
d)` where `d` is its normalised distance from the window centre. Particles inside
the central 60 % have weight 0 and only drift. Edge particles feel the cursor
through `F = edgeWeight × k / (r² + ε)`. The gradient is smooth, so no boundary
is visible. Near neighbours (≤ 110 px) are joined by lines whose opacity tracks
proximity. `prefers-reduced-motion` halves the drift and disables cursor
interaction.

**`app.css`** — the main panel is `rgba(11,15,20,.45)` with `backdrop-filter:
blur(22px) saturate(140%)`, so the particle field genuinely shows through it and
extends across the whole window. `dir` flips between `ar` and `en` without a
reload.

---

## 10. Model and attribution

The model is **PS5 Controller** by **Taohid Animation**, licensed **CC BY 4.0**.
It is taken from the original mirror, not from any modified redistribution.

`tools/pack_model.mjs` runs once and its output is committed:

| Step | Size |
|---|---|
| source | 6 658 KB |
| `gltfpack -cc` (meshopt geometry) | 3 524 KB |
| textures PNG → WebP via ffmpeg, quality 88 | 2 978 KB → 618 KB |
| **result** | **≈ 1 150 KB** |

`gltfpack`'s Node build cannot compress textures — it is built without BasisU —
so texture work goes through ffmpeg and the glTF `EXT_texture_webp` extension.
`GLTFLoader` supports both extensions; this was checked against the loader
source, not assumed.

The source model's 20 materials carry generic names (`VRayMtl55`, `Material.003`)
and its 48 meshes are not split by control, so the packing step also identifies
and names the lightbar meshes. That naming is our modification and is recorded as
such.

Attribution appears in three places, because CC BY requires credit wherever the
work is shown:

1. `ATTRIBUTION.md` at the repository root and in `web/` — creator, licence,
   link to the original, and the list of modifications; plus three.js under MIT.
2. An **About panel inside the application** carrying the same credit and a
   clickable link.
3. A Credits section in `README.md`, which also thanks DualSense Studio as
   inspiration.

Note on the reference project: `SafaElmali/dualsense-controller` is marked
`"private": true` and ships no licence file. Its README licenses only the model
(CC BY 4.0) and three.js (MIT); its own JavaScript is therefore all rights
reserved. None of it is copied. Protocol byte offsets are facts drawn from the
Linux kernel driver, not expression. three.js is vendored from npm.

---

## 11. Packaging, installer, CI

`datas = [('web', 'web')]`. Excludes drop `tkinter` and `_tkinter`. The current
spec's exclude list removes `http`, `html`, `email`, `socketserver` and `urllib`
— the bridge needs all of them (`http.server` pulls in `email.parser`), so those
entries come out.

`install.ps1` keeps Path A (portable EXE plus SHA256 verification, which works
today). Path B becomes a source-zip extraction that needs Python 3.8+ and nothing
else — no pip at all. `$LASTEXITCODE` is checked after every external command; a
failure prints what failed and stops instead of reporting success.

`--doctor` prints devices, transport, report lengths, and the last write error,
so a silent failure can never happen again.

CI adds `python -m unittest` to the existing compileall and ruff steps. A
`release.yml` builds the EXE on `windows-latest` from a tag, so releases stop
depending on one developer's machine.

---

## 12. Testing

**Unit.** CRC32 against a known vector for each of the three seeds. Packet
builders compared byte for byte against `tests/fixtures/packets.json`, generated
once from an independent reference implementation. Bridge tests assert that a
wrong token, a wrong `Host`, and a foreign `Origin` each yield `403`, and that a
valid request opens the stream. Bridge tests must never point at a live runtime
handler — they assert the guard, not a side effect — and must assert the exact
status code rather than a set.

**Live, on real hardware, required before release.**

1. USB: colour change, every lighting mode, battery reading.
2. Bluetooth: the same, plus the `0x01` → `0x31` switch and CRC acceptance.
3. Motion: the model tracks the controller; Recenter works; the model eases home
   when reports stop.
4. Disconnect and reconnect on both transports.
5. Idle cost with the window closed while a game runs.

No completion claim without these.

---

## 13. Budget

| | v2.3.0 | v3 |
|---|---|---|
| EXE on disk | 12.8 MB | ≈ 5 MB |
| Python dependencies | 4 | **0** |
| RAM, window open | ~35 MB | ~150–200 MB |
| RAM, window closed (in game) | ~35 MB | **~12 MB** |
| Idle CPU | ~0 | ~0 |

The open window costs more memory than Tkinter did, because it is Chromium. The
trade is deliberate: during a game — the state that actually matters — the window
is closed and only the engine remains, which is lighter than today.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Edge absent (LTSC, debloated Windows) | fall back to Chrome, then the default browser. The LEDs work regardless, because the engine is independent of the UI |
| The app window shows Edge's icon | verified at implementation time; Chromium normally adopts the page favicon for `--app` windows |
| Bluetooth untested | mandatory live test before release (§12) |
| A wrong CRC makes the controller ignore writes silently | byte-exact fixtures plus known CRC vectors |
| Another program holds the controller (DS4Windows, Steam) | `--doctor` reports "opened but write failed: error N" instead of failing silently |
| SSE drops | `bridge.js` reconnects with backoff; the model eases to the front view meanwhile |
| A Python module grows past its remit | the 250-line ceiling is a review criterion, not a suggestion |

---

## 15. Scope

**In.** Everything above, plus player LEDs and the microphone LED (same report,
no extra cost), buttons/sticks/touch mirrored on the model, run-at-startup as an
opt-in registry entry, and a written promise of zero network calls from the
application itself.

**Out.** Rumble, adaptive triggers, auto-update, Linux and macOS.

---

## 16. Order of work

Each stage ends with a live check on real hardware. Nothing proceeds on a stage
that has not passed.

1. `hid_win` + `crc` + `dualsense` + unit tests → the controller changes colour
   from a command line, USB then Bluetooth.
2. `device` + `engine` + `state` + `cli --background --doctor` → the engine runs
   headless and the tray works.
3. `bridge` + `launcher` + a minimal page showing colour and battery → the loop
   closes.
4. `scene.js` + the packed model + lightbar emissive → the model lights up in the
   real colour.
5. Gyro and buttons on the model → moving the controller moves the model.
6. `particles.js`, the glass panel, and the rest of the UI.
7. Installer, spec file, `release.yml`, attribution, README.
8. Independent review of the protocol and the bridge guards.

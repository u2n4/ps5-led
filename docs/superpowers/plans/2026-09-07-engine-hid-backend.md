# PS5 LED v3 — Plan 1: dependency-free HID engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `pydualsense` / `hidapi` / `cffi` stack with a stdlib-and-`ctypes` HID engine that drives the DualSense and DualShock 4 lightbars over USB and Bluetooth, runs headless, and reports why it failed when it fails.

**Architecture:** Protocol modules are pure functions over `bytes` with no Windows imports, so they unit-test on the Ubuntu CI runner. A single Windows-only module (`hid_win.py`) wraps `setupapi` and `hid.dll` through `ctypes` and is imported lazily. A `DeviceManager` owns the handle and an overlapped reader thread; an `Engine` thread computes colour and writes only on change. `AppState` is the one shared object, guarded by a lock and versioned by a `seq` counter.

**Tech Stack:** Python 3.8+, standard library only (`ctypes`, `zlib`, `threading`, `queue`, `unittest`). No pip packages, no tkinter.

**Spec:** `docs/superpowers/specs/2026-09-07-webview-rewrite-design.md`

**Branch:** `feat/webview-rewrite` (already created, spec committed at `3822c9f`)

## Global Constraints

- **Python floor is 3.8.** CI runs 3.8, 3.10 and 3.12. No `match`, no `X | Y` annotations, no `list[int]` subscripting at runtime — use `typing.List`, `typing.Optional`, `typing.Tuple`.
- **Zero third-party dependencies.** If a task seems to need a package, it is the wrong task.
- **CI runs on `ubuntu-latest`.** Every module under `ps5led/` except `hid_win.py` must import cleanly on Linux. `hid_win.py` must only be imported from inside a function body, never at module scope of a module that CI imports.
- **Never use `HidD_SetOutputReport`.** Writes go through `WriteFile` only. Microsoft documents that some devices hang on `HidD_SetXxx`.
- **Every `ctypes` prototype declares `argtypes` and `restype`.** Handles are `ctypes.c_void_p`. An undeclared handle return defaults to `c_int` and truncates above 4 GB.
- **Output buffer length is always `HIDP_CAPS.OutputReportByteLength`.** Never a literal — Linux says 63 for the DualSense USB report, Windows says 48 for the same controller.
- Vendor ID `0x054C`. DualSense `0x0CE6`, DualSense Edge `0x0DF2`. DualShock 4 `0x05C4`, `0x09CC`, `0x0BA0`.
- CRC seeds: input `0xA1`, output `0xA2`, feature `0xA3`.
- Repository line endings are LF (`.gitattributes`). Tests that match source text must normalise `\r\n`.

---

## File structure

| File | Responsibility |
|---|---|
| `ps5led/__init__.py` | version constant only |
| `ps5led/crc.py` | PlayStation CRC32 over `zlib.crc32` |
| `ps5led/dualsense.py` | DS5 output builder, input parser, calibration parser |
| `ps5led/dualshock4.py` | DS4 output builder for USB and Bluetooth |
| `ps5led/hid_win.py` | Windows-only `ctypes` HID: enumerate, open, read, write, feature |
| `ps5led/state.py` | `AppState` — lock, `seq`, `snapshot()` |
| `ps5led/device.py` | `DeviceManager` — connect, reader thread, reconnect, write |
| `ps5led/engine.py` | lighting modes → RGB at 30 Hz |
| `ps5led/config.py` | config load/save/throttle, ported from `dualled_pro.py` |
| `ps5led/cli.py` | `--doctor`, `--background`, `--stop` |
| `tests/test_crc.py` | CRC vectors and framing |
| `tests/test_dualsense.py` | DS5 packet bytes, input decode, calibration |
| `tests/test_dualshock4.py` | DS4 packet bytes both transports |
| `tests/test_engine.py` | mode maths without hardware |

---

### Task 1: CRC and package skeleton

**Files:**
- Create: `ps5led/__init__.py`, `ps5led/crc.py`, `tests/__init__.py`, `tests/test_crc.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ps5led.crc.ps_crc32(seed: int, data: bytes) -> int`,
  `ps5led.crc.append_crc32(seed: int, report: bytearray) -> None`,
  `ps5led.crc.check_crc32(seed: int, report: bytes) -> bool`,
  and constants `INPUT_SEED = 0xA1`, `OUTPUT_SEED = 0xA2`, `FEATURE_SEED = 0xA3`.

Background for the implementer: Sony's controllers use ordinary CRC-32 (IEEE, reflected, polynomial `0xEDB88320`, initial value `0xFFFFFFFF`, final XOR `0xFFFFFFFF`) computed over a one-byte seed followed by the report. That is exactly what `zlib.crc32` computes, which was verified against a bit-by-bit reference loop over 1000 random vectors. Do not hand-roll a table.

`zlib.crc32(data, running)` chains correctly because the running value it accepts and returns is already post-final-XOR, which is why `zlib.crc32(data, zlib.crc32(bytes([seed])))` reproduces the kernel's `~crc32_le(crc32_le(0xFFFFFFFF, &seed, 1), data, len)`.

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` empty, and `tests/test_crc.py`:

```python
import unittest
import zlib

from ps5led.crc import (
    FEATURE_SEED,
    INPUT_SEED,
    OUTPUT_SEED,
    append_crc32,
    check_crc32,
    ps_crc32,
)


def reference_crc(data):
    """Bit-by-bit CRC-32 — the independent oracle, deliberately not zlib."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


class TestSeeds(unittest.TestCase):
    def test_seed_values(self):
        self.assertEqual((INPUT_SEED, OUTPUT_SEED, FEATURE_SEED), (0xA1, 0xA2, 0xA3))


class TestPsCrc32(unittest.TestCase):
    def test_matches_bitwise_reference(self):
        for payload in (b"", b"\x00", bytes(range(74)), b"\xff" * 77):
            for seed in (INPUT_SEED, OUTPUT_SEED, FEATURE_SEED):
                self.assertEqual(
                    ps_crc32(seed, payload),
                    reference_crc(bytes([seed]) + payload),
                    "seed=%#x len=%d" % (seed, len(payload)),
                )

    def test_known_vector(self):
        # DualSense Bluetooth output report, report id 0x31, payload all zero.
        self.assertEqual(ps_crc32(OUTPUT_SEED, bytes([0x31]) + bytes(73)), 0xC30E1F7B)

    def test_seed_changes_result(self):
        self.assertNotEqual(ps_crc32(INPUT_SEED, b"abc"), ps_crc32(OUTPUT_SEED, b"abc"))


class TestFraming(unittest.TestCase):
    def test_append_writes_little_endian_tail(self):
        report = bytearray(78)
        report[0] = 0x31
        append_crc32(OUTPUT_SEED, report)
        expected = ps_crc32(OUTPUT_SEED, bytes(report[:74]))
        self.assertEqual(int.from_bytes(report[74:78], "little"), expected)

    def test_append_leaves_body_untouched(self):
        report = bytearray(78)
        report[0] = 0x31
        report[47] = 0xAB
        append_crc32(OUTPUT_SEED, report)
        self.assertEqual(report[47], 0xAB)

    def test_append_is_idempotent(self):
        first = bytearray(78)
        first[0] = 0x31
        append_crc32(OUTPUT_SEED, first)
        second = bytearray(first)
        append_crc32(OUTPUT_SEED, second)
        self.assertEqual(bytes(first), bytes(second))

    def test_check_accepts_what_append_produced(self):
        report = bytearray(78)
        report[0] = 0x31
        report[46] = 0x7F
        append_crc32(OUTPUT_SEED, report)
        self.assertTrue(check_crc32(OUTPUT_SEED, bytes(report)))

    def test_check_rejects_a_flipped_bit(self):
        report = bytearray(78)
        report[0] = 0x31
        append_crc32(OUTPUT_SEED, report)
        report[20] ^= 0x01
        self.assertFalse(check_crc32(OUTPUT_SEED, bytes(report)))

    def test_check_rejects_short_report(self):
        self.assertFalse(check_crc32(INPUT_SEED, b"\x31\x00\x00"))

    def test_append_rejects_short_report(self):
        with self.assertRaises(ValueError):
            append_crc32(OUTPUT_SEED, bytearray(4))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails for the right reason**

```bash
python -m unittest tests.test_crc -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led'`. If it fails any other way, stop and read the error before continuing.

- [ ] **Step 3: Create the package and implement `crc.py`**

`ps5led/__init__.py`:

```python
"""PS5 LED — DualSense and DualShock 4 lightbar control."""

__version__ = "3.0.0-dev"
```

`ps5led/crc.py`:

```python
"""PlayStation report CRC32.

Sony's controllers protect Bluetooth reports with ordinary CRC-32 (IEEE,
reflected, polynomial 0xEDB88320) computed over a one-byte seed followed by the
report body. That is precisely zlib.crc32, verified against a bit-by-bit
reference over 1000 random vectors, so there is no table to maintain here.

Seeds come from drivers/hid/hid-playstation.c in the Linux kernel.
"""

import zlib

INPUT_SEED = 0xA1
OUTPUT_SEED = 0xA2
FEATURE_SEED = 0xA3

CRC_SIZE = 4


def ps_crc32(seed, data):
    """CRC-32 over ``bytes([seed]) + data``."""
    return zlib.crc32(data, zlib.crc32(bytes([seed]))) & 0xFFFFFFFF


def append_crc32(seed, report):
    """Write the CRC of ``report[:-4]`` into the last four bytes, little-endian.

    ``report`` is modified in place, so the body must already be final.
    """
    if len(report) <= CRC_SIZE:
        raise ValueError("report too short to carry a CRC: %d bytes" % len(report))
    crc = ps_crc32(seed, bytes(report[:-CRC_SIZE]))
    report[-CRC_SIZE:] = crc.to_bytes(CRC_SIZE, "little")


def check_crc32(seed, report):
    """True when the trailing CRC matches the body."""
    if len(report) <= CRC_SIZE:
        return False
    carried = int.from_bytes(report[-CRC_SIZE:], "little")
    return carried == ps_crc32(seed, bytes(report[:-CRC_SIZE]))
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
python -m unittest tests.test_crc -v
```

Expected: 10 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/__init__.py ps5led/crc.py tests/__init__.py tests/test_crc.py
git commit -m "feat(crc): PlayStation report CRC32 over zlib"
```

---

### Task 2: DualSense output report builder

**Files:**
- Create: `ps5led/dualsense.py`, `tests/test_dualsense.py`

**Interfaces:**
- Consumes: `ps5led.crc.OUTPUT_SEED`, `ps5led.crc.append_crc32`
- Produces:
  - constants `VENDOR_ID = 0x054C`, `PRODUCT_IDS = (0x0CE6, 0x0DF2)`,
    `OUTPUT_REPORT_USB = 0x02`, `OUTPUT_REPORT_BT = 0x31`,
    `INPUT_REPORT_USB = 0x01`, `INPUT_REPORT_BT = 0x31`,
    `FEATURE_CALIBRATION = 0x05`, `CALIBRATION_SIZE = 41`,
    `COMMON_SIZE = 47`, `BT_OUTPUT_SIZE = 78`,
    `USB_INPUT_SIZE = 64`, `BT_INPUT_SIZE = 78`
  - `TRANSPORT_USB = "usb"`, `TRANSPORT_BT = "bt"`
  - `build_output(transport, length, rgb=None, player_leds=None, mic_led=None, lightbar_setup=False, seq=0) -> bytes`

The report layout is `drivers/hid/hid-playstation.c`,
`struct dualsense_output_report_common` (47 bytes). Offsets **within the common
block**:

| Offset | Field | Notes |
|---|---|---|
| 0 | `valid_flag0` | stays 0 — this app never drives rumble |
| 1 | `valid_flag1` | `0x01` mic LED, `0x04` lightbar, `0x10` player LEDs |
| 8 | `mute_button_led` | |
| 38 | `valid_flag2` | `0x02` enables the lightbar-setup field |
| 41 | `lightbar_setup` | `0x02` = leave the power-on animation |
| 42 | `led_brightness` | |
| 43 | `player_leds` | 5-bit mask |
| 44, 45, 46 | red, green, blue | |

The common block starts at buffer index **1** for USB (after the report ID) and
index **3** for Bluetooth (after the report ID, a sequence byte and a tag byte).
Bluetooth reports are always 78 bytes and end in a CRC32.

A controller that has just connected is still running its power-on light
animation and ignores RGB. One `lightbar_setup=True` packet per connection ends
it. That is why the flag exists as a separate call rather than being folded into
the colour packet.

- [ ] **Step 1: Write the failing test**

`tests/test_dualsense.py`:

```python
import unittest

from ps5led import dualsense as ds
from ps5led.crc import OUTPUT_SEED, check_crc32


class TestConstants(unittest.TestCase):
    def test_identifiers(self):
        self.assertEqual(ds.VENDOR_ID, 0x054C)
        self.assertEqual(ds.PRODUCT_IDS, (0x0CE6, 0x0DF2))

    def test_report_ids(self):
        self.assertEqual(ds.OUTPUT_REPORT_USB, 0x02)
        self.assertEqual(ds.OUTPUT_REPORT_BT, 0x31)
        self.assertEqual(ds.INPUT_REPORT_USB, 0x01)
        self.assertEqual(ds.INPUT_REPORT_BT, 0x31)

    def test_sizes(self):
        self.assertEqual(ds.COMMON_SIZE, 47)
        self.assertEqual(ds.BT_OUTPUT_SIZE, 78)
        self.assertEqual(ds.CALIBRATION_SIZE, 41)


class TestUsbOutput(unittest.TestCase):
    def test_length_is_what_the_caller_asked_for(self):
        for length in (48, 63):
            self.assertEqual(len(ds.build_output(ds.TRANSPORT_USB, length, rgb=(1, 2, 3))), length)

    def test_report_id_leads(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, rgb=(1, 2, 3))
        self.assertEqual(packet[0], 0x02)

    def test_colour_lands_at_common_44_to_46(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, rgb=(0x11, 0x22, 0x33))
        self.assertEqual(packet[1 + 44], 0x11)
        self.assertEqual(packet[1 + 45], 0x22)
        self.assertEqual(packet[1 + 46], 0x33)

    def test_colour_sets_only_the_lightbar_flag(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, rgb=(1, 2, 3))
        self.assertEqual(packet[1 + 0], 0x00, "valid_flag0 must stay clear — no rumble")
        self.assertEqual(packet[1 + 1], 0x04)

    def test_colour_packet_is_otherwise_zero(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, rgb=(1, 2, 3))
        expected = bytearray(48)
        expected[0] = 0x02
        expected[1 + 1] = 0x04
        expected[1 + 44], expected[1 + 45], expected[1 + 46] = 1, 2, 3
        self.assertEqual(packet, bytes(expected))

    def test_setup_packet_bytes(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, lightbar_setup=True)
        expected = bytearray(48)
        expected[0] = 0x02
        expected[1 + 38] = 0x02
        expected[1 + 41] = 0x02
        self.assertEqual(packet, bytes(expected))

    def test_player_leds_set_their_own_flag(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, player_leds=0x15)
        self.assertEqual(packet[1 + 1], 0x10)
        self.assertEqual(packet[1 + 43], 0x15)

    def test_mic_led_is_at_common_8_not_42(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, mic_led=1)
        self.assertEqual(packet[1 + 1], 0x01)
        self.assertEqual(packet[1 + 8], 1)
        self.assertEqual(packet[1 + 42], 0, "offset 42 is led_brightness, not the mic LED")

    def test_flags_combine(self):
        packet = ds.build_output(ds.TRANSPORT_USB, 48, rgb=(9, 9, 9), player_leds=1, mic_led=1)
        self.assertEqual(packet[1 + 1], 0x01 | 0x04 | 0x10)

    def test_rgb_is_range_checked(self):
        for bad in ((256, 0, 0), (-1, 0, 0), (0, 0, 300)):
            with self.assertRaises(ValueError):
                ds.build_output(ds.TRANSPORT_USB, 48, rgb=bad)

    def test_length_is_range_checked(self):
        with self.assertRaises(ValueError):
            ds.build_output(ds.TRANSPORT_USB, 40, rgb=(1, 2, 3))


class TestBluetoothOutput(unittest.TestCase):
    def test_length_is_always_78(self):
        self.assertEqual(len(ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3))), 78)

    def test_header(self):
        packet = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3), seq=5)
        self.assertEqual(packet[0], 0x31)
        self.assertEqual(packet[1], 5 << 4)
        self.assertEqual(packet[2], 0x10)

    def test_sequence_wraps_at_four_bits(self):
        self.assertEqual(ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3), seq=17)[1], 1 << 4)

    def test_common_block_starts_at_index_3(self):
        packet = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(0x44, 0x55, 0x66))
        self.assertEqual(packet[3 + 1], 0x04)
        self.assertEqual(packet[3 + 44], 0x44)
        self.assertEqual(packet[3 + 45], 0x55)
        self.assertEqual(packet[3 + 46], 0x66)

    def test_crc_is_present_and_valid(self):
        packet = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3))
        self.assertTrue(check_crc32(OUTPUT_SEED, packet))

    def test_crc_covers_the_colour(self):
        a = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3))
        b = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 4))
        self.assertNotEqual(a[-4:], b[-4:])

    def test_crc_covers_the_sequence(self):
        a = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3), seq=1)
        b = ds.build_output(ds.TRANSPORT_BT, 78, rgb=(1, 2, 3), seq=2)
        self.assertNotEqual(a[-4:], b[-4:])

    def test_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            ds.build_output(ds.TRANSPORT_BT, 64, rgb=(1, 2, 3))


class TestTransportValidation(unittest.TestCase):
    def test_unknown_transport_raises(self):
        with self.assertRaises(ValueError):
            ds.build_output("serial", 48, rgb=(1, 2, 3))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
python -m unittest tests.test_dualsense -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.dualsense'`.

- [ ] **Step 3: Implement the builder**

`ps5led/dualsense.py`:

```python
"""DualSense (DS5) HID protocol.

Report layouts are taken from drivers/hid/hid-playstation.c in the Linux
kernel. Offsets named "common" below are relative to the start of
``struct dualsense_output_report_common``, which sits at buffer index 1 over
USB and index 3 over Bluetooth.

This module is pure: bytes in, bytes out, no I/O and no Windows imports, so it
runs under CI on Linux.
"""

from .crc import CRC_SIZE, OUTPUT_SEED, append_crc32

VENDOR_ID = 0x054C
PRODUCT_IDS = (0x0CE6, 0x0DF2)  # DualSense, DualSense Edge

INPUT_REPORT_USB = 0x01
INPUT_REPORT_BT = 0x31
OUTPUT_REPORT_USB = 0x02
OUTPUT_REPORT_BT = 0x31
FEATURE_CALIBRATION = 0x05

USB_INPUT_SIZE = 64
BT_INPUT_SIZE = 78
BT_OUTPUT_SIZE = 78
CALIBRATION_SIZE = 41
COMMON_SIZE = 47

TRANSPORT_USB = "usb"
TRANSPORT_BT = "bt"

# Offsets inside the common block.
_VALID_FLAG0 = 0
_VALID_FLAG1 = 1
_MUTE_LED = 8
_VALID_FLAG2 = 38
_LIGHTBAR_SETUP = 41
_LED_BRIGHTNESS = 42
_PLAYER_LEDS = 43
_RED = 44
_GREEN = 45
_BLUE = 46

FLAG1_MIC_MUTE_LED = 0x01
FLAG1_LIGHTBAR = 0x04
FLAG1_PLAYER_INDICATOR = 0x10
FLAG2_LIGHTBAR_SETUP = 0x02
LIGHTBAR_SETUP_LIGHT_OUT = 0x02

# Where the common block begins, per transport.
_COMMON_OFFSET = {TRANSPORT_USB: 1, TRANSPORT_BT: 3}


def _check_rgb(rgb):
    if len(rgb) != 3:
        raise ValueError("rgb needs exactly three channels, got %d" % len(rgb))
    for channel in rgb:
        if not isinstance(channel, int) or not 0 <= channel <= 255:
            raise ValueError("rgb channel out of range: %r" % (channel,))


def build_output(transport, length, rgb=None, player_leds=None, mic_led=None,
                 lightbar_setup=False, seq=0):
    """Build one DualSense output report.

    ``length`` must be the value Windows reported as OutputReportByteLength for
    USB; Bluetooth is always ``BT_OUTPUT_SIZE``. Pass ``lightbar_setup=True``
    once per connection before the first colour, otherwise the controller stays
    in its power-on animation and ignores RGB.
    """
    if transport not in _COMMON_OFFSET:
        raise ValueError("unknown transport: %r" % (transport,))
    offset = _COMMON_OFFSET[transport]

    if transport == TRANSPORT_BT:
        if length != BT_OUTPUT_SIZE:
            raise ValueError("Bluetooth reports are %d bytes, got %d" % (BT_OUTPUT_SIZE, length))
    elif length < offset + COMMON_SIZE:
        raise ValueError("USB report needs at least %d bytes, got %d" % (offset + COMMON_SIZE, length))

    report = bytearray(length)

    if transport == TRANSPORT_USB:
        report[0] = OUTPUT_REPORT_USB
    else:
        report[0] = OUTPUT_REPORT_BT
        report[1] = (seq & 0x0F) << 4
        report[2] = 0x10

    flag1 = 0
    if rgb is not None:
        _check_rgb(rgb)
        flag1 |= FLAG1_LIGHTBAR
        report[offset + _RED], report[offset + _GREEN], report[offset + _BLUE] = rgb
    if player_leds is not None:
        flag1 |= FLAG1_PLAYER_INDICATOR
        report[offset + _PLAYER_LEDS] = player_leds & 0x1F
    if mic_led is not None:
        flag1 |= FLAG1_MIC_MUTE_LED
        report[offset + _MUTE_LED] = 1 if mic_led else 0
    if flag1:
        report[offset + _VALID_FLAG1] = flag1

    if lightbar_setup:
        report[offset + _VALID_FLAG2] = FLAG2_LIGHTBAR_SETUP
        report[offset + _LIGHTBAR_SETUP] = LIGHTBAR_SETUP_LIGHT_OUT

    if transport == TRANSPORT_BT:
        append_crc32(OUTPUT_SEED, report)

    return bytes(report)
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
python -m unittest tests.test_dualsense -v
```

Expected: 20 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/dualsense.py tests/test_dualsense.py
git commit -m "feat(ds5): output report builder for USB and Bluetooth"
```

---

### Task 3: DualSense input and calibration parsing

**Files:**
- Modify: `ps5led/dualsense.py` (append)
- Modify: `tests/test_dualsense.py` (append)

**Interfaces:**
- Consumes: constants from Task 2
- Produces:
  - `InputState` — a `typing.NamedTuple` with fields `sticks: Tuple[int, int, int, int]`, `triggers: Tuple[int, int]`, `buttons: int`, `gyro_raw: Tuple[int, int, int]`, `accel_raw: Tuple[int, int, int]`, `timestamp: int`, `touch: Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]`, `battery_percent: int`, `charge_state: int`
  - `parse_input(data: bytes) -> Optional[InputState]`
  - `parse_calibration(data: bytes) -> Optional[Tuple[float, float, float]]`
  - `DEFAULT_GYRO_SCALE = 1.0 / 16.0`

`struct dualsense_input_report` is 63 bytes and begins at buffer index **1** for
a 64-byte USB report `0x01`, and index **2** for a 78-byte Bluetooth report
`0x31`. Offsets within it:

| Offset | Field |
|---|---|
| 0–3 | left X, left Y, right X, right Y |
| 4, 5 | L2, R2 analogue |
| 6 | sequence |
| 7–10 | buttons, four bytes |
| 15, 17, 19 | gyro X/Y/Z, `int16` little-endian |
| 21, 23, 25 | accel X/Y/Z, `int16` little-endian |
| 27 | timestamp, `uint32` little-endian |
| 32–35, 36–39 | touch points; bit 7 of the first byte **clear** means the finger is down |
| 52 | status: low nibble × 10 = battery percent, high nibble = charge state |

A live capture on real hardware produced `|accel| / 8192 = 0.992 g` with the
controller at rest, which is how these offsets were confirmed rather than
assumed. Bluetooth input reports carry a CRC32 with seed `0xA1`; verify it and
reject a report that fails, because a corrupt report would otherwise be
integrated into the orientation estimate.

Calibration is feature report `0x05`, 41 bytes including the leading report ID.
Reading it does double duty: it yields the per-axis gyro scale, and it switches a
Bluetooth DualSense out of its reduced 10-byte `0x01` report into the full `0x31`
report. Speed is `speed_max + speed_min` read at offsets 18 and 20 of the body;
each axis divides that by the sum of the absolute distances of its plus and minus
calibration points from its bias. A plausible scale sits between 0.001 and 1;
anything else means the read was garbage, so return `None` and let the caller
fall back to `DEFAULT_GYRO_SCALE`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dualsense.py`, above the `if __name__` block:

```python
import struct

from ps5led.crc import INPUT_SEED, append_crc32


def make_usb_input(gyro=(0, 0, 0), accel=(0, 0, 0), timestamp=0, status=0,
                   sticks=(128, 128, 128, 128), triggers=(0, 0), buttons=b"\x00\x00\x00\x00",
                   touch0=None, touch1=None):
    """Build a synthetic 64-byte USB input report."""
    report = bytearray(ds.USB_INPUT_SIZE)
    report[0] = ds.INPUT_REPORT_USB
    body = 1
    report[body + 0:body + 4] = bytes(sticks)
    report[body + 4], report[body + 5] = triggers
    report[body + 7:body + 11] = buttons
    for i, value in enumerate(gyro):
        struct.pack_into("<h", report, body + 15 + i * 2, value)
    for i, value in enumerate(accel):
        struct.pack_into("<h", report, body + 21 + i * 2, value)
    struct.pack_into("<I", report, body + 27, timestamp)
    for slot, point in enumerate((touch0, touch1)):
        base = body + 32 + slot * 4
        if point is None:
            report[base] = 0x80  # bit 7 set means "not touching"
        else:
            x, y = point
            report[base] = 0x00
            report[base + 1] = x & 0xFF
            report[base + 2] = ((x >> 8) & 0x0F) | ((y & 0x0F) << 4)
            report[base + 3] = (y >> 4) & 0xFF
    report[body + 52] = status
    return bytes(report)


def make_bt_input(**kwargs):
    """Wrap the same body in a 78-byte Bluetooth report with a valid CRC."""
    usb = make_usb_input(**kwargs)
    report = bytearray(ds.BT_INPUT_SIZE)
    report[0] = ds.INPUT_REPORT_BT
    report[1] = 0x01
    report[2:2 + 63] = usb[1:1 + 63]
    append_crc32(INPUT_SEED, report)
    return bytes(report)


class TestParseInput(unittest.TestCase):
    def test_rejects_empty(self):
        self.assertIsNone(ds.parse_input(b""))

    def test_rejects_short_usb_report(self):
        self.assertIsNone(ds.parse_input(bytes([ds.INPUT_REPORT_USB]) + bytes(20)))

    def test_rejects_minimal_bluetooth_report(self):
        # The 10-byte report a DualSense emits before calibration is read.
        self.assertIsNone(ds.parse_input(bytes([0x01]) + bytes(9)))

    def test_rejects_unknown_report_id(self):
        self.assertIsNone(ds.parse_input(bytes([0x77]) + bytes(63)))

    def test_sticks_and_triggers(self):
        state = ds.parse_input(make_usb_input(sticks=(1, 2, 3, 4), triggers=(200, 201)))
        self.assertEqual(state.sticks, (1, 2, 3, 4))
        self.assertEqual(state.triggers, (200, 201))

    def test_buttons_pack_little_endian(self):
        state = ds.parse_input(make_usb_input(buttons=b"\x01\x02\x03\x04"))
        self.assertEqual(state.buttons, 0x04030201)

    def test_gyro_is_signed(self):
        state = ds.parse_input(make_usb_input(gyro=(-1, 300, -32768)))
        self.assertEqual(state.gyro_raw, (-1, 300, -32768))

    def test_accel_is_signed(self):
        state = ds.parse_input(make_usb_input(accel=(-434, 8016, -1243)))
        self.assertEqual(state.accel_raw, (-434, 8016, -1243))

    def test_timestamp_is_unsigned_32_bit(self):
        state = ds.parse_input(make_usb_input(timestamp=0xFFFFFFFF))
        self.assertEqual(state.timestamp, 0xFFFFFFFF)

    def test_battery_low_nibble_times_ten(self):
        state = ds.parse_input(make_usb_input(status=0x2A))
        self.assertEqual(state.battery_percent, 100)
        self.assertEqual(state.charge_state, 0x2)

    def test_battery_partial(self):
        self.assertEqual(ds.parse_input(make_usb_input(status=0x05)).battery_percent, 50)

    def test_touch_absent_by_default(self):
        state = ds.parse_input(make_usb_input())
        self.assertEqual(state.touch, (None, None))

    def test_touch_coordinates_round_trip(self):
        state = ds.parse_input(make_usb_input(touch0=(1919, 1079)))
        self.assertEqual(state.touch[0], (1919, 1079))
        self.assertIsNone(state.touch[1])

    def test_second_touch_point(self):
        state = ds.parse_input(make_usb_input(touch1=(100, 200)))
        self.assertEqual(state.touch[1], (100, 200))

    def test_bluetooth_body_is_offset_by_one_more_byte(self):
        state = ds.parse_input(make_bt_input(gyro=(7, 8, 9), status=0x1A))
        self.assertEqual(state.gyro_raw, (7, 8, 9))
        self.assertEqual(state.battery_percent, 100)

    def test_bluetooth_rejects_bad_crc(self):
        corrupt = bytearray(make_bt_input(gyro=(1, 2, 3)))
        corrupt[20] ^= 0xFF
        self.assertIsNone(ds.parse_input(bytes(corrupt)))


class TestParseCalibration(unittest.TestCase):
    @staticmethod
    def make(bias=(0, 0, 0), plus=(1000, 1000, 1000), minus=(-1000, -1000, -1000),
             speed=(1024, 1024), report_id=ds.FEATURE_CALIBRATION):
        data = bytearray(ds.CALIBRATION_SIZE)
        data[0] = report_id
        body = 1
        for i in range(3):
            struct.pack_into("<h", data, body + i * 2, bias[i])
            struct.pack_into("<h", data, body + 6 + i * 4, plus[i])
            struct.pack_into("<h", data, body + 8 + i * 4, minus[i])
        struct.pack_into("<h", data, body + 18, speed[0])
        struct.pack_into("<h", data, body + 20, speed[1])
        return bytes(data)

    def test_returns_three_scales(self):
        scales = ds.parse_calibration(self.make())
        self.assertEqual(len(scales), 3)

    def test_scale_matches_hand_computation(self):
        # speed 1024+1024 = 2048 over |1000-0| + |-1000-0| = 2000
        scales = ds.parse_calibration(self.make())
        for scale in scales:
            self.assertAlmostEqual(scale, 2048.0 / 2000.0, places=9)

    def test_realistic_values_land_near_one_sixteenth(self):
        # Shape matching a real controller: scale close to 0.061 deg/s per LSB.
        scales = ds.parse_calibration(self.make(plus=(16800, 16800, 16800),
                                                minus=(-16800, -16800, -16800),
                                                speed=(1024, 1024)))
        for scale in scales:
            self.assertAlmostEqual(scale, 0.0609, places=3)

    def test_rejects_wrong_length(self):
        self.assertIsNone(ds.parse_calibration(bytes(20)))

    def test_rejects_wrong_report_id(self):
        self.assertIsNone(ds.parse_calibration(self.make(report_id=0x09)))

    def test_rejects_zero_span(self):
        self.assertIsNone(ds.parse_calibration(self.make(plus=(0, 0, 0), minus=(0, 0, 0))))

    def test_rejects_implausible_scale(self):
        self.assertIsNone(ds.parse_calibration(self.make(plus=(1, 1, 1), minus=(-1, -1, -1))))

    def test_default_scale_constant(self):
        self.assertAlmostEqual(ds.DEFAULT_GYRO_SCALE, 1.0 / 16.0)
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```bash
python -m unittest tests.test_dualsense -v
```

Expected: `AttributeError: module 'ps5led.dualsense' has no attribute 'parse_input'`.

- [ ] **Step 3: Implement the parsers**

Append to `ps5led/dualsense.py`:

```python
import struct
from typing import NamedTuple, Optional, Tuple

from .crc import INPUT_SEED, check_crc32

DEFAULT_GYRO_SCALE = 1.0 / 16.0

BODY_SIZE = 63

# Offsets inside struct dualsense_input_report.
_STICKS = 0
_TRIGGERS = 4
_BUTTONS = 7
_GYRO = 15
_ACCEL = 21
_TIMESTAMP = 27
_TOUCH = 32
_STATUS = 52

# Where the body begins, keyed by (report id, total length).
_BODY_OFFSET = {
    (INPUT_REPORT_USB, USB_INPUT_SIZE): 1,
    (INPUT_REPORT_BT, BT_INPUT_SIZE): 2,
}


class InputState(NamedTuple):
    sticks: Tuple[int, int, int, int]
    triggers: Tuple[int, int]
    buttons: int
    gyro_raw: Tuple[int, int, int]
    accel_raw: Tuple[int, int, int]
    timestamp: int
    touch: Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]
    battery_percent: int
    charge_state: int


def _touch_point(data, base):
    """Decode one touch slot. Bit 7 of the first byte is set when no finger is down."""
    if data[base] & 0x80:
        return None
    x = data[base + 1] | ((data[base + 2] & 0x0F) << 8)
    y = (data[base + 2] >> 4) | (data[base + 3] << 4)
    return (x, y)


def parse_input(data):
    """Decode a DualSense input report, or None if it is not one we trust.

    Rejects the reduced 10-byte Bluetooth report the controller sends before its
    calibration has been read, and any Bluetooth report whose CRC fails — a
    corrupt sample would otherwise be integrated into the orientation estimate.
    """
    if len(data) < 2:
        return None
    body = _BODY_OFFSET.get((data[0], len(data)))
    if body is None:
        return None
    if data[0] == INPUT_REPORT_BT and not check_crc32(INPUT_SEED, data):
        return None

    def i16(offset):
        return struct.unpack_from("<h", data, body + offset)[0]

    status = data[body + _STATUS]
    return InputState(
        sticks=tuple(data[body + _STICKS:body + _STICKS + 4]),
        triggers=(data[body + _TRIGGERS], data[body + _TRIGGERS + 1]),
        buttons=struct.unpack_from("<I", data, body + _BUTTONS)[0],
        gyro_raw=(i16(_GYRO), i16(_GYRO + 2), i16(_GYRO + 4)),
        accel_raw=(i16(_ACCEL), i16(_ACCEL + 2), i16(_ACCEL + 4)),
        timestamp=struct.unpack_from("<I", data, body + _TIMESTAMP)[0],
        touch=(_touch_point(data, body + _TOUCH), _touch_point(data, body + _TOUCH + 4)),
        battery_percent=min(100, (status & 0x0F) * 10),
        charge_state=status >> 4,
    )


def parse_calibration(data):
    """Per-axis gyro scale in degrees per second per LSB, or None if implausible.

    Reading this feature report also switches a Bluetooth DualSense out of its
    reduced report into the full 0x31 report, so the caller should do it on every
    connection even when the default scale would be acceptable.
    """
    if len(data) != CALIBRATION_SIZE or data[0] != FEATURE_CALIBRATION:
        return None
    body = 1

    def i16(offset):
        return struct.unpack_from("<h", data, body + offset)[0]

    speed = i16(18) + i16(20)
    scales = []
    for axis in range(3):
        bias = i16(axis * 2)
        span = abs(i16(6 + axis * 4) - bias) + abs(i16(8 + axis * 4) - bias)
        if span == 0:
            return None
        scale = speed / float(span)
        if not 0.001 < scale < 1.0:
            return None
        scales.append(scale)
    return tuple(scales)
```

Move the `import struct` and the `typing` import to the top of the file with the
other imports rather than leaving them mid-module, and merge the second
`from .crc import` into the first.

- [ ] **Step 4: Run the tests and confirm they pass**

```bash
python -m unittest tests.test_dualsense -v
```

Expected: 44 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/dualsense.py tests/test_dualsense.py
git commit -m "feat(ds5): input report and calibration parsing"
```

---

### Task 4: DualShock 4 output reports

**Files:**
- Create: `ps5led/dualshock4.py`, `tests/test_dualshock4.py`

**Interfaces:**
- Consumes: `ps5led.crc.OUTPUT_SEED`, `ps5led.crc.append_crc32`, `check_crc32`
- Produces: `PRODUCT_IDS = (0x05C4, 0x09CC, 0x0BA0)`, `OUTPUT_REPORT_USB = 0x05`,
  `OUTPUT_REPORT_BT = 0x11`, `USB_OUTPUT_SIZE = 32`, `BT_OUTPUT_SIZE = 78`,
  `build_output(transport, rgb, blink=(0, 0)) -> bytes`

`struct dualshock4_output_report_common` is 11 bytes: `valid_flag0`,
`valid_flag1`, `reserved`, `motor_right`, `motor_left`, `lightbar_red`,
`lightbar_green`, `lightbar_blue`, `lightbar_blink_on`, `lightbar_blink_off`.

USB wraps it as report `0x05` at index 1, total 32 bytes, no CRC. Bluetooth
wraps it as report `0x11` with `hw_control` at index 1 and `audio_control` at
index 2, common at index 3, total 78 bytes, CRC32 at the end.

The Bluetooth `hw_control` byte **must** be `0x80 | 0x40` — `HID` plus `CRC32`.
Without it the controller silently discards the whole report. `valid_flag0` gets
`0x02` to enable the LED, and `0x04` additionally when blink timings are set.

Note for the implementer: the old `dualled_pro.py` wrote `valid_flag0 = 0xFF`,
which happens to work because it sets the LED bit among others, but it also
claims control of the rumble motors it then leaves at zero. Set only the bits
this app means.

- [ ] **Step 1: Write the failing test**

`tests/test_dualshock4.py`:

```python
import unittest

from ps5led import dualshock4 as ds4
from ps5led.crc import OUTPUT_SEED, check_crc32


class TestConstants(unittest.TestCase):
    def test_product_ids(self):
        self.assertEqual(ds4.PRODUCT_IDS, (0x05C4, 0x09CC, 0x0BA0))

    def test_report_ids_and_sizes(self):
        self.assertEqual((ds4.OUTPUT_REPORT_USB, ds4.USB_OUTPUT_SIZE), (0x05, 32))
        self.assertEqual((ds4.OUTPUT_REPORT_BT, ds4.BT_OUTPUT_SIZE), (0x11, 78))


class TestUsb(unittest.TestCase):
    def test_full_packet_bytes(self):
        packet = ds4.build_output(ds4.TRANSPORT_USB, (0x11, 0x22, 0x33))
        expected = bytearray(32)
        expected[0] = 0x05
        expected[1] = 0x02  # valid_flag0: LED only
        expected[6], expected[7], expected[8] = 0x11, 0x22, 0x33
        self.assertEqual(packet, bytes(expected))

    def test_no_rumble_bit(self):
        packet = ds4.build_output(ds4.TRANSPORT_USB, (1, 2, 3))
        self.assertEqual(packet[1] & 0x01, 0, "motor bit must stay clear")

    def test_blink_sets_its_own_bit_and_bytes(self):
        packet = ds4.build_output(ds4.TRANSPORT_USB, (1, 2, 3), blink=(10, 20))
        self.assertEqual(packet[1], 0x02 | 0x04)
        self.assertEqual(packet[9], 10)
        self.assertEqual(packet[10], 20)

    def test_rgb_range_checked(self):
        with self.assertRaises(ValueError):
            ds4.build_output(ds4.TRANSPORT_USB, (0, 0, 256))


class TestBluetooth(unittest.TestCase):
    def test_length_and_report_id(self):
        packet = ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 3))
        self.assertEqual(len(packet), 78)
        self.assertEqual(packet[0], 0x11)

    def test_hw_control_enables_hid_and_crc(self):
        packet = ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 3))
        self.assertEqual(packet[1], 0xC0)

    def test_colour_at_indices_8_9_10(self):
        packet = ds4.build_output(ds4.TRANSPORT_BT, (0x44, 0x55, 0x66))
        self.assertEqual(packet[8], 0x44)
        self.assertEqual(packet[9], 0x55)
        self.assertEqual(packet[10], 0x66)

    def test_valid_flag0_at_index_3(self):
        self.assertEqual(ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 3))[3], 0x02)

    def test_crc_is_valid(self):
        self.assertTrue(check_crc32(OUTPUT_SEED, ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 3))))

    def test_crc_covers_the_colour(self):
        a = ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 3))
        b = ds4.build_output(ds4.TRANSPORT_BT, (1, 2, 4))
        self.assertNotEqual(a[-4:], b[-4:])


class TestTransportValidation(unittest.TestCase):
    def test_unknown_transport(self):
        with self.assertRaises(ValueError):
            ds4.build_output("infrared", (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_dualshock4 -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.dualshock4'`.

- [ ] **Step 3: Implement**

`ps5led/dualshock4.py`:

```python
"""DualShock 4 (DS4) HID output reports.

Layout from struct dualshock4_output_report_* in drivers/hid/hid-playstation.c.
Pure functions, no I/O.
"""

from .crc import OUTPUT_SEED, append_crc32

VENDOR_ID = 0x054C
PRODUCT_IDS = (0x05C4, 0x09CC, 0x0BA0)

OUTPUT_REPORT_USB = 0x05
OUTPUT_REPORT_BT = 0x11
USB_OUTPUT_SIZE = 32
BT_OUTPUT_SIZE = 78

TRANSPORT_USB = "usb"
TRANSPORT_BT = "bt"

VALID_FLAG0_MOTOR = 0x01
VALID_FLAG0_LED = 0x02
VALID_FLAG0_LED_BLINK = 0x04

HWCTL_CRC32 = 0x40
HWCTL_HID = 0x80

# Offsets inside the common block, and where that block starts per transport.
_RED, _GREEN, _BLUE, _BLINK_ON, _BLINK_OFF = 5, 6, 7, 8, 9
_COMMON_OFFSET = {TRANSPORT_USB: 1, TRANSPORT_BT: 3}
_SIZE = {TRANSPORT_USB: USB_OUTPUT_SIZE, TRANSPORT_BT: BT_OUTPUT_SIZE}


def build_output(transport, rgb, blink=(0, 0)):
    """Build one DualShock 4 output report carrying a lightbar colour."""
    if transport not in _COMMON_OFFSET:
        raise ValueError("unknown transport: %r" % (transport,))
    if len(rgb) != 3 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in rgb):
        raise ValueError("rgb out of range: %r" % (rgb,))

    offset = _COMMON_OFFSET[transport]
    report = bytearray(_SIZE[transport])

    if transport == TRANSPORT_USB:
        report[0] = OUTPUT_REPORT_USB
    else:
        report[0] = OUTPUT_REPORT_BT
        # Without HID|CRC32 here the controller discards the report entirely.
        report[1] = HWCTL_HID | HWCTL_CRC32

    flag0 = VALID_FLAG0_LED
    report[offset + _RED], report[offset + _GREEN], report[offset + _BLUE] = rgb
    if blink != (0, 0):
        flag0 |= VALID_FLAG0_LED_BLINK
        report[offset + _BLINK_ON], report[offset + _BLINK_OFF] = blink
    report[offset] = flag0

    if transport == TRANSPORT_BT:
        append_crc32(OUTPUT_SEED, report)

    return bytes(report)
```

- [ ] **Step 4: Run and confirm passing**

```bash
python -m unittest tests.test_dualshock4 -v
```

Expected: 11 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/dualshock4.py tests/test_dualshock4.py
git commit -m "feat(ds4): output reports for USB and Bluetooth"
```

---

### Task 5: Windows HID transport

**Files:**
- Create: `ps5led/hid_win.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `DeviceInfo` — `NamedTuple` with `path: str`, `vendor_id: int`, `product_id: int`, `product: str`, `input_length: int`, `output_length: int`, `feature_length: int`, `transport: str`
  - `enumerate_devices(vendor_id: Optional[int] = None) -> List[DeviceInfo]`
  - `HidDevice` — `open(path)` classmethod, `read(timeout_ms) -> Optional[bytes]`, `write(data: bytes) -> int`, `get_feature(report_id, length) -> Optional[bytes]`, `close()`, context-manager protocol, and a `last_error: Optional[str]` attribute
  - `HidError(OSError)`

This is the only Windows-specific module. **It must never be imported at module
scope by anything CI imports on Linux** — callers do `from . import hid_win`
inside a function body.

Three rules that are not negotiable, all of them consequences of things that have
already gone wrong in comparable code:

1. Declare `argtypes` and `restype` for every function. `HANDLE` is
   `ctypes.c_void_p`. Left undeclared, a returned handle is truncated to 32 bits
   and the failure appears far from the cause.
2. Write with `WriteFile`, padding to `output_length`. Microsoft documents that
   `HidD_SetOutputReport` can leave some devices unresponsive.
3. Open with `FILE_FLAG_OVERLAPPED` and give every read a timeout. A blocking
   read cannot be cancelled at shutdown, and a Bluetooth controller that has gone
   to sleep would hang the reader thread with no way to notice the disconnect.

Transport is derived from `HIDP_CAPS.InputReportByteLength`: 64 means USB, 78
means Bluetooth. That was measured on real hardware and is more reliable than
parsing the device interface path.

`SetupDiGetDeviceInterfaceDetailW` needs its `cbSize` set to 8 on 64-bit and 6 on
32-bit — the size of the fixed part of `SP_DEVICE_INTERFACE_DETAIL_DATA_W`, not
of the buffer you allocated. Getting this wrong yields `ERROR_INVALID_USER_BUFFER`
with no other clue.

- [ ] **Step 1: Write the guard test**

Create `tests/test_hid_win_import.py`:

```python
import platform
import unittest


class TestPlatformIsolation(unittest.TestCase):
    def test_protocol_modules_do_not_pull_in_windows_code(self):
        """crc/dualsense/dualshock4 must import anywhere — CI runs on Linux."""
        import ps5led.crc  # noqa: F401
        import ps5led.dualsense  # noqa: F401
        import ps5led.dualshock4  # noqa: F401

    @unittest.skipUnless(platform.system() == "Windows", "Windows-only module")
    def test_hid_win_imports_on_windows(self):
        from ps5led import hid_win

        self.assertTrue(hasattr(hid_win, "enumerate_devices"))
        self.assertTrue(hasattr(hid_win, "HidDevice"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm the Windows case fails**

```bash
python -m unittest tests.test_hid_win_import -v
```

Expected on Windows: the first test passes, the second fails with
`ModuleNotFoundError: No module named 'ps5led.hid_win'`.

- [ ] **Step 3: Implement `hid_win.py`**

```python
"""Windows HID transport over ctypes — setupapi for discovery, hid.dll for caps,
CreateFile/ReadFile/WriteFile for I/O.

Windows only. Import this from inside a function body, never at the module scope
of anything the Linux CI runner imports.

Every prototype below declares argtypes and restype. On 64-bit Windows an
undeclared handle return defaults to c_int and silently truncates.
"""

import ctypes
import ctypes.wintypes as wintypes
from typing import List, NamedTuple, Optional

_hid = ctypes.WinDLL("hid")
_setupapi = ctypes.WinDLL("setupapi")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HANDLE = ctypes.c_void_p
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10

ERROR_IO_PENDING = 997
ERROR_DEVICE_NOT_CONNECTED = 1167
WAIT_TIMEOUT = 0x102
WAIT_OBJECT_0 = 0

TRANSPORT_USB = "usb"
TRANSPORT_BT = "bt"
_TRANSPORT_BY_INPUT_LENGTH = {64: TRANSPORT_USB, 78: TRANSPORT_BT}


class HidError(OSError):
    """A HID operation failed; the message carries the Win32 error."""


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17), ("Counts", wintypes.USHORT * 13)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", HANDLE)]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetHidGuid.restype = None
_hid.HidD_GetAttributes.argtypes = [HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidP_GetCaps.restype = ctypes.c_long
_hid.HidD_GetProductString.argtypes = [HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetProductString.restype = wintypes.BOOLEAN
_hid.HidD_GetFeature.argtypes = [HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetFeature.restype = wintypes.BOOLEAN

_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                           wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, HANDLE]
_kernel32.CreateFileW.restype = HANDLE
_kernel32.CloseHandle.argtypes = [HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                   wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = HANDLE
_kernel32.ReadFile.argtypes = [HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CancelIoEx.argtypes = [HANDLE, ctypes.POINTER(OVERLAPPED)]
_kernel32.CancelIoEx.restype = wintypes.BOOL


class DeviceInfo(NamedTuple):
    path: str
    vendor_id: int
    product_id: int
    product: str
    input_length: int
    output_length: int
    feature_length: int
    transport: str


def _interface_paths():
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not devs or devs == INVALID_HANDLE_VALUE:
        raise HidError("SetupDiGetClassDevsW failed: %d" % ctypes.get_last_error())
    paths = []
    index = 0
    try:
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                    devs, None, ctypes.byref(guid), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                devs, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            if not needed.value:
                continue
            buf = ctypes.create_string_buffer(needed.value)
            # cbSize is the size of the fixed part of the struct, not of the
            # buffer: 8 on 64-bit (4-byte size + WCHAR alignment), 6 on 32-bit.
            fixed = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(fixed)), 4)
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(
                    devs, ctypes.byref(data), buf, needed, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(devs)
    return paths


def _describe(handle, path):
    attrs = HIDD_ATTRIBUTES()
    attrs.Size = ctypes.sizeof(attrs)
    if not _hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
        return None
    preparsed = ctypes.c_void_p()
    if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        return None
    caps = HIDP_CAPS()
    try:
        _hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
    finally:
        _hid.HidD_FreePreparsedData(preparsed)
    name = ctypes.create_unicode_buffer(128)
    _hid.HidD_GetProductString(handle, name, ctypes.sizeof(name))
    return DeviceInfo(
        path=path,
        vendor_id=attrs.VendorID,
        product_id=attrs.ProductID,
        product=name.value,
        input_length=caps.InputReportByteLength,
        output_length=caps.OutputReportByteLength,
        feature_length=caps.FeatureReportByteLength,
        transport=_TRANSPORT_BY_INPUT_LENGTH.get(caps.InputReportByteLength, "unknown"),
    )


def enumerate_devices(vendor_id=None):
    # type: (Optional[int]) -> List[DeviceInfo]
    """Every present HID interface, optionally filtered by vendor."""
    found = []
    for path in _interface_paths():
        handle = _kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            continue
        try:
            info = _describe(handle, path)
        finally:
            _kernel32.CloseHandle(handle)
        if info and (vendor_id is None or info.vendor_id == vendor_id):
            found.append(info)
    return found


class HidDevice(object):
    """One open HID interface with overlapped read and write.

    The reader thread and the writer thread may share an instance: each
    operation uses its own OVERLAPPED and event, which is what makes that safe.
    """

    def __init__(self, handle, info):
        self._handle = handle
        self.info = info
        self.last_error = None  # type: Optional[str]
        self._read_event = _kernel32.CreateEventW(None, True, False, None)
        self._write_event = _kernel32.CreateEventW(None, True, False, None)

    @classmethod
    def open(cls, path):
        handle = _kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            raise HidError("cannot open %s: Win32 error %d" % (path, ctypes.get_last_error()))
        info = _describe(handle, path)
        if info is None:
            _kernel32.CloseHandle(handle)
            raise HidError("cannot read capabilities for %s" % path)
        return cls(handle, info)

    def read(self, timeout_ms=1000):
        """One input report, or None on timeout. Raises HidError if the device left."""
        if self._handle is None:
            raise HidError("device is closed")
        length = self.info.input_length
        buf = ctypes.create_string_buffer(length)
        transferred = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._read_event
        ok = _kernel32.ReadFile(self._handle, buf, length,
                                ctypes.byref(transferred), ctypes.byref(overlapped))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise HidError("ReadFile failed: Win32 error %d" % err)
            wait = _kernel32.WaitForSingleObject(self._read_event, timeout_ms)
            if wait == WAIT_TIMEOUT:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                              ctypes.byref(transferred), True)
                return None
            if wait != WAIT_OBJECT_0:
                raise HidError("WaitForSingleObject returned %d" % wait)
            if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                 ctypes.byref(transferred), False):
                raise HidError("GetOverlappedResult failed: Win32 error %d"
                               % ctypes.get_last_error())
        return buf.raw[:transferred.value]

    def write(self, data):
        """Send an output report, padded to OutputReportByteLength.

        WriteFile, never HidD_SetOutputReport: Microsoft documents that some
        devices stop responding when driven through HidD_SetXxx.
        """
        if self._handle is None:
            raise HidError("device is closed")
        length = self.info.output_length
        if len(data) > length:
            raise HidError("report is %d bytes, device accepts %d" % (len(data), length))
        buf = ctypes.create_string_buffer(bytes(data).ljust(length, b"\x00"), length)
        transferred = wintypes.DWORD(0)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._write_event
        ok = _kernel32.WriteFile(self._handle, buf, length,
                                 ctypes.byref(transferred), ctypes.byref(overlapped))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                self.last_error = "WriteFile failed: Win32 error %d" % err
                raise HidError(self.last_error)
            if _kernel32.WaitForSingleObject(self._write_event, 1000) != WAIT_OBJECT_0:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(overlapped))
                self.last_error = "write timed out"
                raise HidError(self.last_error)
            if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                                 ctypes.byref(transferred), False):
                self.last_error = ("write failed: Win32 error %d" % ctypes.get_last_error())
                raise HidError(self.last_error)
        self.last_error = None
        return transferred.value

    def get_feature(self, report_id, length):
        """Read a feature report, or None if the device refused."""
        if self._handle is None:
            raise HidError("device is closed")
        buf = ctypes.create_string_buffer(length)
        buf[0] = bytes([report_id])
        if not _hid.HidD_GetFeature(self._handle, buf, length):
            self.last_error = ("HidD_GetFeature(%#x) failed: Win32 error %d"
                               % (report_id, ctypes.get_last_error()))
            return None
        return buf.raw[:length]

    def close(self):
        for event in (self._read_event, self._write_event):
            if event:
                _kernel32.CloseHandle(event)
        self._read_event = self._write_event = None
        if self._handle is not None:
            _kernel32.CancelIoEx(self._handle, None)
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
```

- [ ] **Step 4: Run the guard test, then verify against real hardware**

```bash
python -m unittest tests.test_hid_win_import -v
```

Then, with a DualSense connected by USB:

```bash
python -c "from ps5led.hid_win import enumerate_devices; [print(d) for d in enumerate_devices(0x054C)]"
```

Expected: at least one `DeviceInfo` with `vendor_id=1356`, `product_id=3302`,
`input_length=64`, `transport='usb'`. If `transport` reads `unknown`, record the
actual `input_length` before going further — the transport table needs that
value and guessing is not acceptable.

- [ ] **Step 5: Commit**

```bash
git add ps5led/hid_win.py tests/test_hid_win_import.py
git commit -m "feat(hid): Windows ctypes HID transport, overlapped IO"
```

---

### Task 6: First light — the live proof

**Files:**
- Create: `tools/live_check.py`

**Interfaces:**
- Consumes: `hid_win.enumerate_devices`, `hid_win.HidDevice`, `dualsense.build_output`,
  `dualsense.parse_input`, `dualsense.parse_calibration`, `dualshock4.build_output`
- Produces: nothing importable — this is an operator tool, and it is the gate the
  whole plan turns on

This task writes no new library code. It exists because every claim in the spec
about Bluetooth is still theory, and because a lightbar that does not change
colour is the entire bug being fixed. Nothing downstream is worth building until
this passes on both transports.

- [ ] **Step 1: Write the tool**

`tools/live_check.py`:

```python
"""Operator tool: prove the lightbar responds on real hardware.

    python tools/live_check.py            # cycle red, green, blue, then restore
    python tools/live_check.py --watch    # stream motion and battery for 10 s

Not part of the test suite: it needs a controller in your hand.
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from ps5led import dualsense as ds
from ps5led import dualshock4 as ds4
from ps5led.hid_win import HidDevice, enumerate_devices


def pick():
    devices = enumerate_devices(ds.VENDOR_ID)
    if not devices:
        raise SystemExit("No Sony controller found. Connect one and try again.")
    for info in devices:
        print("  %s  pid=%#06x  in=%d out=%d feat=%d  transport=%s"
              % (info.product, info.product_id, info.input_length,
                 info.output_length, info.feature_length, info.transport))
    for info in devices:
        if info.product_id in ds.PRODUCT_IDS + ds4.PRODUCT_IDS:
            return info
    raise SystemExit("Sony device present but not a controller we drive.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    info = pick()
    is_ds5 = info.product_id in ds.PRODUCT_IDS
    print("\nusing %s over %s\n" % (info.product, info.transport))

    with HidDevice.open(info.path) as dev:
        scales = None
        if is_ds5:
            raw = dev.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
            scales = ds.parse_calibration(raw) if raw else None
            print("calibration: %s" % ("scales %s" % (scales,) if scales else "unavailable"))
            dev.write(ds.build_output(info.transport, info.output_length,
                                      lightbar_setup=True, seq=0))
            time.sleep(0.05)

        seq = 1
        for name, rgb in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                          ("blue", (0, 0, 255)), ("restored", (0, 170, 255))):
            if is_ds5:
                packet = ds.build_output(info.transport, info.output_length, rgb=rgb, seq=seq)
            else:
                packet = ds4.build_output(info.transport, rgb)
            dev.write(packet)
            seq += 1
            print("wrote %-9s %s" % (name, rgb))
            time.sleep(0.8)

        if args.watch and is_ds5:
            print("\nwatching for 10 s — move the controller\n")
            scale = scales[0] if scales else ds.DEFAULT_GYRO_SCALE
            deadline = time.time() + 10
            while time.time() < deadline:
                data = dev.read(timeout_ms=200)
                if not data:
                    continue
                state = ds.parse_input(data)
                if state is None:
                    continue
                print("\rbatt %3d%% state %d  gyro %8.1f %8.1f %8.1f deg/s   "
                      % (state.battery_percent, state.charge_state,
                         state.gyro_raw[0] * scale, state.gyro_raw[1] * scale,
                         state.gyro_raw[2] * scale), end="")
            print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it over USB**

```bash
python tools/live_check.py --watch
```

Expected: the lightbar turns red, then green, then blue, then settles on cyan;
calibration prints three scales near `0.061`; moving the controller shows
non-zero degrees per second that return to roughly zero when it is still.

- [ ] **Step 3: Run it over Bluetooth**

Unplug the cable, pair the controller over Bluetooth, then run the same command.

Expected: identical behaviour. `transport=bt`, `in=78`, `out=78`.

If the lightbar does not respond over Bluetooth, the cause is one of exactly
three things, in this order of likelihood: the CRC is being computed over the
wrong span, the setup packet was skipped, or the report never reached 78 bytes.
Print `packet.hex()` and check the last four bytes against
`ps_crc32(0xA2, packet[:74])` before changing anything else.

If input reports keep arriving as 10 bytes, the calibration read did not happen —
that read is what switches the controller into the full report.

- [ ] **Step 4: Record the outcome**

Append a short section to the spec under §3 naming the date, both transports, and
the observed values. A claim of Bluetooth support that is not written down beside
its evidence is not a claim, it is a hope.

- [ ] **Step 5: Commit**

```bash
git add tools/live_check.py docs/superpowers/specs/2026-09-07-webview-rewrite-design.md
git commit -m "test(live): hardware check for lightbar and motion on both transports"
```

---

### Task 7: Shared state

**Files:**
- Create: `ps5led/state.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: nothing
- Produces: `AppState` with `seq: int`, `update(**fields) -> int`, `snapshot() -> dict`,
  `wait_for_change(last_seq: int, timeout: float) -> Optional[dict]`

`AppState` is the only object shared between threads. It holds a
`threading.Condition`, a plain dict of fields, and a monotonic `seq` that
advances on every mutation that actually changed something. `snapshot()` returns
a shallow copy including the current `seq`, so a reader can hold it without a
lock. `wait_for_change` lets the SSE thread block instead of polling.

Setting a field to the value it already holds must not advance `seq` — otherwise
the SSE stream would emit 60 identical frames a second while the controller sits
still.

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
import threading
import time
import unittest

from ps5led.state import AppState


class TestAppState(unittest.TestCase):
    def test_starts_at_zero(self):
        self.assertEqual(AppState().seq, 0)

    def test_update_advances_seq(self):
        state = AppState()
        self.assertEqual(state.update(rgb=(1, 2, 3)), 1)
        self.assertEqual(state.seq, 1)

    def test_snapshot_carries_fields_and_seq(self):
        state = AppState()
        state.update(rgb=(1, 2, 3), battery=80)
        snap = state.snapshot()
        self.assertEqual(snap["rgb"], (1, 2, 3))
        self.assertEqual(snap["battery"], 80)
        self.assertEqual(snap["seq"], 1)

    def test_snapshot_is_a_copy(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        snap = state.snapshot()
        snap["rgb"] = (9, 9, 9)
        self.assertEqual(state.snapshot()["rgb"], (1, 2, 3))

    def test_writing_the_same_value_does_not_advance_seq(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        self.assertEqual(state.update(rgb=(1, 2, 3)), 1)

    def test_partial_no_op_still_advances_for_the_changed_field(self):
        state = AppState()
        state.update(rgb=(1, 2, 3), battery=80)
        self.assertEqual(state.update(rgb=(1, 2, 3), battery=79), 2)

    def test_wait_returns_immediately_when_already_ahead(self):
        state = AppState()
        state.update(rgb=(1, 2, 3))
        started = time.time()
        snap = state.wait_for_change(0, timeout=5)
        self.assertIsNotNone(snap)
        self.assertLess(time.time() - started, 0.5)

    def test_wait_times_out_when_nothing_changes(self):
        self.assertIsNone(AppState().wait_for_change(0, timeout=0.1))

    def test_wait_wakes_on_update_from_another_thread(self):
        state = AppState()
        result = []

        def waiter():
            result.append(state.wait_for_change(0, timeout=5))

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.05)
        state.update(battery=42)
        thread.join(timeout=5)
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0])
        self.assertEqual(result[0]["battery"], 42)

    def test_concurrent_updates_produce_unique_sequence_numbers(self):
        state = AppState()
        seen = []
        lock = threading.Lock()

        def worker(base):
            for i in range(50):
                seq = state.update(**{"f%d" % base: i})
                with lock:
                    seen.append(seq)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(seen), len(set(seen)), "seq must never repeat")
        self.assertEqual(state.seq, 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_state -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.state'`.

- [ ] **Step 3: Implement**

`ps5led/state.py`:

```python
"""The one object shared between threads.

Everything else in the engine is single-owner. Readers take a snapshot and hold
a plain dict; nobody hands a callback across a thread boundary.
"""

import threading


class AppState(object):
    def __init__(self):
        self._condition = threading.Condition()
        self._fields = {}
        self._seq = 0

    @property
    def seq(self):
        with self._condition:
            return self._seq

    def update(self, **fields):
        """Merge fields in. Returns the sequence number after the merge.

        A field written with the value it already holds is not a change, so the
        sequence does not advance — otherwise a motionless controller would still
        push sixty identical frames a second down the stream.
        """
        with self._condition:
            changed = False
            for key, value in fields.items():
                if key not in self._fields or self._fields[key] != value:
                    self._fields[key] = value
                    changed = True
            if changed:
                self._seq += 1
                self._condition.notify_all()
            return self._seq

    def snapshot(self):
        with self._condition:
            snap = dict(self._fields)
            snap["seq"] = self._seq
            return snap

    def wait_for_change(self, last_seq, timeout=25.0):
        """Snapshot once the sequence passes ``last_seq``, or None on timeout."""
        deadline = None
        with self._condition:
            while self._seq <= last_seq:
                if deadline is None:
                    import time
                    deadline = time.monotonic() + timeout
                    remaining = timeout
                else:
                    import time
                    remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            snap = dict(self._fields)
            snap["seq"] = self._seq
            return snap
```

Move `import time` to the top of the file next to `import threading` rather than
importing it inside the loop.

- [ ] **Step 4: Run and confirm passing**

```bash
python -m unittest tests.test_state -v
```

Expected: 10 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/state.py tests/test_state.py
git commit -m "feat(state): lock-guarded shared state with change sequencing"
```

---

### Task 8: Lighting engine

**Files:**
- Create: `ps5led/engine.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: `ps5led.state.AppState`
- Produces: `MODES = ("manual", "rainbow", "wave", "flash", "battery")`,
  `colour_for(mode, phase, settings) -> Tuple[int, int, int]`,
  `hsv_to_rgb(h, s, v) -> Tuple[int, int, int]`,
  `Engine(state, write_colour, interval=1/30.0)` with `start()`, `stop()`, `set_mode()`, `set_colour()`

The colour maths is separated from the thread so it can be tested without one.
`colour_for` is a pure function of the mode, a phase in `[0, 1)`, and a settings
dict; the `Engine` thread only advances the phase, calls it, and writes when the
result differs from the last value written.

Writing only on change is what keeps a solid colour at zero USB traffic. The old
implementation wrote every frame regardless.

`settings` keys: `colour` an `(r, g, b)` tuple, `brightness` a float in
`[0.2, 1.0]`, `duty` a float in `[0.1, 0.9]`, `battery` an int percent or `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_engine.py`:

```python
import threading
import time
import unittest

from ps5led.engine import Engine, MODES, colour_for, hsv_to_rgb
from ps5led.state import AppState

BASE = {"colour": (0, 170, 255), "brightness": 1.0, "duty": 0.5, "battery": None}


def settings(**overrides):
    merged = dict(BASE)
    merged.update(overrides)
    return merged


class TestHsv(unittest.TestCase):
    def test_primaries(self):
        self.assertEqual(hsv_to_rgb(0.0, 1.0, 1.0), (255, 0, 0))
        self.assertEqual(hsv_to_rgb(1 / 3.0, 1.0, 1.0), (0, 255, 0))
        self.assertEqual(hsv_to_rgb(2 / 3.0, 1.0, 1.0), (0, 0, 255))

    def test_value_scales_output(self):
        self.assertEqual(hsv_to_rgb(0.0, 1.0, 0.5), (127, 0, 0))

    def test_zero_saturation_is_grey(self):
        r, g, b = hsv_to_rgb(0.4, 0.0, 1.0)
        self.assertEqual((r, g, b), (255, 255, 255))

    def test_hue_wraps(self):
        self.assertEqual(hsv_to_rgb(1.0, 1.0, 1.0), hsv_to_rgb(0.0, 1.0, 1.0))

    def test_channels_stay_in_range(self):
        for step in range(0, 100):
            for channel in hsv_to_rgb(step / 100.0, 1.0, 1.0):
                self.assertTrue(0 <= channel <= 255)


class TestColourFor(unittest.TestCase):
    def test_modes_are_named(self):
        self.assertEqual(MODES, ("manual", "rainbow", "wave", "flash", "battery"))

    def test_manual_ignores_phase(self):
        for phase in (0.0, 0.25, 0.9):
            self.assertEqual(colour_for("manual", phase, settings()), (0, 170, 255))

    def test_manual_applies_brightness(self):
        self.assertEqual(colour_for("manual", 0.0, settings(colour=(200, 100, 50),
                                                            brightness=0.5)),
                         (100, 50, 25))

    def test_rainbow_moves_with_phase(self):
        self.assertNotEqual(colour_for("rainbow", 0.0, settings()),
                            colour_for("rainbow", 0.5, settings()))

    def test_rainbow_is_periodic(self):
        self.assertEqual(colour_for("rainbow", 0.0, settings()),
                         colour_for("rainbow", 1.0, settings()))

    def test_wave_dims_the_base_colour_without_changing_hue(self):
        bright = colour_for("wave", 0.25, settings(colour=(255, 0, 0)))
        dim = colour_for("wave", 0.75, settings(colour=(255, 0, 0)))
        self.assertEqual((bright[1], bright[2]), (0, 0))
        self.assertGreater(bright[0], dim[0])

    def test_flash_is_on_below_duty_and_off_above(self):
        on = colour_for("flash", 0.1, settings(colour=(255, 0, 0), duty=0.5))
        off = colour_for("flash", 0.9, settings(colour=(255, 0, 0), duty=0.5))
        self.assertEqual(on, (255, 0, 0))
        self.assertEqual(off, (0, 0, 0))

    def test_flash_duty_shifts_the_boundary(self):
        self.assertEqual(colour_for("flash", 0.7, settings(colour=(255, 0, 0), duty=0.9)),
                         (255, 0, 0))

    def test_battery_is_green_when_full(self):
        r, g, b = colour_for("battery", 0.0, settings(battery=100))
        self.assertGreater(g, 200)
        self.assertLess(r, 60)

    def test_battery_is_red_when_empty(self):
        r, g, b = colour_for("battery", 0.0, settings(battery=0))
        self.assertGreater(r, 200)
        self.assertLess(g, 60)

    def test_battery_falls_back_to_manual_when_unknown(self):
        self.assertEqual(colour_for("battery", 0.0, settings(battery=None)),
                         (0, 170, 255))

    def test_unknown_mode_falls_back_to_manual(self):
        self.assertEqual(colour_for("nonsense", 0.3, settings()), (0, 170, 255))

    def test_every_mode_returns_valid_channels(self):
        for mode in MODES:
            for phase in (0.0, 0.33, 0.66, 0.99):
                for channel in colour_for(mode, phase, settings(battery=50)):
                    self.assertTrue(0 <= channel <= 255, "%s %s" % (mode, phase))


class TestEngineThread(unittest.TestCase):
    def test_writes_once_for_a_solid_colour(self):
        writes = []
        state = AppState()
        engine = Engine(state, writes.append, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()
        self.assertEqual(writes, [(10, 20, 30)],
                         "a solid colour must not be rewritten every frame")

    def test_writes_repeatedly_for_an_animated_mode(self):
        writes = []
        engine = Engine(AppState(), writes.append, interval=0.005)
        engine.set_mode("rainbow")
        engine.start()
        time.sleep(0.2)
        engine.stop()
        self.assertGreater(len(writes), 3)

    def test_publishes_colour_to_state(self):
        state = AppState()
        engine = Engine(state, lambda rgb: None, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((1, 2, 3))
        engine.start()
        time.sleep(0.1)
        engine.stop()
        self.assertEqual(state.snapshot()["rgb"], (1, 2, 3))

    def test_stop_joins_the_thread(self):
        engine = Engine(AppState(), lambda rgb: None, interval=0.005)
        engine.start()
        engine.stop()
        self.assertEqual(threading.active_count(), threading.active_count())
        self.assertFalse(engine.is_alive())

    def test_a_failing_writer_does_not_kill_the_thread(self):
        calls = []

        def writer(rgb):
            calls.append(rgb)
            raise RuntimeError("device went away")

        engine = Engine(AppState(), writer, interval=0.005)
        engine.set_mode("rainbow")
        engine.start()
        time.sleep(0.15)
        alive = engine.is_alive()
        engine.stop()
        self.assertTrue(alive, "the engine must survive a write failure")
        self.assertGreater(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_engine -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.engine'`.

- [ ] **Step 3: Implement**

`ps5led/engine.py`:

```python
"""Lighting modes.

The colour maths is a pure function so it can be tested without a thread and
without a controller. The thread only advances a phase and writes when the
result actually changed — a solid colour costs one write, not thirty a second.
"""

import threading
import time

MODES = ("manual", "rainbow", "wave", "flash", "battery")

_DEFAULT_COLOUR = (0, 170, 255)


def hsv_to_rgb(h, s, v):
    """HSV in [0, 1] to 8-bit RGB."""
    h = h % 1.0
    if s <= 0:
        level = int(v * 255)
        return (level, level, level)
    sector = int(h * 6.0)
    offset = h * 6.0 - sector
    p = v * (1.0 - s)
    q = v * (1.0 - s * offset)
    t = v * (1.0 - s * (1.0 - offset))
    table = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))
    return tuple(int(channel * 255) for channel in table[sector % 6])


def _scale(rgb, factor):
    return tuple(max(0, min(255, int(channel * factor))) for channel in rgb)


def colour_for(mode, phase, settings):
    """The colour this mode shows at ``phase`` in [0, 1)."""
    base = settings.get("colour") or _DEFAULT_COLOUR
    brightness = settings.get("brightness", 1.0)

    if mode == "rainbow":
        return hsv_to_rgb(phase, 1.0, brightness)
    if mode == "wave":
        import math
        factor = (math.sin(phase * 2 * math.pi) + 1.0) / 2.0
        return _scale(base, brightness * (0.15 + 0.85 * factor))
    if mode == "flash":
        duty = settings.get("duty", 0.5)
        return _scale(base, brightness) if phase < duty else (0, 0, 0)
    if mode == "battery":
        level = settings.get("battery")
        if level is not None:
            # 0 % red through 100 % green, along the hue circle's short arc.
            return hsv_to_rgb((level / 100.0) / 3.0, 1.0, brightness)
    return _scale(base, brightness)


class Engine(threading.Thread):
    """Drives ``write_colour`` at a fixed interval, only when the colour changed."""

    def __init__(self, state, write_colour, interval=1 / 30.0):
        threading.Thread.__init__(self, name="ps5led-engine", daemon=True)
        self._state = state
        self._write = write_colour
        self._interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._mode = "manual"
        self._settings = {"colour": _DEFAULT_COLOUR, "brightness": 1.0,
                          "duty": 0.5, "battery": None}
        self._speed = 1.0
        self._last_written = None

    def set_mode(self, mode):
        with self._lock:
            self._mode = mode

    def set_colour(self, rgb):
        with self._lock:
            self._settings["colour"] = tuple(rgb)

    def set_setting(self, key, value):
        with self._lock:
            self._settings[key] = value

    def set_speed(self, speed):
        with self._lock:
            self._speed = max(0.1, min(5.0, float(speed)))

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=2.0)

    def run(self):
        phase = 0.0
        while not self._stop.is_set():
            with self._lock:
                mode = self._mode
                settings = dict(self._settings)
                speed = self._speed
            rgb = colour_for(mode, phase, settings)
            if rgb != self._last_written:
                self._last_written = rgb
                self._state.update(rgb=rgb, mode=mode)
                try:
                    self._write(rgb)
                except Exception:
                    # A device that vanished is DeviceManager's problem to
                    # notice and recover from; the engine must keep running.
                    pass
            phase = (phase + self._interval * speed * 0.5) % 1.0
            self._stop.wait(self._interval)
```

Move `import math` to the top of the file with `threading` and `time`, and drop
`time` if the final implementation does not use it.

- [ ] **Step 4: Run and confirm passing**

```bash
python -m unittest tests.test_engine -v
```

Expected: 22 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/engine.py tests/test_engine.py
git commit -m "feat(engine): lighting modes with write-on-change"
```

---

### Task 9: Device manager and CLI

**Files:**
- Create: `ps5led/device.py`, `ps5led/cli.py`, `ps5led/__main__.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything above
- Produces: `DeviceManager(state)` with `start()`, `stop()`, `write_colour(rgb)`,
  `describe() -> dict`; `cli.main(argv=None) -> int`

`DeviceManager` owns the handle. Its reader thread reads with a 200 ms timeout so
it can notice a stop request; on `HidError` it closes, publishes
`connected=False`, and rescans every two seconds. On a fresh connection it reads
calibration — which is also what switches a Bluetooth DualSense into full
reports — then sends one setup packet, then whatever colour the engine last
produced.

`--doctor` prints what `describe()` returns plus the last write error. This is
the answer to the original bug report: a lightbar that does not respond now
explains itself instead of failing silently.

- [ ] **Step 1: Write the failing test**

`tests/test_device.py`:

```python
import unittest

from ps5led.device import DeviceManager, choose_device
from ps5led.state import AppState


class FakeInfo(object):
    def __init__(self, product_id, transport="usb", input_length=64,
                 output_length=48, feature_length=64):
        self.path = "\\\\?\\fake#%04x" % product_id
        self.vendor_id = 0x054C
        self.product_id = product_id
        self.product = "Fake %04x" % product_id
        self.transport = transport
        self.input_length = input_length
        self.output_length = output_length
        self.feature_length = feature_length


class TestChooseDevice(unittest.TestCase):
    def test_none_when_empty(self):
        self.assertIsNone(choose_device([]))

    def test_prefers_dualsense_over_dualshock(self):
        chosen = choose_device([FakeInfo(0x05C4), FakeInfo(0x0CE6)])
        self.assertEqual(chosen.product_id, 0x0CE6)

    def test_accepts_dualsense_edge(self):
        self.assertEqual(choose_device([FakeInfo(0x0DF2)]).product_id, 0x0DF2)

    def test_falls_back_to_dualshock(self):
        self.assertEqual(choose_device([FakeInfo(0x09CC)]).product_id, 0x09CC)

    def test_ignores_unrelated_sony_devices(self):
        self.assertIsNone(choose_device([FakeInfo(0x0000)]))

    def test_skips_interfaces_with_unknown_transport(self):
        self.assertIsNone(choose_device([FakeInfo(0x0CE6, transport="unknown")]))


class TestDescribe(unittest.TestCase):
    def test_reports_disconnected_before_start(self):
        info = DeviceManager(AppState()).describe()
        self.assertFalse(info["connected"])
        self.assertIsNone(info["product"])

    def test_write_without_a_device_records_an_error(self):
        manager = DeviceManager(AppState())
        manager.write_colour((1, 2, 3))
        self.assertIn("no device", manager.describe()["last_error"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_device -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.device'`.

- [ ] **Step 3: Implement**

`ps5led/device.py`:

```python
"""Owns the controller handle, the reader thread, and reconnection.

hid_win is imported inside functions on purpose: it is Windows-only and the CI
runner is Linux.
"""

import threading
import time

from . import dualsense as ds
from . import dualshock4 as ds4

RESCAN_SECONDS = 2.0
READ_TIMEOUT_MS = 200


def choose_device(infos):
    """Prefer a DualSense, then a DualShock 4; ignore anything else."""
    for wanted in (ds.PRODUCT_IDS, ds4.PRODUCT_IDS):
        for info in infos:
            if info.product_id in wanted and info.transport in ("usb", "bt"):
                return info
    return None


class DeviceManager(object):
    def __init__(self, state):
        self._state = state
        self._lock = threading.Lock()
        self._device = None
        self._info = None
        self._is_ds5 = False
        self._scales = None
        self._seq = 0
        self._last_error = None
        self._last_rgb = None
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ps5led-reader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._close()

    def describe(self):
        with self._lock:
            info = self._info
            return {
                "connected": self._device is not None,
                "product": info.product if info else None,
                "product_id": info.product_id if info else None,
                "transport": info.transport if info else None,
                "input_length": info.input_length if info else None,
                "output_length": info.output_length if info else None,
                "gyro_scales": self._scales,
                "last_error": self._last_error,
            }

    # -- writing -----------------------------------------------------------
    def write_colour(self, rgb):
        with self._lock:
            device, info, is_ds5 = self._device, self._info, self._is_ds5
            if device is None:
                self._last_error = "no device connected"
                return False
            self._seq = (self._seq + 1) & 0x0F
            seq = self._seq
        try:
            if is_ds5:
                packet = ds.build_output(info.transport, info.output_length, rgb=rgb, seq=seq)
            else:
                packet = ds4.build_output(info.transport, rgb)
            device.write(packet)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._drop()
            return False
        with self._lock:
            self._last_error = None
            self._last_rgb = tuple(rgb)
        return True

    # -- internals ---------------------------------------------------------
    def _close(self):
        with self._lock:
            device, self._device, self._info = self._device, None, None
            self._scales = None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        self._state.update(connected=False, transport=None, product=None)

    def _drop(self):
        self._close()

    def _connect(self):
        from .hid_win import HidDevice, enumerate_devices

        info = choose_device(enumerate_devices(ds.VENDOR_ID))
        if info is None:
            return False
        device = HidDevice.open(info.path)
        is_ds5 = info.product_id in ds.PRODUCT_IDS
        scales = None
        if is_ds5:
            # This read yields the gyro scale AND switches a Bluetooth DualSense
            # out of its reduced 10-byte report into the full 0x31 report.
            raw = device.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
            scales = ds.parse_calibration(raw) if raw else None
            # One setup packet per connection, or RGB is ignored while the
            # controller finishes its power-on animation.
            device.write(ds.build_output(info.transport, info.output_length,
                                         lightbar_setup=True, seq=0))
        with self._lock:
            self._device, self._info, self._is_ds5, self._scales = device, info, is_ds5, scales
            self._last_error = None
            last_rgb = self._last_rgb
        self._state.update(connected=True, transport=info.transport,
                           product=info.product,
                           gyro_scale=(scales[0] if scales else ds.DEFAULT_GYRO_SCALE))
        if last_rgb is not None:
            self.write_colour(last_rgb)
        return True

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                device = self._device
            if device is None:
                try:
                    if not self._connect():
                        self._stop.wait(RESCAN_SECONDS)
                        continue
                except Exception as exc:
                    with self._lock:
                        self._last_error = str(exc)
                    self._stop.wait(RESCAN_SECONDS)
                    continue
                with self._lock:
                    device = self._device
                if device is None:
                    continue
            try:
                data = device.read(timeout_ms=READ_TIMEOUT_MS)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self._drop()
                self._stop.wait(RESCAN_SECONDS)
                continue
            if not data:
                continue
            with self._lock:
                is_ds5, scales = self._is_ds5, self._scales
            if not is_ds5:
                continue
            sample = ds.parse_input(data)
            if sample is None:
                continue
            scale = scales[0] if scales else ds.DEFAULT_GYRO_SCALE
            self._state.update(
                battery=sample.battery_percent,
                charging=sample.charge_state in (1, 2),
                gyro=tuple(value * scale for value in sample.gyro_raw),
                accel=tuple(value / 8192.0 for value in sample.accel_raw),
                sensor_timestamp=sample.timestamp,
                buttons=sample.buttons,
                touch=sample.touch,
            )
```

`ps5led/cli.py`:

```python
"""Command line entry points."""

import argparse
import json
import platform
import sys
import time

from . import __version__
from .device import DeviceManager
from .engine import Engine
from .state import AppState


def _require_windows():
    if platform.system() != "Windows":
        sys.stderr.write("PS5 LED drives controllers on Windows only.\n")
        return False
    return True


def doctor():
    """Print what the app can see. This is what a silent failure looks like now."""
    if not _require_windows():
        return 2
    from .hid_win import enumerate_devices

    print("PS5 LED %s" % __version__)
    devices = enumerate_devices(0x054C)
    if not devices:
        print("\nNo Sony HID device found.")
        print("  - Is the controller connected by cable or paired over Bluetooth?")
        print("  - Another program (Steam, DS4Windows) may hold it exclusively.")
        return 1
    print("\nSony HID interfaces:")
    for info in devices:
        print("  %-32s pid=%#06x in=%-3d out=%-3d feat=%-3d transport=%s"
              % (info.product, info.product_id, info.input_length,
                 info.output_length, info.feature_length, info.transport))

    state = AppState()
    manager = DeviceManager(state)
    manager.start()
    time.sleep(1.5)
    print("\nengine view:")
    print(json.dumps(manager.describe(), indent=2, default=str))
    manager.stop()
    return 0


def run_background(state=None):
    if not _require_windows():
        return 2
    state = state or AppState()
    manager = DeviceManager(state)
    manager.start()
    engine = Engine(state, manager.write_colour)
    engine.start()
    print("PS5 LED running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        manager.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ps5led")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--doctor", action="store_true",
                        help="report what the app can see, and why it failed")
    parser.add_argument("--background", action="store_true",
                        help="run the engine with no window")
    args = parser.parse_args(argv)

    if args.doctor:
        return doctor()
    if args.background:
        return run_background()
    parser.print_help()
    return 0
```

`ps5led/__main__.py`:

```python
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the suite, then check the CLI against hardware**

```bash
python -m unittest discover -s tests -v
```

Expected: every test passes on Windows; on Linux the `hid_win` test skips.

```bash
python -m ps5led --doctor
```

Expected: the controller is listed, `connected: true`, `transport` correct,
`gyro_scales` near `0.061`, `last_error: null`.

```bash
python -m ps5led --background
```

Expected: the lightbar takes the default colour and holds it. Unplug the
controller — `--doctor` in another window should now report `connected: false`.
Plug it back in and within two seconds the colour returns without a restart.

- [ ] **Step 5: Wire the suite into CI and commit**

In `.github/workflows/ci.yml`, replace the `compileall` step's `run:` value with
`python -m compileall -q ps5led tests` and add a step after the ruff step:

```yaml
      - name: Unit tests
        run: python -m unittest discover -s tests -v
```

```bash
git add ps5led/device.py ps5led/cli.py ps5led/__main__.py tests/test_device.py .github/workflows/ci.yml
git commit -m "feat(device): connection lifecycle, reconnect, and --doctor"
```

---

## Self-review

**Spec coverage for Plan 1's scope (spec §6, §7, §16 stages 1–2):**

| Spec requirement | Task |
|---|---|
| CRC seeds 0xA1/0xA2/0xA3 | 1 |
| DS5 output, USB and Bluetooth, setup packet | 2 |
| DS5 input offsets, battery, touch, Bluetooth CRC check | 3 |
| DS5 calibration and the Bluetooth report switch | 3, 9 |
| DS4 USB and Bluetooth, `hw_control = 0xC0` | 4 |
| `WriteFile` not `HidD_SetOutputReport` | 5 |
| Overlapped IO with timeouts | 5 |
| Length from `OutputReportByteLength` | 5, 2 |
| `argtypes`/`restype` everywhere | 5 |
| Transport from `InputReportByteLength` | 5 |
| Live verification on both transports | 6 |
| `AppState` with lock and `seq` | 7 |
| Lighting modes at 30 Hz, write-on-change | 8 |
| Reader thread, reconnect | 9 |
| `--doctor` | 9 |
| `--background` | 9 |
| Unit tests in CI | 9 |

Deferred to Plan 2 by design: `bridge.py`, `launcher.py`, the web layer, and the
model pipeline. Deferred to Plan 3: `config.py` migration, `tray.py` and
`instance.py` ports, the installer, the PyInstaller spec, and `release.yml`. The
engine of Plan 1 runs standalone without them.

**Placeholder scan:** none. Every step carries the code it needs.

**Type consistency:** `TRANSPORT_USB`/`TRANSPORT_BT` are the string constants
`"usb"`/`"bt"` in `dualsense`, `dualshock4` and `hid_win`, and `DeviceInfo.transport`
carries the same values, so `info.transport` feeds `build_output` directly.
`build_output` has different signatures in the two protocol modules — DS5 takes
`(transport, length, ...)` because Windows dictates its length, DS4 takes
`(transport, rgb, blink)` because its sizes are fixed — and `DeviceManager.write_colour`
is the only caller of both, branching on `_is_ds5`. `colour_for` and `Engine`
share the settings keys `colour`, `brightness`, `duty`, `battery`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-07-engine-hid-backend.md`. Two execution options:

1. **Subagent-driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline execution** — tasks run in this session with checkpoints for review.

Task 6 is a hard gate either way: it needs the controller in hand, on both USB
and Bluetooth, and nothing after it is worth building until it passes.

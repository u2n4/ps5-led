"""DualSense (DS5) HID protocol.

Report layouts are taken from drivers/hid/hid-playstation.c in the Linux
kernel. Offsets named "common" below are relative to the start of
``struct dualsense_output_report_common``, which sits at buffer index 1 over
USB and index 3 over Bluetooth.

This module is pure: bytes in, bytes out, no I/O and no Windows imports, so it
runs under CI on Linux.
"""

import struct
from typing import NamedTuple, Optional, Tuple

from .crc import INPUT_SEED, OUTPUT_SEED, append_crc32, check_crc32

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

"""DualSense (DS5) HID protocol.

Report layouts are taken from drivers/hid/hid-playstation.c in the Linux
kernel. Offsets named "common" below are relative to the start of
``struct dualsense_output_report_common``, which sits at buffer index 1 over
USB and index 3 over Bluetooth.

This module is pure: bytes in, bytes out, no I/O and no Windows imports, so it
runs under CI on Linux.
"""

from .crc import OUTPUT_SEED, append_crc32

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

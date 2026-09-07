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

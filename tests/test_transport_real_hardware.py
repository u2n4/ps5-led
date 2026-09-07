"""Regressions for the two Bluetooth failures real hardware found.

Both were invisible to 147 tests because every fixture used the numbers the plan
assumed rather than the numbers Windows reports. These pin the measured values,
captured 2026-09-07 with a DualSense and a DualShock 4 both paired over
Bluetooth while the DualSense was also on USB:

    DualSense  USB : in=64  out=48   path carries vid_054c&pid_0ce6&mi_03
    DualSense  BT  : in=78  out=547  path carries the 00001124 HID-over-BT UUID
    DualShock4 BT  : in=547 out=547  path carries the 00001124 HID-over-BT UUID

The exact paths are pinned as constants below.
"""

import platform
import unittest

from ps5led import dualsense as ds
from ps5led.device import DeviceManager, choose_device

USB_PATH = r"\\?\hid#vid_054c&pid_0ce6&mi_03#7&fe98350&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"
BT_DS5_PATH = r"\\?\hid#{00001124-0000-1000-8000-00805f9b34fb}_vid&0002054c_pid&0ce6#8&fbb7b48&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"
BT_DS4_PATH = r"\\?\hid#{00001124-0000-1000-8000-00805f9b34fb}_vid&0002054c_pid&09cc#8&187c1321&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"


class Info(object):
    """Stands in for hid_win.DeviceInfo without needing Windows."""

    def __init__(self, path, product_id, input_length, output_length, transport):
        self.path = path
        self.vendor_id = 0x054C
        self.product_id = product_id
        self.product = "stand-in"
        self.input_length = input_length
        self.output_length = output_length
        self.feature_length = 64
        self.transport = transport


DS5_USB = Info(USB_PATH, 0x0CE6, 64, 48, "usb")
DS5_BT = Info(BT_DS5_PATH, 0x0CE6, 78, 547, "bt")
DS4_BT = Info(BT_DS4_PATH, 0x09CC, 547, 547, "bt")


@unittest.skipUnless(platform.system() == "Windows", "hid_win is Windows-only")
class TestTransportComesFromThePath(unittest.TestCase):
    """Report length is not a transport discriminator; the interface path is."""

    def setUp(self):
        from ps5led.hid_win import transport_for_path

        self.transport_for_path = transport_for_path

    def test_usb_path(self):
        self.assertEqual(self.transport_for_path(USB_PATH), "usb")

    def test_bluetooth_dualsense_path(self):
        self.assertEqual(self.transport_for_path(BT_DS5_PATH), "bt")

    def test_bluetooth_dualshock4_path(self):
        # in=547 used to make this "unknown", so choose_device dropped the
        # controller silently and the lightbar was never touched.
        self.assertEqual(self.transport_for_path(BT_DS4_PATH), "bt")

    def test_case_is_irrelevant(self):
        self.assertEqual(self.transport_for_path(BT_DS5_PATH.upper()), "bt")

    def test_missing_path_does_not_raise(self):
        self.assertEqual(self.transport_for_path(None), "usb")


class TestBluetoothDeviceIsAccepted(unittest.TestCase):
    def test_dualshock4_over_bluetooth_is_no_longer_dropped(self):
        self.assertIsNotNone(choose_device([DS4_BT]))

    def test_dualsense_over_bluetooth_is_accepted(self):
        self.assertIs(choose_device([DS5_BT]), DS5_BT)

    def test_dualsense_still_wins_over_dualshock4(self):
        self.assertIs(choose_device([DS4_BT, DS5_BT]), DS5_BT)


class TestBuildsAtProtocolLengthNotWindowsBufferSize(unittest.TestCase):
    def test_bluetooth_uses_the_protocol_length(self):
        self.assertEqual(DeviceManager._ds5_output_length(DS5_BT), ds.BT_OUTPUT_SIZE)

    def test_usb_uses_what_windows_reported(self):
        self.assertEqual(DeviceManager._ds5_output_length(DS5_USB), 48)

    def test_colour_packet_over_bluetooth_builds_at_78(self):
        # Before the fix this raised "Bluetooth reports are 78 bytes, got 547".
        packet = DeviceManager._build_packet(DS5_BT, True, (1, 2, 3), 1)
        self.assertEqual(len(packet), ds.BT_OUTPUT_SIZE)
        self.assertEqual(packet[0], ds.OUTPUT_REPORT_BT)

    def test_setup_packet_over_bluetooth_does_not_raise(self):
        # _connect sends this FIRST, so it is where Bluetooth actually died.
        packet = ds.build_output(DS5_BT.transport,
                                 DeviceManager._ds5_output_length(DS5_BT),
                                 lightbar_setup=True, seq=0)
        self.assertEqual(len(packet), ds.BT_OUTPUT_SIZE)

    def test_colour_packet_over_usb_still_builds_at_the_reported_length(self):
        packet = DeviceManager._build_packet(DS5_USB, True, (1, 2, 3), 1)
        self.assertEqual(len(packet), 48)

    def test_dualshock4_over_bluetooth_builds_its_own_78(self):
        packet = DeviceManager._build_packet(DS4_BT, False, (1, 2, 3), 0)
        self.assertEqual(len(packet), 78)
        self.assertEqual(packet[0], 0x11)
        self.assertEqual(packet[1], 0xC0, "hw_control must stay HID|CRC32")


if __name__ == "__main__":
    unittest.main()

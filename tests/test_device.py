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

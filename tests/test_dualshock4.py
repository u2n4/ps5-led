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

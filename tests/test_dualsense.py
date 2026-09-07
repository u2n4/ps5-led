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

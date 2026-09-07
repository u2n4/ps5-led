import struct
import unittest

from ps5led import dualsense as ds
from ps5led.crc import INPUT_SEED, OUTPUT_SEED, append_crc32, check_crc32


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

    def test_battery_full_step_saturates_at_a_hundred(self):
        state = ds.parse_input(make_usb_input(status=0x2A))
        self.assertEqual(state.battery_percent, 100)
        self.assertEqual(state.charge_state, 0x2)

    def test_battery_step_reads_as_the_middle_of_its_band(self):
        # hid-playstation: min(capacity * 10 + 5, 100). The controller reports a
        # 0..10 step, so step 5 means "somewhere in 50-59 %", and the kernel
        # answers with the middle of that band rather than its floor.
        self.assertEqual(ds.parse_input(make_usb_input(status=0x05)).battery_percent, 55)
        self.assertEqual(ds.parse_input(make_usb_input(status=0x00)).battery_percent, 5)

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
    def make(bias=(0, 0, 0), plus=(2000, 2000, 2000), minus=(-2000, -2000, -2000),
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
        # speed 1024+1024 = 2048 over |2000-0| + |-2000-0| = 4000
        scales = ds.parse_calibration(self.make())
        for scale in scales:
            self.assertAlmostEqual(scale, 2048.0 / 4000.0, places=9)

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


if __name__ == "__main__":
    unittest.main()

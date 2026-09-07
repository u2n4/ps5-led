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

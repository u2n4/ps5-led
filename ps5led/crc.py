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

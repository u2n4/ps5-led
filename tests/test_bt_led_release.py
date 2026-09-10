"""Bluetooth must release the LEDs from the wireless firmware before painting.

Over Bluetooth the DualSense's wireless firmware owns the lightbar. It runs
the connect animation and then keeps painting its own colour; a host that
only writes RGB fights it and the bar flickers -- the report from the field.
The controller honours a RELEASE_LEDS pulse (valid_flag1 bit 3) only once
its sensor timestamp shows the connection animation is over. SDL waits for
BT_CONNECTION_COMPLETE_TIMESTAMP and then pulses once; so does ps5led.

USB has no wireless firmware in the loop and keeps the LIGHT_OUT setup.
"""
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_native_backend as harness  # noqa: E402
from ps5led import device as device_mod  # noqa: E402
from ps5led import dualsense as ds  # noqa: E402
from ps5led.device import DeviceManager, BOOT_COLOUR_WRITES  # noqa: E402

BT_COMMON = 3   # common block offset in report 0x31
USB_COMMON = 1  # common block offset in report 0x02
FLAG1, FLAG2, SETUP = 1, 38, 41
usb_input_report = harness.input_report


def bt_input_report(timestamp):
    """A real Bluetooth 0x31 input report (78 bytes, body at 2, CRC32 at the end)."""
    data = bytearray(ds.BT_INPUT_SIZE)
    data[0] = ds.INPUT_REPORT_BT
    struct.pack_into("<I", data, 2 + 27, timestamp)
    ds.append_crc32(ds.INPUT_SEED, data)
    return bytes(data)


class ReportingDevice(harness.FakeDevice):
    """FakeDevice that answers reads from a queue of input reports, then None."""
    def __init__(self, reports=()):
        super().__init__()
        self.reports = list(reports)
        self.reads = 0
        self.reads_before_first_write = None

    def read(self, timeout_ms):
        self.reads += 1
        return self.reports.pop(0) if self.reports else None

    def write(self, packet):
        if self.reads_before_first_write is None:
            self.reads_before_first_write = self.reads
        super().write(packet)


class BluetoothLedReleaseTests(unittest.TestCase):
    def test_bluetooth_releases_leds_once_before_the_first_colour(self):
        sink = harness.Sink(); manager = DeviceManager(sink)
        device = ReportingDevice([usb_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP)])
        self.assertTrue(harness.connect(manager, device, "bt"))
        release, colours = device.writes[0], device.writes[1:]
        self.assertEqual(release[0], ds.OUTPUT_REPORT_BT)
        self.assertEqual(release[BT_COMMON + FLAG1], ds.FLAG1_RELEASE_LEDS)
        self.assertEqual(release[BT_COMMON + FLAG2], 0, "no LIGHT_OUT setup on Bluetooth")
        self.assertTrue(ds.check_crc32(ds.OUTPUT_SEED, release))
        self.assertEqual(len(colours), BOOT_COLOUR_WRITES)
        for packet in colours:
            self.assertEqual(packet[BT_COMMON + FLAG1], ds.FLAG1_LIGHTBAR)
            self.assertEqual(packet[BT_COMMON + FLAG1] & ds.FLAG1_RELEASE_LEDS, 0,
                             "the release is a pulse, not a standing flag")

    def test_release_waits_for_the_connection_animation_to_finish(self):
        sink = harness.Sink(); manager = DeviceManager(sink)
        early = ds.BT_CONNECTION_COMPLETE_TIMESTAMP - 1
        device = ReportingDevice([usb_input_report(1_000_000), usb_input_report(early),
                                  usb_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP)])
        self.assertTrue(harness.connect(manager, device, "bt"))
        self.assertEqual(device.reads_before_first_write, 3,
                         "released only once the timestamp reached the threshold")

    def test_gate_reads_real_bluetooth_framing_and_skips_what_it_cannot_parse(self):
        # The reduced 10-byte report (calibration not yet read), a 0x31 report
        # with a bad CRC, and a 0x31 report still inside the animation are all
        # skipped; the first genuine settled 0x31 report opens the gate.
        sink = harness.Sink(); manager = DeviceManager(sink)
        corrupt = bytearray(bt_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP)); corrupt[-1] ^= 0xFF
        device = ReportingDevice([bytes(10), bytes(corrupt),
                                  bt_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP - 1),
                                  bt_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP)])
        self.assertTrue(harness.connect(manager, device, "bt"))
        self.assertEqual(device.reads_before_first_write, 4)
        self.assertEqual(device.writes[0][BT_COMMON + FLAG1], ds.FLAG1_RELEASE_LEDS)

    def test_stop_during_the_gate_writes_nothing_and_closes_the_handle(self):
        sink = harness.Sink(); manager = DeviceManager(sink)
        device = ReportingDevice([])
        def read(timeout_ms):
            manager._stop.set()
            return None
        device.read = read
        self.assertFalse(harness.connect(manager, device, "bt"))
        self.assertEqual(device.writes, [], "a cancelled connect must not touch the lightbar")
        self.assertTrue(device.closed)
        self.assertFalse(sink.values.get("connected", False))

    def test_release_is_sent_anyway_when_the_pad_never_reports(self):
        # A pad that never delivers an input report must not stall the connect.
        sink = harness.Sink(); manager = DeviceManager(sink)
        device = ReportingDevice([])
        with patch.object(device_mod, "BT_RELEASE_WAIT_SECONDS", 0.05):
            self.assertTrue(harness.connect(manager, device, "bt"))
        self.assertEqual(device.writes[0][BT_COMMON + FLAG1], ds.FLAG1_RELEASE_LEDS)
        self.assertGreater(device.reads, 0)

    def test_usb_keeps_the_light_out_setup_and_never_releases(self):
        sink = harness.Sink(); manager = DeviceManager(sink)
        device = ReportingDevice([usb_input_report(ds.BT_CONNECTION_COMPLETE_TIMESTAMP)])
        self.assertTrue(harness.connect(manager, device, "usb"))
        setup = device.writes[0]
        self.assertEqual(setup[0], ds.OUTPUT_REPORT_USB)
        self.assertEqual(setup[USB_COMMON + FLAG2], ds.FLAG2_LIGHTBAR_SETUP)
        self.assertEqual(setup[USB_COMMON + SETUP], ds.LIGHTBAR_SETUP_LIGHT_OUT)
        for packet in device.writes:
            self.assertEqual(packet[USB_COMMON + FLAG1] & ds.FLAG1_RELEASE_LEDS, 0)
        self.assertEqual(device.reads, 0, "USB does not wait on input reports")

    def test_build_output_release_flag(self):
        packet = ds.build_output(ds.TRANSPORT_BT, ds.BT_OUTPUT_SIZE, release_leds=True, seq=5)
        self.assertEqual(packet[1], 5 << 4)
        self.assertEqual(packet[2], 0x10)
        self.assertEqual(packet[BT_COMMON + FLAG1], ds.FLAG1_RELEASE_LEDS)
        self.assertEqual(packet[BT_COMMON + 44:BT_COMMON + 47], b"\x00\x00\x00")
        self.assertTrue(ds.check_crc32(ds.OUTPUT_SEED, packet))


if __name__ == "__main__":
    unittest.main()

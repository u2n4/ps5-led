"""The reader must notice a device that goes quiet without erroring.

Real hardware, 2026-09-07: unplugging the DualSense while the engine ran left
ReadFile accepting a request that never completed. Every read returned None as
an ordinary timeout, `if not data: continue` spun the loop on a dead handle, and
_drop() was never reached — the colours stopped and only restarting the process
brought them back. Windows reported no error at any point.

A connected controller streams about 253 input reports a second whether or not
anyone touches it, so sustained silence is the liveness signal.
"""

import sys
import threading
import time
import types
import unittest

from ps5led import device as device_mod
from ps5led.device import DeviceManager, READ_TIMEOUT_MS, SILENT_READS_BEFORE_DROP
from ps5led.state import AppState


class FakeInfo(object):
    def __init__(self):
        self.path = r"\\?\fake"
        self.vendor_id = 0x054C
        self.product_id = 0x0CE6
        self.product = "Fake DualSense"
        self.input_length = 64
        self.output_length = 48
        self.feature_length = 64
        self.transport = "usb"


class SilentDevice(object):
    """Opens fine, writes fine, and never returns a report — the observed failure."""

    def __init__(self):
        self.closed = 0
        self.reads = 0
        self.writes = 0

    def read(self, timeout_ms=1000):
        self.reads += 1
        return None

    def write(self, data):
        self.writes += 1
        return len(data)

    def get_feature(self, report_id, length):
        buf = bytearray(length)
        buf[0] = report_id
        return bytes(buf)

    def close(self):
        self.closed += 1


class TestSilenceIsTreatedAsLoss(unittest.TestCase):
    def setUp(self):
        self.opened = []
        fake_hid = types.ModuleType("ps5led.hid_win")
        fake_hid.enumerate_devices = lambda vendor_id=None: [FakeInfo()]

        def _open(path):
            dev = SilentDevice()
            self.opened.append(dev)
            return dev

        fake_hid.HidDevice = types.SimpleNamespace(open=staticmethod(_open))
        fake_hid.HidError = OSError
        self._saved = sys.modules.get("ps5led.hid_win")
        sys.modules["ps5led.hid_win"] = fake_hid
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            sys.modules.pop("ps5led.hid_win", None)
        else:
            sys.modules["ps5led.hid_win"] = self._saved

    def test_threshold_is_a_few_seconds_not_forever(self):
        seconds = SILENT_READS_BEFORE_DROP * READ_TIMEOUT_MS / 1000.0
        self.assertGreaterEqual(seconds, 1.0, "too eager: a brief stall would drop a live device")
        self.assertLessEqual(seconds, 10.0, "too patient: the user sees a dead lightbar this long")

    def test_a_silent_device_is_dropped_and_reconnected(self):
        state = AppState()
        manager = DeviceManager(state)
        manager.start()
        try:
            # One drop needs SILENT_READS_BEFORE_DROP timeouts plus RESCAN_SECONDS
            # before the next connect. Wait long enough for a second open.
            deadline = time.time() + 25
            while time.time() < deadline and len(self.opened) < 2:
                time.sleep(0.1)
        finally:
            manager.stop()

        self.assertGreaterEqual(
            len(self.opened), 2,
            "the reader never dropped the silent device, so it never reconnected")
        self.assertGreaterEqual(self.opened[0].closed, 1, "the dead handle was not closed")
        self.assertIn("no input report", (manager.describe()["last_error"] or "")
                      + (state.snapshot().get("last_error") or ""),
                      "the drop reason should say the device went quiet")


class TestCounterResets(unittest.TestCase):
    def test_constant_is_exported_for_the_reader_loop(self):
        self.assertIsInstance(SILENT_READS_BEFORE_DROP, int)
        self.assertGreater(SILENT_READS_BEFORE_DROP, 1)
        self.assertTrue(hasattr(device_mod, "READ_TIMEOUT_MS"))


if __name__ == "__main__":
    unittest.main()

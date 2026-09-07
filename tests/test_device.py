import sys
import time
import types
import unittest

import ps5led
from ps5led import dualsense as ds
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


class FakeDevice(object):
    """Stands in for HidDevice, with no Win32 handles behind it.

    ``write_errors`` is consumed one entry per write(): None lets the write
    through, an exception instance is raised instead. Every write also records
    whether DeviceManager had already published this device at that moment,
    which is how the "resend before publish" ordering is checked.
    """

    def __init__(self, manager=None, write_errors=(), read_error=None,
                 on_get_feature=None):
        self.manager = manager
        self.writes = []
        self.published_at_write = []
        self.closed = 0
        self.get_feature_calls = 0
        self._write_errors = list(write_errors)
        self._read_error = read_error
        self._on_get_feature = on_get_feature

    def get_feature(self, report_id, length):
        self.get_feature_calls += 1
        if self._on_get_feature is not None:
            self._on_get_feature()
        return None

    def write(self, packet):
        self.published_at_write.append(
            self.manager is not None and self.manager._device is not None)
        error = self._write_errors.pop(0) if self._write_errors else None
        if error is not None:
            raise error
        self.writes.append(bytes(packet))
        return len(packet)

    def read(self, timeout_ms=0):
        if self._read_error is not None:
            raise self._read_error
        time.sleep(0.01)
        return b""

    def close(self):
        self.closed += 1


def install_fake_hid(test, infos, factory):
    """Point device.py's function-local ``from .hid_win import ...`` at a fake.

    hid_win is imported inside _connect so the Windows-only module never loads
    under CI. That same indirection is what makes the connection path testable
    without hardware: a stand-in module in sys.modules is what the import finds.
    """
    module = types.ModuleType("ps5led.hid_win")
    module.enumerate_devices = lambda vendor_id=None: list(infos)

    class _HidDevice(object):
        @staticmethod
        def open(path):
            return factory(path)

    module.HidDevice = _HidDevice

    missing = object()
    saved_module = sys.modules.get("ps5led.hid_win", missing)
    saved_attr = getattr(ps5led, "hid_win", missing)

    def restore():
        if saved_module is missing:
            sys.modules.pop("ps5led.hid_win", None)
        else:
            sys.modules["ps5led.hid_win"] = saved_module
        if saved_attr is missing:
            if hasattr(ps5led, "hid_win"):
                delattr(ps5led, "hid_win")
        else:
            setattr(ps5led, "hid_win", saved_attr)

    test.addCleanup(restore)
    sys.modules["ps5led.hid_win"] = module
    ps5led.hid_win = module
    return module


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


class TestConnectHandleLifetime(unittest.TestCase):
    def test_a_failure_after_open_closes_the_device(self):
        """The setup write is exactly where a sleeping Bluetooth pad raises.

        Without a close on that path the Win32 file handle and the instance's
        two event handles are unreachable forever -- and the reader retries the
        leak every RESCAN_SECONDS for as long as the app runs.
        """
        device = FakeDevice(write_errors=[RuntimeError("write timed out")])
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())

        with self.assertRaises(RuntimeError):
            manager._connect()

        self.assertEqual(device.closed, 1)
        self.assertIsNone(manager._device)
        self.assertFalse(manager.describe()["connected"])

    def test_a_stop_during_connect_closes_instead_of_publishing(self):
        """stop() has to be a barrier: nothing may go live behind its back."""
        state = AppState()
        manager = DeviceManager(state)
        device = FakeDevice(on_get_feature=manager._stop.set)
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)

        self.assertFalse(manager._connect())

        self.assertEqual(device.closed, 1)
        self.assertIsNone(manager._device)
        self.assertFalse(manager.describe()["connected"])
        # ... and AppState must not be told a stopped manager holds a pad.
        self.assertFalse(state.snapshot().get("connected", False))


class TestWriteFailureRecovery(unittest.TestCase):
    def _connected_manager(self, device):
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        return manager

    def test_last_rgb_survives_a_failed_write(self):
        """The colour recorded must be the newest one asked for, not the last
        one that reached the wire.

        write_colour returns False rather than raising, so Engine advances its
        own _last_written and will never re-issue the colour. The reconnect
        resend is the only recovery path there is, and it can only resend what
        _last_rgb holds -- so recording it on success alone would strand the
        lightbar on a stale colour with nothing left to notice.
        """
        device = FakeDevice(write_errors=[None, None, RuntimeError("write timed out")])
        manager = self._connected_manager(device)
        self.assertTrue(manager.write_colour((1, 2, 3)))

        self.assertFalse(manager.write_colour((9, 8, 7)))

        self.assertEqual(manager._last_rgb, (9, 8, 7))
        self.assertEqual(manager.describe()["last_write_error"], "write timed out")
        self.assertEqual(device.closed, 1)
        self.assertIsNone(manager._device)

        # ... and the reconnect must put that newest colour on the device.
        replacement = FakeDevice()
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: replacement)
        self.assertTrue(manager._connect())
        self.assertEqual(replacement.writes[-1],
                         ds.build_output("usb", 48, rgb=(9, 8, 7)))
        self.assertNotEqual(replacement.writes[-1],
                            ds.build_output("usb", 48, rgb=(1, 2, 3)))

    def test_resend_is_written_before_the_device_is_published(self):
        """HidDevice allows one thread inside write() at a time.

        Publishing first lets the engine thread into write() while the resend
        is still in flight -- the loser cancels its own healthy write and tears
        down the connection that was just built -- and lets a newer colour
        arriving in that window be overwritten by this older one.
        """
        manager = DeviceManager(AppState())
        device = FakeDevice(manager=manager)
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager.write_colour((4, 5, 6))  # no device yet: records the intent

        self.assertTrue(manager._connect())

        self.assertEqual(len(device.writes), 2)  # setup packet, then the resend
        self.assertEqual(device.published_at_write, [False, False])
        self.assertEqual(device.writes[-1], ds.build_output("usb", 48, rgb=(4, 5, 6)))


class TestErrorProvenance(unittest.TestCase):
    def test_a_read_failure_never_becomes_a_write_error(self):
        """One field with three writers told the user nothing.

        A write failure used to be overwritten by the reader's downstream
        "device is closed" within milliseconds and then cleared outright by the
        next reconnect, so --doctor printed last_error: null on a controller
        that had been failing every write.
        """
        install_fake_hid(
            self, [FakeInfo(0x0CE6)],
            lambda path: FakeDevice(read_error=RuntimeError("device is closed")))
        manager = DeviceManager(AppState())
        manager.start()
        try:
            deadline = time.monotonic() + 3.0
            while (manager.describe()["last_error"] is None
                   and time.monotonic() < deadline):
                time.sleep(0.01)
            view = manager.describe()
        finally:
            manager.stop()

        self.assertEqual(view["last_error"], "device is closed")
        self.assertIsNone(view["last_write_error"])


class TestStartIsIdempotent(unittest.TestCase):
    def test_a_second_start_does_not_orphan_the_first_reader(self):
        install_fake_hid(self, [], lambda path: FakeDevice())
        manager = DeviceManager(AppState())
        manager.start()
        first = manager._thread
        try:
            manager.start()
            self.assertIs(manager._thread, first)
        finally:
            manager.stop()
        self.assertFalse(first.is_alive())


if __name__ == "__main__":
    unittest.main()

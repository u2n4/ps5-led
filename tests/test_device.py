import struct
import sys
import time
import types
import unittest

import ps5led
from ps5led import dualsense as ds
from ps5led import dualshock4 as ds4
from ps5led.device import (
    BOOT_COLOUR_WRITES,
    DEFAULT_RGB,
    DeviceManager,
    choose_device,
)
from ps5led.engine import colour_for
from ps5led.state import AppState

# A DualSense connect writes one setup packet then repeats the colour across the
# boot-animation window. Fixtures that queue per-write outcomes must skip these
# or their indices silently shift the day BOOT_COLOUR_WRITES changes - which is
# exactly how three tests broke when it went from 1 to 3.
DS5_CONNECT_WRITES = 1 + BOOT_COLOUR_WRITES
DS4_CONNECT_WRITES = BOOT_COLOUR_WRITES


def calibration_blob(speed=2048, span=16384):
    """A feature-report payload ``parse_calibration`` accepts.

    Zero bias, symmetric span and a speed of ``speed`` give every axis a scale of
    speed / (2 * span) = 0.0625 deg/s per LSB, comfortably inside the plausible
    band. The real controller answers with something very close to this; a fake
    that answered None would make every connect in this file record a
    calibration failure it was never meant to be testing.
    """
    data = bytearray(ds.CALIBRATION_SIZE)
    data[0] = ds.FEATURE_CALIBRATION

    def put(offset, value):
        struct.pack_into("<h", data, 1 + offset, value)

    for axis in range(3):
        put(axis * 2, 0)                # bias
        put(6 + axis * 4, span)         # positive extreme
        put(8 + axis * 4, -span)        # negative extreme
    put(18, speed // 2)
    put(20, speed - speed // 2)
    return bytes(data)


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
                 on_get_feature=None, feature=None, feature_error=None,
                 on_write=None):
        self.manager = manager
        self.writes = []
        self.published_at_write = []
        self.closed = 0
        self.get_feature_calls = 0
        # HidDevice's own field. A fake without it hides the seam --
        # _connect reads device.last_error to explain a refused calibration.
        self.last_error = None
        self._write_errors = list(write_errors)
        self._read_error = read_error
        self._on_get_feature = on_get_feature
        # Called with the 0-based index of the write about to happen, before
        # write_errors is consulted. Lets a test land another thread's work in
        # an exact window without a real thread and without a sleep.
        self._on_write = on_write
        # None means "answer with a payload parse_calibration accepts", which
        # is what a healthy controller does. Pass feature_error to model a
        # refusal (get_feature returns None and leaves last_error behind), or
        # feature=<bytes> to model a report that arrives and does not decode.
        self._feature = calibration_blob() if feature is None else feature
        self._feature_error = feature_error

    def get_feature(self, report_id, length):
        self.get_feature_calls += 1
        if self._on_get_feature is not None:
            self._on_get_feature()
        if self._feature_error is not None:
            self.last_error = self._feature_error
            return None
        return self._feature

    def write(self, packet):
        self.published_at_write.append(
            self.manager is not None and self.manager._device is not None)
        if self._on_write is not None:
            self._on_write(len(self.published_at_write) - 1)
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


class TestConnectLightsTheBar(unittest.TestCase):
    """The setup packet is LIGHTBAR_SETUP_LIGHT_OUT: it leaves the bar dark.

    _connect used to send it and then write a colour only if some caller had
    already asked for one. --doctor never asks for one, so running the
    diagnostic on a controller whose light had stopped working printed
    "connected: true", exited 0, and turned the light off -- the exact silent
    failure this branch exists to end, re-entered through the tool built to end
    it. The Linux driver has the same two-step and never leaves the gap:
    dualsense_probe() calls dualsense_reset_leds() and then
    dualsense_set_lightbar() on the very next line.
    """

    def _connect_with(self, device, info=None):
        install_fake_hid(self, [info or FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        return manager

    def test_a_connect_with_no_colour_requested_still_writes_one(self):
        device = FakeDevice()
        self._connect_with(device)

        # One setup packet, then the colour repeated across the boot-animation
        # window. A controller powered on a moment ago ignores RGB until that
        # animation ends, which is why a single write was not enough: on real
        # hardware over Bluetooth only the LAST of four colours ever appeared.
        self.assertEqual(len(device.writes), 1 + BOOT_COLOUR_WRITES)
        self.assertEqual(device.writes[0],
                         ds.build_output("usb", 48, lightbar_setup=True, seq=0))
        for i, packet in enumerate(device.writes[1:], start=1):
            self.assertEqual(packet, ds.build_output("usb", 48, rgb=DEFAULT_RGB, seq=i),
                             "colour write %d should carry the default colour" % i)

    def test_every_boot_window_write_carries_a_fresh_sequence_number(self):
        # Bluetooth only: USB output reports have no sequence byte at all, so
        # this has to run on a BT interface or it reads valid_flag1 and sees
        # zeroes. A repeat that reused seq would be discarded by the controller
        # and the repeats would buy nothing.
        device = FakeDevice()
        self._connect_with(device, FakeInfo(0x0CE6, transport="bt",
                                            input_length=78, output_length=547))
        seqs = [p[1] >> 4 for p in device.writes[1:]]
        self.assertEqual(len(seqs), BOOT_COLOUR_WRITES)
        self.assertEqual(len(set(seqs)), len(seqs), "sequence numbers repeated: %s" % seqs)

    def test_the_boot_window_builds_bluetooth_packets_at_the_protocol_length(self):
        # The 547 above is what Windows really reports for a DualSense on
        # Bluetooth; feeding it to build_output is what used to raise.
        device = FakeDevice()
        self._connect_with(device, FakeInfo(0x0CE6, transport="bt",
                                            input_length=78, output_length=547))
        for packet in device.writes:
            self.assertEqual(len(packet), ds.BT_OUTPUT_SIZE)

    def test_the_default_never_overrides_a_colour_already_asked_for(self):
        device = FakeDevice()
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        manager.write_colour((1, 2, 3))  # no device yet: records the intent

        self.assertTrue(manager._connect())

        self.assertEqual(device.writes[-1], ds.build_output("usb", 48, rgb=(1, 2, 3), seq=1))

    def test_a_dualshock4_connect_also_ends_lit(self):
        # No setup packet on a DS4, so there is no light-out to undo -- but the
        # rule is the same either way: a connected controller shows a colour.
        device = FakeDevice()
        self._connect_with(device, FakeInfo(0x09CC))

        self.assertEqual(device.writes,
                         [ds4.build_output("usb", DEFAULT_RGB)] * BOOT_COLOUR_WRITES,
                         "a DS4 gets the same boot-window repeats, minus the setup packet")

    def test_the_engine_default_matches_the_connect_default(self):
        # If these ever diverged, every connection would light the bar in one
        # colour and the engine's first tick would immediately change it to
        # another -- a visible flash on every reconnect.
        self.assertEqual(colour_for("manual", 0.0, {}), DEFAULT_RGB)


class TestCalibrationDiagnostics(unittest.TestCase):
    """The calibration read is what switches a Bluetooth DualSense out of its
    reduced report. Its failure is the most diagnostic event on the transport
    nobody has tested yet, and --doctor has to be able to name it -- _connect
    used to drop both the Win32 reason and the fact that a report had arrived
    and failed to decode.
    """

    def _connect_with(self, device):
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        return manager

    def test_a_refused_read_carries_the_devices_own_reason(self):
        device = FakeDevice(feature_error="IOCTL_HID_GET_FEATURE(0x5) failed: "
                                          "Win32 error 31")
        view = self._connect_with(device).describe()

        self.assertTrue(view["connected"])
        self.assertIsNone(view["gyro_scales"])
        self.assertIn("refused", view["last_error"])
        self.assertIn("Win32 error 31", view["last_error"],
                      "the Win32 reason must survive the connect, not be dropped")

    def test_implausible_data_is_not_reported_as_a_refusal(self):
        # A report that arrived and did not decode points at the layout; a
        # refusal points at the driver or another process. Opposite fixes.
        device = FakeDevice(feature=bytes([ds.FEATURE_CALIBRATION])
                            + b"\x00" * (ds.CALIBRATION_SIZE - 1))
        view = self._connect_with(device).describe()

        self.assertTrue(view["connected"])
        self.assertIsNone(view["gyro_scales"])
        self.assertIn("implausible", view["last_error"])
        self.assertNotIn("refused", view["last_error"])

    def test_a_healthy_read_leaves_no_error_behind(self):
        view = self._connect_with(FakeDevice()).describe()

        self.assertTrue(view["connected"])
        self.assertIsNotNone(view["gyro_scales"])
        self.assertIsNone(view["last_error"],
                          "a clean connect must still clear earlier failures")


class TestWriteFailureRecovery(unittest.TestCase):
    def _connected_manager(self, device):
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        return manager

    def test_last_rgb_survives_a_failed_write(self):
        """The colour recorded must be the newest one asked for, not the last
        one that reached the wire.

        The reconnect resend can only resend what _last_rgb holds, so recording
        it on success alone would have the reconnect faithfully restore a stale
        colour. Engine's retry does not cover this: it fills the gap only from
        its next tick onward, and a caller that is not the Engine has no retry
        at all.
        """
        # Four writes, in order: _connect's setup packet, _connect's colour (the
        # default, since nothing has been asked for yet), then the two
        # write_colour calls below.
        device = FakeDevice(
            write_errors=[None] * DS5_CONNECT_WRITES
            + [None, RuntimeError("write timed out")])
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

        # setup packet, then the colour repeated across the boot window
        self.assertEqual(len(device.writes), DS5_CONNECT_WRITES)
        # Every write in _connect, including the boot-window repeats, must
        # happen while the device is still unpublished - that is what makes
        # _connect provably the only writer.
        self.assertEqual(device.published_at_write, [False] * DS5_CONNECT_WRITES)
        self.assertEqual(device.writes[-1], ds.build_output("usb", 48, rgb=(4, 5, 6)))


class TestStartupRace(unittest.TestCase):
    def test_a_colour_asked_for_during_connect_never_leaves_the_bar_dark(self):
        """The window between _connect reading _last_rgb and publishing.

        A write_colour landing in there records its colour, finds self._device
        still None, and returns False -- while _connect goes on to write the
        colour it read a moment earlier and publish. With the light-out setup
        packet already sent and the engine marking a colour written whether or
        not it landed, the outcome was a dark bar, connected: true, and no error
        anywhere. Narrow window, permanent and silent result.

        Two independent closures, both asserted here: the connect ends on a
        colour rather than on light-out, and the loser's False return is a
        retryable failure with its intent recorded for the next reconnect.
        """
        manager = DeviceManager(AppState())
        landed = []

        def intrude(index):
            # Index 1 is _connect's colour write -- after it read _last_rgb,
            # before it publishes. Exactly the window.
            if index == 1:
                landed.append(manager.write_colour((5, 5, 5)))

        device = FakeDevice(manager=manager, on_write=intrude)
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)

        self.assertTrue(manager._connect())

        self.assertEqual(landed, [False],
                         "the intruding write must report that it did not land")
        self.assertEqual(device.writes[-1],
                         ds.build_output("usb", 48, rgb=DEFAULT_RGB, seq=1),
                         "the connect must still end on a colour, not light-out")
        self.assertEqual(manager._last_rgb, (5, 5, 5),
                         "the colour that lost the race must survive to the "
                         "next reconnect")


class TestDropIsScopedToOneHandle(unittest.TestCase):
    def test_a_failed_write_does_not_close_a_newer_healthy_handle(self):
        """write_colour releases the lock for the write itself.

        The reader can drop that handle and finish a reconnect inside that
        window, so an unconditional close on the failure path would take down
        the healthy new connection on behalf of a handle that is already gone.
        """
        device = FakeDevice(
            write_errors=[None] * DS5_CONNECT_WRITES + [RuntimeError("write timed out")])
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        replacement = FakeDevice()

        def reconnect_underneath(index):
            with manager._lock:
                manager._device = replacement

        device._on_write = reconnect_underneath

        self.assertFalse(manager.write_colour((1, 2, 3)))

        self.assertEqual(replacement.closed, 0,
                         "the new handle belongs to the reader, not to this "
                         "failure")
        self.assertIs(manager._device, replacement)


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

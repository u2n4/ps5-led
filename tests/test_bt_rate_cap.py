"""The engine must not drive Bluetooth above ~30 output reports a second.

Measured on the real controller: a 60 Hz Rainbow over Bluetooth dropped the
link at 18.9 s and 65 writes then failed -- the flicker the user saw. The same
load at 30 Hz, and over USB at 60 Hz, was clean. So Engine._send decimates
free-running animation frames per transport, while a forced write (a colour
the user just picked, the manual heartbeat) always goes through.

No hardware here: the harness exec's the Engine in isolation with a fake device
and a clock we advance by hand, so the assertions are about counts, not luck.
"""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_native_backend as harness  # noqa: E402


def _engine_on(transport):
    app = harness.app_classes()
    backend = app["Backend"]()
    device = harness.FakeDevice()
    harness.connect(backend._manager, device, transport=transport)
    engine = app["Engine"](backend)
    now = [1000.0]
    app["time"] = types.SimpleNamespace(time=lambda: now[0], sleep=lambda _: None)
    return app, engine, device, now


def _drive(engine, device, now, seconds=1.0, hz=60, force=False):
    """Send one frame per tick for `seconds`; return how many reached the device."""
    before = len(device.writes)
    step = 1.0 / hz
    for i in range(int(seconds * hz)):
        now[0] += step
        engine._send((i % 256, 0, 0), force=force)
    return len(device.writes) - before


class TestBluetoothRateCap(unittest.TestCase):
    def test_bluetooth_animation_is_capped_near_30_hz(self):
        app, engine, device, now = _engine_on("bt")
        # A minimum-interval gate against a quantised producer lands the first
        # frame at or past the gap, so the effective rate rounds DOWN to a
        # multiple of the offered step: measured 20/s when offered 60, 25/s
        # when offered 100. The property that matters is the ceiling -- the
        # link drops above 30/s -- and a floor that keeps the animation alive.
        for hz in (60, 100):
            app, engine, device, now = _engine_on("bt")
            landed = _drive(engine, device, now, seconds=2.0, hz=hz)
            self.assertLessEqual(landed, 60, "offered %d Hz: Bluetooth got more than 30/s" % hz)
            self.assertGreaterEqual(landed, 30, "offered %d Hz: below 15/s, animation would stutter" % hz)

    def test_usb_animation_is_not_capped(self):
        app, engine, device, now = _engine_on("usb")
        landed = _drive(engine, device, now, seconds=1.0, hz=60)
        self.assertEqual(landed, 60)

    def test_forced_writes_are_never_dropped_on_bluetooth(self):
        app, engine, device, now = _engine_on("bt")
        landed = _drive(engine, device, now, seconds=1.0, hz=60, force=True)
        self.assertEqual(landed, 60)

    def test_a_skipped_frame_reports_success_not_failure(self):
        # A skip is deliberate; reporting it as a failed write would make the
        # manual heartbeat and auto-sleep bookkeeping think the device is gone.
        app, engine, device, now = _engine_on("bt")
        now[0] += 1.0
        self.assertTrue(engine._send((1, 2, 3)))          # lands
        now[0] += 0.001
        self.assertTrue(engine._send((4, 5, 6)))          # skipped, still True
        # connect() wrote the setup packet plus the boot colour repeats; only
        # the first _send above added one more, the skipped one added nothing.
        self.assertEqual(len(device.writes), 1 + harness.BOOT_COLOUR_WRITES + 1)

    def test_the_gate_uses_the_live_transport(self):
        # Unplugging the cable flips the pad to Bluetooth mid-run; the gate must
        # follow the transport that is actually connected, not the one at start.
        app, engine, device, now = _engine_on("usb")
        self.assertEqual(_drive(engine, device, now, seconds=1.0, hz=60), 60)
        backend = engine.b
        backend.update(transport="bt")
        self.assertLessEqual(_drive(engine, device, now, seconds=1.0, hz=60), 32)


if __name__ == "__main__":
    unittest.main()

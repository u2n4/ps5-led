import threading
import time
import unittest

from ps5led.device import DEFAULT_RGB, DeviceManager
from ps5led.engine import Engine, MODES, colour_for, hsv_to_rgb
from ps5led.state import AppState

BASE = {"colour": (0, 170, 255), "brightness": 1.0, "duty": 0.5, "battery": None}


def settings(**overrides):
    merged = dict(BASE)
    merged.update(overrides)
    return merged


def recording_writer(sink, ok=True):
    """A writer that records what it was given and reports the truth about it.

    The engine's writer contract is DeviceManager.write_colour's: truthy means
    the colour reached the device, falsy means it did not and must be retried.
    ``writes.append`` returns None, so a fake built on it stands for a writer
    that fails every single time -- and a test using one would measure the
    engine's retry behaviour while claiming to measure its write-once
    behaviour. That mismatch is exactly what let the engine's success gate go
    unnoticed: the fakes here raised where the real writer returns False.
    """
    def write(rgb):
        sink.append(rgb)
        return ok
    return write


class TestHsv(unittest.TestCase):
    def test_primaries(self):
        self.assertEqual(hsv_to_rgb(0.0, 1.0, 1.0), (255, 0, 0))
        self.assertEqual(hsv_to_rgb(1 / 3.0, 1.0, 1.0), (0, 255, 0))
        self.assertEqual(hsv_to_rgb(2 / 3.0, 1.0, 1.0), (0, 0, 255))

    def test_value_scales_output(self):
        self.assertEqual(hsv_to_rgb(0.0, 1.0, 0.5), (127, 0, 0))

    def test_zero_saturation_is_grey(self):
        r, g, b = hsv_to_rgb(0.4, 0.0, 1.0)
        self.assertEqual((r, g, b), (255, 255, 255))

    def test_hue_wraps(self):
        self.assertEqual(hsv_to_rgb(1.0, 1.0, 1.0), hsv_to_rgb(0.0, 1.0, 1.0))

    def test_channels_stay_in_range(self):
        for step in range(0, 100):
            for channel in hsv_to_rgb(step / 100.0, 1.0, 1.0):
                self.assertTrue(0 <= channel <= 255)


class TestColourFor(unittest.TestCase):
    def test_modes_are_named(self):
        self.assertEqual(MODES, ("manual", "rainbow", "wave", "flash", "battery"))

    def test_manual_ignores_phase(self):
        for phase in (0.0, 0.25, 0.9):
            self.assertEqual(colour_for("manual", phase, settings()), (0, 170, 255))

    def test_manual_applies_brightness(self):
        self.assertEqual(colour_for("manual", 0.0, settings(colour=(200, 100, 50),
                                                            brightness=0.5)),
                         (100, 50, 25))

    def test_rainbow_moves_with_phase(self):
        self.assertNotEqual(colour_for("rainbow", 0.0, settings()),
                            colour_for("rainbow", 0.5, settings()))

    def test_rainbow_is_periodic(self):
        self.assertEqual(colour_for("rainbow", 0.0, settings()),
                         colour_for("rainbow", 1.0, settings()))

    def test_wave_dims_the_base_colour_without_changing_hue(self):
        bright = colour_for("wave", 0.25, settings(colour=(255, 0, 0)))
        dim = colour_for("wave", 0.75, settings(colour=(255, 0, 0)))
        self.assertEqual((bright[1], bright[2]), (0, 0))
        self.assertGreater(bright[0], dim[0])

    def test_flash_is_on_below_duty_and_off_above(self):
        on = colour_for("flash", 0.1, settings(colour=(255, 0, 0), duty=0.5))
        off = colour_for("flash", 0.9, settings(colour=(255, 0, 0), duty=0.5))
        self.assertEqual(on, (255, 0, 0))
        self.assertEqual(off, (0, 0, 0))

    def test_flash_duty_shifts_the_boundary(self):
        self.assertEqual(colour_for("flash", 0.7, settings(colour=(255, 0, 0), duty=0.9)),
                         (255, 0, 0))

    def test_battery_is_green_when_full(self):
        r, g, b = colour_for("battery", 0.0, settings(battery=100))
        self.assertGreater(g, 200)
        self.assertLess(r, 60)

    def test_battery_is_red_when_empty(self):
        r, g, b = colour_for("battery", 0.0, settings(battery=0))
        self.assertGreater(r, 200)
        self.assertLess(g, 60)

    def test_battery_falls_back_to_manual_when_unknown(self):
        self.assertEqual(colour_for("battery", 0.0, settings(battery=None)),
                         (0, 170, 255))

    def test_unknown_mode_falls_back_to_manual(self):
        self.assertEqual(colour_for("nonsense", 0.3, settings()), (0, 170, 255))

    def test_every_mode_returns_valid_channels(self):
        for mode in MODES:
            for phase in (0.0, 0.33, 0.66, 0.99):
                for channel in colour_for(mode, phase, settings(battery=50)):
                    self.assertTrue(0 <= channel <= 255, "%s %s" % (mode, phase))


class TestEngineThread(unittest.TestCase):
    def test_writes_once_for_a_solid_colour(self):
        writes = []
        state = AppState()
        engine = Engine(state, recording_writer(writes), interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()
        self.assertEqual(writes, [(10, 20, 30)],
                         "a solid colour must not be rewritten every frame")

    def test_writes_repeatedly_for_an_animated_mode(self):
        writes = []
        engine = Engine(AppState(), recording_writer(writes), interval=0.005)
        engine.set_mode("rainbow")
        engine.start()
        time.sleep(0.2)
        engine.stop()
        self.assertGreater(len(writes), 3)

    def test_publishes_colour_to_state(self):
        state = AppState()
        engine = Engine(state, recording_writer([]), interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((1, 2, 3))
        engine.start()
        time.sleep(0.1)
        engine.stop()
        self.assertEqual(state.snapshot()["rgb"], (1, 2, 3))

    def test_stop_joins_the_thread(self):
        before = threading.active_count()
        engine = Engine(AppState(), recording_writer([]), interval=0.005)
        engine.start()
        self.assertTrue(engine.is_alive())
        engine.stop()
        self.assertFalse(engine.is_alive())
        self.assertEqual(threading.active_count(), before,
                         "stop() must join the thread, not leak it")

    def test_a_failing_writer_does_not_kill_the_thread(self):
        calls = []

        def writer(rgb):
            calls.append(rgb)
            raise RuntimeError("device went away")

        engine = Engine(AppState(), writer, interval=0.005)
        engine.set_mode("rainbow")
        engine.start()
        time.sleep(0.15)
        alive = engine.is_alive()
        engine.stop()
        self.assertTrue(alive, "the engine must survive a write failure")
        self.assertGreater(len(calls), 1)

    def test_mode_switch_to_an_identical_colour_is_still_observable_in_state(self):
        # Regression for IMPORTANT 1: AppState.mode must not get stuck on a
        # stale value just because the resulting colour did not change.
        state = AppState()
        engine = Engine(state, recording_writer([]), interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((0, 170, 255))
        engine.start()
        time.sleep(0.1)
        # battery is None, so colour_for("battery", ...) falls back to the
        # identical manual colour -- the rgb the engine writes does not change,
        # but the mode the caller asked for did, and AppState must say so.
        engine.set_mode("battery")
        time.sleep(0.1)
        engine.stop()
        snap = state.snapshot()
        self.assertEqual(snap["rgb"], (0, 170, 255))
        self.assertEqual(snap["mode"], "battery",
                         "AppState.mode must track the live mode even when "
                         "the resulting colour is unchanged")

    def test_writer_that_raises_once_then_succeeds_eventually_delivers(self):
        # A transient write failure must not permanently desync _last_written
        # (and AppState) from what the device actually holds -- the next tick
        # should retry, not skip. This covers the raising half of the contract
        # only; the real writer never raises, and the returns-False half is
        # test_a_writer_that_returns_false_is_retried_then_settles below.
        calls = []
        state = AppState()

        def flaky_writer(rgb):
            calls.append(rgb)
            if len(calls) == 1:
                raise RuntimeError("device busy, try again")
            return True

        engine = Engine(state, flaky_writer, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()

        self.assertEqual(len(calls), 2,
                         "a writer that failed once must be retried once, then "
                         "left alone after it succeeds")
        self.assertTrue(all(rgb == (10, 20, 30) for rgb in calls))
        # AppState must not claim the colour was delivered before a write
        # actually succeeded.
        self.assertEqual(state.snapshot()["rgb"], (10, 20, 30))

    def test_a_writer_that_returns_false_is_retried_then_settles(self):
        """The contract the production writer actually speaks.

        DeviceManager.write_colour never raises -- every failure path returns
        False. The engine used to advance _last_written whenever the call did
        not raise, so a colour that never left the process was marked delivered
        and, in a mode that writes once, nothing ever asked for it again.
        """
        calls = []

        def writer(rgb):
            calls.append(rgb)
            return len(calls) >= 3  # the first two attempts do not land

        engine = Engine(AppState(), writer, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()

        # Three, exactly: two failures retried, and no fourth attempt after the
        # one that succeeded.
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(rgb == (10, 20, 30) for rgb in calls))

    def test_battery_mode_follows_the_live_level_in_appstate(self):
        """The wiring, not the maths.

        colour_for already knew how to render a battery level and MODES already
        advertised the mode; nothing put the live level in front of it.
        DeviceManager publishes battery into AppState from every input report,
        and Engine never read AppState at all, so battery mode rendered as plain
        manual on every real run. Driven here through AppState exactly as the
        device does it, not through a hand-built settings dict.
        """
        state = AppState()
        engine = Engine(state, recording_writer([]), interval=0.005)
        engine.set_mode("battery")
        state.update(battery=0)
        engine.start()
        try:
            time.sleep(0.08)
            empty = state.snapshot()["rgb"]
            state.update(battery=100)
            time.sleep(0.08)
            full = state.snapshot()["rgb"]
        finally:
            engine.stop()

        self.assertGreater(empty[0], 200, "an empty battery must read red")
        self.assertLess(empty[1], 60)
        self.assertGreater(full[1], 200, "a full battery must read green")
        self.assertLess(full[0], 60)


class TestEngineAgainstTheRealWriter(unittest.TestCase):
    """The seam itself, with no fake standing in for DeviceManager.

    Two tests on this boundary used to encode opposite contracts: an engine test
    whose fake raised, and a device test whose docstring said write_colour
    returns False instead. Only one of them described the shipped code.
    """

    def test_write_colour_reports_failure_by_returning_false(self):
        manager = DeviceManager(AppState())  # never started: no device

        self.assertFalse(manager.write_colour((1, 2, 3)),
                         "the engine's success gate reads this return value")

    def test_the_engine_never_marks_a_write_colour_failure_as_delivered(self):
        manager = DeviceManager(AppState())  # never started: no device
        engine = Engine(AppState(), manager.write_colour, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((7, 7, 7))
        engine.start()
        time.sleep(0.1)
        engine.stop()

        self.assertIsNone(engine._last_written,
                          "nothing reached a device, so nothing is written")
        self.assertEqual(manager.describe()["last_error"], "no device connected")
        # The intent is still recorded, so the next connect resends it rather
        # than falling back to the default.
        self.assertEqual(manager._last_rgb, (7, 7, 7))
        self.assertNotEqual(manager._last_rgb, DEFAULT_RGB)


class TestBatteryOverride(unittest.TestCase):
    """AppState is the normal source, but an explicit set_setting must win --
    it was overwritten unconditionally, so the setter was silently inert."""

    def test_appstate_supplies_battery_when_nothing_was_set(self):
        state = AppState()
        state.update(battery=100)
        engine = Engine(state, lambda rgb: True, interval=0.005)
        engine.set_mode("battery")
        engine.start()
        time.sleep(0.1)
        engine.stop()
        r, g, b = state.snapshot()["rgb"]
        self.assertGreater(g, 200)

    def test_an_explicit_override_is_not_erased_by_appstate(self):
        state = AppState()
        state.update(battery=100)
        engine = Engine(state, lambda rgb: True, interval=0.005)
        engine.set_mode("battery")
        engine.set_setting("battery", 0)
        engine.start()
        time.sleep(0.1)
        engine.stop()
        r, g, b = state.snapshot()["rgb"]
        self.assertGreater(r, 200, "the explicit override was overwritten")


if __name__ == "__main__":
    unittest.main()

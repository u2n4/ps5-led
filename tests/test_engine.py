import threading
import time
import unittest

from ps5led.engine import Engine, MODES, colour_for, hsv_to_rgb
from ps5led.state import AppState

BASE = {"colour": (0, 170, 255), "brightness": 1.0, "duty": 0.5, "battery": None}


def settings(**overrides):
    merged = dict(BASE)
    merged.update(overrides)
    return merged


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
        engine = Engine(state, writes.append, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()
        self.assertEqual(writes, [(10, 20, 30)],
                         "a solid colour must not be rewritten every frame")

    def test_writes_repeatedly_for_an_animated_mode(self):
        writes = []
        engine = Engine(AppState(), writes.append, interval=0.005)
        engine.set_mode("rainbow")
        engine.start()
        time.sleep(0.2)
        engine.stop()
        self.assertGreater(len(writes), 3)

    def test_publishes_colour_to_state(self):
        state = AppState()
        engine = Engine(state, lambda rgb: None, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((1, 2, 3))
        engine.start()
        time.sleep(0.1)
        engine.stop()
        self.assertEqual(state.snapshot()["rgb"], (1, 2, 3))

    def test_stop_joins_the_thread(self):
        before = threading.active_count()
        engine = Engine(AppState(), lambda rgb: None, interval=0.005)
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
        engine = Engine(state, lambda rgb: None, interval=0.005)
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

    def test_writer_that_fails_once_then_succeeds_eventually_delivers(self):
        # Regression for IMPORTANT 2: a transient write failure must not
        # permanently desync _last_written (and AppState) from what the
        # device actually holds -- the next tick should retry, not skip.
        calls = []
        state = AppState()

        def flaky_writer(rgb):
            calls.append(rgb)
            if len(calls) == 1:
                raise RuntimeError("device busy, try again")

        engine = Engine(state, flaky_writer, interval=0.005)
        engine.set_mode("manual")
        engine.set_colour((10, 20, 30))
        engine.start()
        time.sleep(0.15)
        engine.stop()

        self.assertGreaterEqual(len(calls), 2,
                                "a writer that failed once must be retried, "
                                "not abandoned forever")
        self.assertTrue(all(rgb == (10, 20, 30) for rgb in calls))
        # AppState must not claim the colour was delivered before a write
        # actually succeeded.
        self.assertEqual(state.snapshot()["rgb"], (10, 20, 30))


if __name__ == "__main__":
    unittest.main()

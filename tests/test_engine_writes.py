"""Engine writes that must stop, must not happen, or must happen once.

The harness exec's the Engine class bodies in isolation with a fake device and
a clock advanced by hand, so every assertion is about counts and last values,
not timing. No hardware is needed.

- Auto Sleep counts time since the last change made in the app. The engine's
  own frames and Manual heartbeats are not activity, so they cannot keep the
  lightbar awake (before this, the lightbar never slept).
- Tray "Off" and an auto-sleep hold are writes that end at the next change in
  the app. Tray "Off" must not overwrite the saved colour.
- A colour picked during a drag goes through the Bluetooth rate gate. The
  Manual loop lands the final colour, so the drag cannot flood the link.
- The config is written at most once a second while a slider or picker is
  dragged, and the final value is written on quit.
- The Auto Sleep minutes box keeps a typed value only when it is a number.
  Anything else keeps the saved value instead of dropping the setting.
"""
import sys
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appload  # noqa: E402  (keeps dualled_pro's settings folder out of the real %APPDATA%)
import test_native_backend as harness  # noqa: E402

dp = appload.dualled_pro


def _engine(transport="usb", auto_sleep=None):
    app = harness.app_classes()
    app["CFG"]["auto_sleep"] = auto_sleep or {"enabled": False}
    app["save_cfg"] = lambda cfg: None           # settings writes are not under test
    app["save_cfg_throttled"] = lambda cfg: None
    backend = app["Backend"]()
    device = harness.FakeDevice()
    harness.connect(backend._manager, device, transport=transport)
    engine = app["Engine"](backend)
    now = [1000.0]
    app["time"] = SimpleNamespace(time=lambda: now[0],
                                  sleep=lambda _: engine.stop_evt.set())
    return app, engine, device, now


def _tick(engine, now, seconds):
    """Run the engine loop once per quarter second of fake time."""
    for _ in range(int(round(seconds / 0.25))):
        now[0] += 0.25
        engine.stop_evt.clear()
        engine.run()


def _usb_rgb(packet):
    return tuple(packet[45:48])


class AutoSleepTests(unittest.TestCase):
    def test_manual_heartbeats_do_not_keep_the_lightbar_awake(self):
        app, engine, device, now = _engine(
            auto_sleep={"enabled": True, "minutes": 1, "action": "off"})
        engine.set_color((0, 170, 255))          # a change in the app starts the clock
        _tick(engine, now, 50)                   # the Manual heartbeat runs every 2 s
        self.assertIsNone(engine._hold)
        _tick(engine, now, 25)                   # 75 s without a change: past one minute
        self.assertEqual(engine._hold, "off")
        self.assertEqual(_usb_rgb(device.writes[-1]), (0, 0, 0))
        written = len(device.writes)
        _tick(engine, now, 30)
        self.assertEqual(len(device.writes), written, "a held lightbar must stay off")

    def test_a_change_in_the_app_wakes_the_lightbar(self):
        app, engine, device, now = _engine(
            auto_sleep={"enabled": True, "minutes": 1, "action": "off"})
        engine.set_color((0, 170, 255))
        _tick(engine, now, 90)
        self.assertEqual(engine._hold, "off")
        engine.set_color((255, 0, 0))
        self.assertIsNone(engine._hold)
        _tick(engine, now, 0.25)
        self.assertEqual(_usb_rgb(device.writes[-1]), (255, 0, 0))

    def test_solid_action_freezes_at_the_chosen_colour(self):
        app, engine, device, now = _engine(
            auto_sleep={"enabled": True, "minutes": 1, "action": "solid"})
        engine.set_color((10, 20, 30))
        _tick(engine, now, 90)
        self.assertEqual(engine._hold, "solid")
        self.assertEqual(_usb_rgb(device.writes[-1]), (10, 20, 30))

    def test_disabled_auto_sleep_never_holds(self):
        app, engine, device, now = _engine(
            auto_sleep={"enabled": False, "minutes": 1, "action": "off"})
        engine.set_color((0, 170, 255))
        _tick(engine, now, 600)
        self.assertIsNone(engine._hold)


class TrayOffTests(unittest.TestCase):
    def test_hold_off_darkens_the_bar_and_keeps_the_saved_colour(self):
        app, engine, device, now = _engine()
        app["CFG"]["color"] = "#ff3434"
        engine.color = (255, 52, 52)
        engine.hold_off()
        self.assertEqual(_usb_rgb(device.writes[-1]), (0, 0, 0))
        self.assertEqual(app["CFG"]["color"], "#ff3434")
        written = len(device.writes)
        _tick(engine, now, 5)
        self.assertEqual(len(device.writes), written)


class PickerDragTests(unittest.TestCase):
    def test_a_drag_on_bluetooth_stays_under_the_link_limit(self):
        app, engine, device, now = _engine("bt")
        engine.mode = "Manual"
        now[0] += 1.0
        before = len(device.writes)
        for i in range(120):                     # a 1.2 s drag sampled at 100 Hz
            now[0] += 0.01
            engine.set_color((i, 0, 0))
        landed = len(device.writes) - before
        self.assertLessEqual(landed, 40, "a drag pushed %d writes onto Bluetooth" % landed)
        _tick(engine, now, 0.25)                 # the Manual loop lands the final colour
        self.assertEqual(tuple(device.writes[-1][47:50]), (119, 0, 0))


class ConfigWriteTests(unittest.TestCase):
    def test_a_drag_writes_the_config_at_most_once_a_second(self):
        now = [500.0]
        fake_clock = SimpleNamespace(time=lambda: now[0], strftime=time.strftime)
        dp._CFG_SAVE.update(last=0.0, dirty=False)
        with patch.object(dp, "time", fake_clock), patch.object(dp, "save_cfg") as save:
            for _ in range(300):                 # ten seconds of 33 ms ticks, value moving each tick
                now[0] += 0.033
                dp.save_cfg_throttled(dp.CFG)
                dp.flush_cfg()
        self.assertLessEqual(save.call_count, 11)
        self.assertGreaterEqual(save.call_count, 9)

    def test_quit_writes_the_last_value_even_inside_the_window(self):
        now = [500.0]
        fake_clock = SimpleNamespace(time=lambda: now[0], strftime=time.strftime)
        dp._CFG_SAVE.update(last=now[0], dirty=True)
        with patch.object(dp, "time", fake_clock), patch.object(dp, "save_cfg") as save:
            dp.flush_cfg()
            self.assertEqual(save.call_count, 0)
            dp.flush_cfg(force=True)
            self.assertEqual(save.call_count, 1)


class AutoSleepMinutesTests(unittest.TestCase):
    def test_typed_minutes_are_whole_numbers_of_at_least_one(self):
        parse = dp.parse_auto_sleep_minutes
        self.assertEqual(parse("45", 30), 45)
        self.assertEqual(parse(" 20 ", 30), 20)
        self.assertEqual(parse("1.5", 30), 1)
        self.assertEqual(parse("0", 30), 1)
        self.assertEqual(parse("-3", 30), 1)
        self.assertEqual(parse("", 30), 30)

    def test_text_that_is_not_a_number_keeps_the_saved_value(self):
        parse = dp.parse_auto_sleep_minutes
        for text in ("30 min", "abc", "nan", "inf", "1e400"):
            self.assertEqual(parse(text, 15), 15, repr(text))


if __name__ == "__main__":
    unittest.main()

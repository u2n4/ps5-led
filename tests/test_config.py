import json
import os
import tempfile
import time
import unittest

from ps5led import config as cfg


class TestDefaults(unittest.TestCase):
    def test_shape(self):
        for key in ("mode", "colour", "speed", "brightness", "language",
                    "shell", "profiles", "window"):
            self.assertIn(key, cfg.DEFAULTS)

    def test_default_colour_matches_the_device_default(self):
        from ps5led.device import DEFAULT_RGB
        self.assertEqual(tuple(cfg.DEFAULTS["colour"]), DEFAULT_RGB,
                         "a saved-nothing launch must not change colour on connect")

    def test_default_mode_is_a_real_mode(self):
        from ps5led.engine import MODES
        self.assertIn(cfg.DEFAULTS["mode"], MODES)

    def test_defaults_are_not_shared_between_loads(self):
        a = cfg.load(path=os.devnull)
        b = cfg.load(path=os.devnull)
        a["profiles"]["scratch"] = 1
        self.assertNotIn("scratch", b["profiles"], "load() handed out a shared object")


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_missing_file_gives_defaults(self):
        self.assertEqual(cfg.load(self.path)["mode"], cfg.DEFAULTS["mode"])

    def test_corrupt_file_gives_defaults_rather_than_raising(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        self.assertEqual(cfg.load(self.path)["mode"], cfg.DEFAULTS["mode"])

    def test_truncated_file_gives_defaults(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"mode": "rain')
        self.assertEqual(cfg.load(self.path)["mode"], cfg.DEFAULTS["mode"])

    def test_a_json_list_at_the_top_level_gives_defaults(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        self.assertEqual(cfg.load(self.path)["mode"], cfg.DEFAULTS["mode"])

    def test_saved_values_win_over_defaults(self):
        cfg.save({"mode": "rainbow", "speed": 2.5}, self.path)
        loaded = cfg.load(self.path)
        self.assertEqual(loaded["mode"], "rainbow")
        self.assertEqual(loaded["speed"], 2.5)

    def test_missing_keys_are_filled_from_defaults(self):
        cfg.save({"mode": "rainbow"}, self.path)
        self.assertEqual(cfg.load(self.path)["language"], cfg.DEFAULTS["language"])

    def test_unknown_keys_survive_a_round_trip(self):
        cfg.save({"mode": "rainbow", "from_a_newer_build": 7}, self.path)
        self.assertEqual(cfg.load(self.path)["from_a_newer_build"], 7)


class TestSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_creates_the_directory(self):
        nested = os.path.join(self.dir, "a", "b", "config.json")
        cfg.save({"mode": "wave"}, nested)
        self.assertTrue(os.path.exists(nested))

    def test_writes_utf8_without_a_bom(self):
        # PowerShell's Set-Content -Encoding UTF8 writes a BOM and strict JSON
        # readers choke on the three invisible bytes. Ours must not.
        cfg.save({"mode": "wave", "note": "عربي"}, self.path)
        with open(self.path, "rb") as fh:
            head = fh.read(3)
        self.assertNotEqual(head, b"\xef\xbb\xbf")

    def test_round_trips_non_ascii(self):
        cfg.save({"note": "عربي"}, self.path)
        self.assertEqual(cfg.load(self.path)["note"], "عربي")

    def test_an_unwritable_path_does_not_raise(self):
        # Losing a preference is acceptable; crashing the app on shutdown is not.
        cfg.save({"mode": "wave"}, os.path.join(self.dir, "nope\x00bad", "c.json"))


class TestConfigObject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_get_falls_back_to_defaults(self):
        c = cfg.Config(self.path)
        self.assertEqual(c.get("mode"), cfg.DEFAULTS["mode"])

    def test_get_returns_an_explicit_default_for_an_unknown_key(self):
        self.assertEqual(cfg.Config(self.path).get("nope", 42), 42)

    def test_set_is_visible_immediately(self):
        c = cfg.Config(self.path)
        c.set("mode", "flash")
        self.assertEqual(c.get("mode"), "flash")

    def test_set_does_not_write_on_every_call(self):
        c = cfg.Config(self.path)
        for i in range(20):
            c.set("speed", i)
        self.assertFalse(os.path.exists(self.path),
                         "20 slider ticks must not be 20 disk writes")

    def test_flush_writes(self):
        c = cfg.Config(self.path)
        c.set("mode", "flash")
        c.flush()
        self.assertEqual(cfg.load(self.path)["mode"], "flash")

    def test_a_later_set_writes_once_the_throttle_has_passed(self):
        c = cfg.Config(self.path, throttle_seconds=0.05)
        c.set("mode", "flash")
        time.sleep(0.08)
        c.set("mode", "wave")
        self.assertEqual(cfg.load(self.path)["mode"], "wave")

    def test_snapshot_is_a_copy(self):
        c = cfg.Config(self.path)
        snap = c.snapshot()
        snap["mode"] = "tampered"
        self.assertNotEqual(c.get("mode"), "tampered")

    def test_snapshot_is_json_serialisable(self):
        json.dumps(cfg.Config(self.path).snapshot())


class TestLocation(unittest.TestCase):
    def test_config_path_is_under_config_dir(self):
        self.assertEqual(cfg.config_path().parent, cfg.config_dir())

    def test_config_path_is_named_config_json(self):
        self.assertEqual(cfg.config_path().name, "config.json")


if __name__ == "__main__":
    unittest.main()

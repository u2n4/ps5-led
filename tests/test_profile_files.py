"""Profile export and import: a bad file gets a clear message, and nothing changes when one is refused.

No controller is needed, and the real settings folder is never touched (see appload).
"""
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import appload

dp = appload.dualled_pro

GOOD = {"mode": "Manual", "speed": 1.0, "rainbow_brightness": 0.9, "flash_duty": 0.5, "color": "#3b82f6"}


def document(profiles, **overrides):
    doc = {"format": dp.PROFILE_FILE_FORMAT, "version": dp.PROFILE_FILE_VERSION, "profiles": profiles}
    doc.update(overrides)
    return doc


class ProfileFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ps5led-profile-tests-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "profiles.json"

    def write_text(self, text):
        self.path.write_text(text, encoding="utf-8")

    def write_document(self, doc):
        self.write_text(json.dumps(doc))

    def assertRefused(self, fragment):
        with self.assertRaises(dp.ProfileFileError) as ctx:
            dp.read_profile_file(self.path)
        self.assertIn(fragment, str(ctx.exception))

    def test_export_then_import_round_trips_every_default_profile(self):
        saved = {name: dict(data) for name, data in dp.DEFAULT_CFG["profiles"].items()}
        self.assertEqual(dp.write_profile_file(self.path, saved), len(saved))
        self.assertEqual(dp.read_profile_file(self.path), saved)

    def test_export_writes_the_documented_format(self):
        dp.write_profile_file(self.path, {"Fortnite": dict(GOOD)})
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc, {"format": "ps5led-profiles", "version": 1, "profiles": {"Fortnite": GOOD}})

    def test_export_refuses_a_saved_profile_that_is_not_valid_and_writes_nothing(self):
        with self.assertRaisesRegex(dp.ProfileFileError, r"Profile 'Broken' has speed 9\.0; it must be from 0\.1 to 5"):
            dp.write_profile_file(self.path, {"Broken": dict(GOOD, speed=9.0)})
        self.assertFalse(self.path.exists())

    def test_export_refuses_when_there_is_nothing_to_export(self):
        with self.assertRaisesRegex(dp.ProfileFileError, "no saved profiles"):
            dp.write_profile_file(self.path, {})

    def test_text_that_is_not_json_says_where_it_breaks(self):
        self.write_text("{not json")
        self.assertRefused("not valid JSON (line 1, column 2)")

    def test_a_top_level_list_is_not_a_profile_file(self):
        self.write_text("[]")
        self.assertRefused("the top level must be a JSON object")

    def test_another_programs_file_is_refused_by_its_format(self):
        self.write_document(document({"Fortnite": GOOD}, format="something-else"))
        self.assertRefused('is not a PS5 LED profile file: "format" must be "ps5led-profiles"')

    def test_an_unknown_version_is_refused(self):
        self.write_document(document({"Fortnite": GOOD}, version=2))
        self.assertRefused("has version 2. This program reads version 1")

    def test_a_boolean_or_float_version_is_refused(self):
        for version in (True, 1.0):
            with self.subTest(version):
                self.write_document(document({"Fortnite": GOOD}, version=version))
                self.assertRefused("This program reads version 1")

    def test_a_file_with_no_profiles_is_refused(self):
        self.write_document(document({}))
        self.assertRefused("contains no profiles")

    def test_a_profile_missing_a_field_names_the_field(self):
        broken = dict(GOOD)
        del broken["flash_duty"]
        self.write_document(document({"Fortnite": broken}))
        self.assertRefused("Profile 'Fortnite' is missing 'flash_duty'")

    def test_an_unknown_field_is_refused(self):
        self.write_document(document({"Fortnite": dict(GOOD, brightness=3)}))
        self.assertRefused("Profile 'Fortnite' has an unknown field 'brightness'")

    def test_bad_values_are_refused_and_name_the_profile(self):
        cases = {
            "colour without a hash": dict(GOOD, color="3b82f6"),
            "named colour": dict(GOOD, color="red"),
            "colour that is not text": dict(GOOD, color=12),
            "unknown mode": dict(GOOD, mode="Disco"),
            "speed too low": dict(GOOD, speed=0.05),
            "speed too high": dict(GOOD, speed=5.5),
            "brightness too low": dict(GOOD, rainbow_brightness=0.1),
            "duty too high": dict(GOOD, flash_duty=0.95),
            "speed as text": dict(GOOD, speed="1.0"),
            "speed as a boolean": dict(GOOD, speed=True),
            "speed not finite": dict(GOOD, speed=math.nan),
        }
        for label, profile in cases.items():
            with self.subTest(label):
                self.write_document(document({"Fortnite": profile}))
                self.assertRefused("Profile 'Fortnite' has")

    def test_bad_profile_names_are_refused(self):
        cases = {
            "empty": ("", "A profile name is empty."),
            "blank": ("   ", "A profile name is empty."),
            "too long": ("x" * (dp.PROFILE_NAME_MAX + 1), "is longer than 40 characters"),
            "control character": ("bad\nname", "contains a control character"),
            "lone surrogate": ("\ud800", "is not valid text"),
        }
        for label, (name, fragment) in cases.items():
            with self.subTest(label):
                self.write_document(document({name: dict(GOOD)}))
                self.assertRefused(fragment)

    def test_a_file_over_the_size_limit_is_refused_before_it_is_read(self):
        self.write_text("x" * (dp.PROFILE_FILE_MAX_BYTES + 1))
        self.assertRefused("is larger than")

    def test_huge_numbers_are_refused_without_crashing(self):
        self.write_document(document({"Fortnite": dict(GOOD, speed=10 ** 401)}))
        self.assertRefused("Profile 'Fortnite' has speed")
        self.write_text('{"format": "ps5led-profiles", "version": 1, "profiles": {"Fortnite": '
                        '{"mode": "Manual", "speed": ' + "1" * 5000 + ', "rainbow_brightness": 0.9, '
                        '"flash_duty": 0.5, "color": "#3b82f6"}}}')
        with self.assertRaises(dp.ProfileFileError):
            dp.read_profile_file(self.path)

    def test_the_settings_file_is_refused_as_an_export_target(self):
        with self.assertRaisesRegex(dp.ProfileFileError, "is the settings file"):
            dp.write_profile_file(dp.CFG_FILE, {"Fortnite": dict(GOOD)})

    def test_a_missing_file_is_reported(self):
        with self.assertRaisesRegex(dp.ProfileFileError, "Cannot read"):
            dp.read_profile_file(self.dir / "absent.json")

    def test_a_byte_order_mark_from_windows_powershell_is_accepted(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + json.dumps(document({"Fortnite": GOOD})).encode("utf-8"))
        self.assertEqual(list(dp.read_profile_file(self.path)), ["Fortnite"])

    def test_a_refused_import_changes_nothing_and_saves_nothing(self):
        cfg = {"profiles": {"Default": dict(GOOD)}}
        self.write_document(document({"Good": dict(GOOD), "Bad": dict(GOOD, mode="Disco")}))
        with patch.object(dp, "CFG", cfg), patch.object(dp, "save_cfg") as save:
            with self.assertRaises(dp.ProfileFileError):
                dp.import_profile_file_into_settings(self.path)
        self.assertEqual(cfg, {"profiles": {"Default": GOOD}})
        save.assert_not_called()

    def test_a_settings_file_that_cannot_be_written_is_reported_and_nothing_changes(self):
        cfg = {"profiles": {"Default": dict(GOOD)}}
        self.write_document(document({"Night": dict(GOOD, color="#101020")}))
        with patch.object(dp, "CFG", cfg), patch.object(dp, "save_cfg", return_value=False):
            with self.assertRaisesRegex(dp.ProfileFileError, "could not be saved"):
                dp.import_profile_file_into_settings(self.path)
        self.assertEqual(cfg, {"profiles": {"Default": GOOD}})

    def test_an_import_adds_new_profiles_and_replaces_same_named_ones(self):
        cfg = {"profiles": {"Default": dict(GOOD, color="#000000"), "Keep": dict(GOOD)}}
        self.write_document(document({"Default": dict(GOOD, color="#112233"), "Night": dict(GOOD, color="#101020")}))
        with patch.object(dp, "CFG", cfg), patch.object(dp, "save_cfg") as save:
            added, replaced = dp.import_profile_file_into_settings(self.path)
        self.assertEqual((added, replaced), (1, 1))
        self.assertEqual(cfg["profiles"]["Default"]["color"], "#112233")
        self.assertEqual(cfg["profiles"]["Keep"], GOOD)
        self.assertEqual(cfg["profiles"]["Night"]["color"], "#101020")
        save.assert_called_once_with(cfg)


if __name__ == "__main__":
    unittest.main()

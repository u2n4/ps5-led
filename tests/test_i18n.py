import json
import unittest

from ps5led import i18n

REQUIRED = (
    "app_title", "mode", "mode_manual", "mode_rainbow", "mode_wave",
    "mode_flash", "mode_battery", "colour", "speed", "brightness", "duty",
    "shell", "shell_white", "shell_black", "shell_red", "battery", "charging",
    "connected", "disconnected", "transport_usb", "transport_bt", "recentre",
    "about", "close", "background", "profiles", "profile_save",
    "profile_delete", "language", "no_controller", "held_by_another_app",
)


class TestLanguages(unittest.TestCase):
    def test_both_languages_exist(self):
        self.assertEqual(set(i18n.LANGUAGES), {"ar", "en"})

    def test_direction_is_declared_for_each(self):
        self.assertEqual(i18n.DIRECTION["ar"], "rtl")
        self.assertEqual(i18n.DIRECTION["en"], "ltr")

    def test_every_language_has_a_direction(self):
        for lang in i18n.LANGUAGES:
            self.assertIn(lang, i18n.DIRECTION)


class TestStrings(unittest.TestCase):
    def test_every_required_key_is_present_in_every_language(self):
        for lang in i18n.LANGUAGES:
            table = i18n.strings(lang)
            missing = [k for k in REQUIRED if k not in table]
            self.assertEqual(missing, [], "%s is missing %s" % (lang, missing))

    def test_the_two_languages_have_identical_key_sets(self):
        # A key present in one language renders as a blank label in the other,
        # and only a reader of that language would ever notice.
        self.assertEqual(set(i18n.strings("ar")), set(i18n.strings("en")))

    def test_no_value_is_empty(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.strings(lang).items():
                self.assertTrue(str(value).strip(), "%s/%s is empty" % (lang, key))

    def test_arabic_is_actually_arabic(self):
        # Guards against an untranslated table copied from English.
        table = i18n.strings("ar")
        arabic = [v for v in table.values() if any("؀" <= ch <= "ۿ" for ch in str(v))]
        self.assertGreater(len(arabic), len(table) // 2,
                           "most Arabic strings are not in Arabic script")

    def test_unknown_language_falls_back_rather_than_raising(self):
        self.assertEqual(set(i18n.strings("kl")), set(i18n.strings("en")))

    def test_strings_is_a_copy(self):
        table = i18n.strings("en")
        table["app_title"] = "tampered"
        self.assertNotEqual(i18n.strings("en")["app_title"], "tampered")


class TestServedShape(unittest.TestCase):
    def test_all_strings_carries_every_language(self):
        self.assertEqual(set(i18n.all_strings()), set(i18n.LANGUAGES))

    def test_all_strings_is_json_serialisable(self):
        # It is embedded in /api/boot, so a non-serialisable value breaks boot.
        json.dumps(i18n.all_strings())


if __name__ == "__main__":
    unittest.main()

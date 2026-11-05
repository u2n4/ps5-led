"""Headless command line: parsing, exit codes, and the no-argument window path. No controller is needed.

The Windows HID layer is replaced with a fake. The real device manager still runs, and it finds only the
fake, so the colour bytes checked here are the ones the app would send to a controller.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import appload
from ps5led import dualsense as ds

dp = appload.dualled_pro

PROFILE = {"mode": "Manual", "speed": 1.0, "rainbow_brightness": 0.9, "flash_duty": 0.5, "color": "#3b82f6"}


def input_report():
    body = bytearray(63)
    body[27:31] = (20_000_000).to_bytes(4, "little")
    return bytes([0x01]) + bytes(body)


class FakeDevice:
    """Records every output report. A read waits briefly and returns an idle controller."""
    last_error = "fixture has no calibration"

    def __init__(self):
        self.writes = []

    def write(self, packet):
        self.writes.append(bytes(packet))

    def get_feature(self, *args):
        return None

    def read(self, timeout_ms):
        time.sleep(0.01)
        return input_report()

    def close(self):
        pass


def controller_info():
    return types.SimpleNamespace(product_id=0x0CE6, product="Fixture DualSense", transport="usb",
                                 path="fixture", input_length=64, output_length=48)


@contextlib.contextmanager
def fake_controller(device, found=True):
    """Stand in for the Windows HID module. The device manager runs for real and finds only this fake."""
    module = types.ModuleType("ps5led.hid_win")
    module.HidDevice = types.SimpleNamespace(open=lambda path: device)
    module.enumerate_devices = lambda vid: [controller_info()] if found else []
    with patch.dict(sys.modules, {"ps5led.hid_win": module}):
        yield


def lightbar_colours(device):
    """Colours in the reports that set the lightbar. The connect-time setup report carries none."""
    offset = ds._COMMON_OFFSET[ds.TRANSPORT_USB]
    return {(w[offset + ds._RED], w[offset + ds._GREEN], w[offset + ds._BLUE])
            for w in device.writes if w[offset + ds._VALID_FLAG1] & ds.FLAG1_LIGHTBAR}


class ParseTests(unittest.TestCase):
    def test_no_options_means_the_window(self):
        args = dp.parse_cli([])
        self.assertFalse(args.headless)
        self.assertFalse(args.stop)
        self.assertFalse(args.background)

    def test_a_colour_takes_six_hex_digits_with_or_without_a_hash(self):
        self.assertEqual(dp.parse_cli(["--color", "FF8800"]).color, "#ff8800")
        self.assertEqual(dp.parse_cli(["--color", "#00aaff"]).color, "#00aaff")
        self.assertTrue(dp.parse_cli(["--color", "ff8800"]).headless)

    def test_a_bad_colour_is_a_usage_error(self):
        for bad in ("red", "#12345", "ff88000", "gg0000"):
            with self.subTest(bad), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    dp.parse_cli(["--color", bad])
                self.assertEqual(ctx.exception.code, 2)

    def test_only_one_headless_action_at_a_time(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            dp.parse_cli(["--color", "ff0000", "--profile", "Fortnite"])
        self.assertEqual(ctx.exception.code, 2)

    def test_a_headless_action_cannot_be_combined_with_background_or_stop_options(self):
        for extra in (["--background"], ["--stop"], ["--stop-after", "5"], ["--keep-on-exit"], ["--off-on-exit"]):
            with self.subTest(extra), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    dp.parse_cli(["--color", "ff0000", *extra])
                self.assertEqual(ctx.exception.code, 2)

    def test_stop_is_not_a_headless_action(self):
        self.assertFalse(dp.parse_cli(["--stop"]).headless)


class DispatchTests(unittest.TestCase):
    def test_no_arguments_starts_the_window_as_before(self):
        with patch.object(dp, "main", return_value=True) as main, patch.object(dp, "run_main") as run_main:
            self.assertEqual(dp.dispatch([]), 0)
        main.assert_called_once_with()
        run_main.assert_called_once()
        self.assertFalse(run_main.call_args.args[0].headless)

    def test_a_running_instance_means_no_second_window(self):
        with patch.object(dp, "main", return_value=False), patch.object(dp, "run_main") as run_main:
            self.assertEqual(dp.dispatch([]), 0)
        run_main.assert_not_called()

    def test_stop_skips_the_single_instance_lock(self):
        with patch.object(dp, "main") as main, patch.object(dp, "run_main") as run_main:
            dp.dispatch(["--stop"])
        main.assert_not_called()
        run_main.assert_called_once()

    def test_a_headless_action_never_opens_the_window(self):
        with patch.object(dp, "run_headless", return_value=0) as headless, \
                patch.object(dp, "main") as main, patch.object(dp, "run_main") as run_main:
            self.assertEqual(dp.dispatch(["--export-profiles", "unused.json"]), 0)
        headless.assert_called_once()
        main.assert_not_called()
        run_main.assert_not_called()


class HeadlessTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ps5led-cli-tests-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cfg = {"color": "#00aaff", "profiles": {"Fortnite": dict(PROFILE), "Default": dict(PROFILE, color="#00aaff")}}
        self.save = Mock()
        self.mutex = Mock(return_value=True)  # no other PS5 LED is running
        for name, value in (("CFG", self.cfg), ("save_cfg", self.save), ("_acquire_global_mutex", self.mutex)):
            patcher = patch.object(dp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dp.dispatch(argv)
        return code, out.getvalue(), err.getvalue()

    def test_export_writes_the_saved_profiles(self):
        target = self.dir / "out.json"
        code, out, err = self.run_cli(["--export-profiles", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["profiles"]["Fortnite"]["color"], "#3b82f6")
        self.assertIn("Exported 2 profile(s)", out)

    def test_export_of_a_broken_saved_profile_exits_1_and_names_it(self):
        self.cfg["profiles"]["Broken"] = dict(PROFILE, mode="Disco")
        target = self.dir / "out.json"
        code, _, err = self.run_cli(["--export-profiles", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("Profile 'Broken' has an unknown mode 'Disco'", err)
        self.assertFalse(target.exists())

    def test_import_merges_a_valid_file(self):
        source = self.dir / "in.json"
        source.write_text(json.dumps({"format": "ps5led-profiles", "version": 1,
                                      "profiles": {"Night": dict(PROFILE, color="#101020")}}), encoding="utf-8")
        code, out, err = self.run_cli(["--import-profiles", str(source)])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.cfg["profiles"]["Night"]["color"], "#101020")
        self.assertIn("1 added, 0 replaced", out)
        self.save.assert_called_once()

    def test_import_of_a_bad_file_exits_1_and_changes_nothing(self):
        before = json.dumps(self.cfg, sort_keys=True)
        source = self.dir / "bad.json"
        source.write_text("{oops", encoding="utf-8")
        code, _, err = self.run_cli(["--import-profiles", str(source)])
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)
        self.assertEqual(json.dumps(self.cfg, sort_keys=True), before)
        self.save.assert_not_called()

    def test_import_is_refused_while_the_app_is_running(self):
        self.mutex.return_value = False
        source = self.dir / "in.json"
        source.write_text(json.dumps({"format": "ps5led-profiles", "version": 1,
                                      "profiles": {"Night": dict(PROFILE)}}), encoding="utf-8")
        code, _, err = self.run_cli(["--import-profiles", str(source)])
        self.assertEqual(code, 1)
        self.assertIn("already running", err)
        self.assertNotIn("Night", self.cfg["profiles"])

    def test_an_unknown_profile_name_lists_the_saved_ones(self):
        with patch.object(dp, "_apply_colour_headless") as apply:
            code, _, err = self.run_cli(["--profile", "Missing"])
        self.assertEqual(code, 1)
        self.assertIn("no saved profile named 'Missing'", err)
        self.assertIn("Fortnite", err)
        apply.assert_not_called()

    def test_a_running_app_blocks_setting_the_colour(self):
        self.mutex.return_value = False
        with patch.object(dp, "_apply_colour_headless") as apply:
            code, _, err = self.run_cli(["--color", "ff8800"])
        self.assertEqual(code, 1)
        self.assertIn("already running", err)
        apply.assert_not_called()

    def test_a_colour_reaches_the_controller_and_is_not_switched_off_on_exit(self):
        device = FakeDevice()
        with fake_controller(device), patch.object(dp, "CLI_CONNECT_TIMEOUT_S", 10):
            code, out, err = self.run_cli(["--color", "ff8800"])
        self.assertEqual(code, 0, err)
        self.assertIn("Lightbar set to #ff8800", out)
        self.assertTrue(lightbar_colours(device))
        # Every lightbar report carries the requested colour: the saved colour is never sent, not even briefly.
        self.assertEqual(lightbar_colours(device), {(255, 136, 0)})
        self.assertEqual(self.cfg["color"], "#00aaff", "a one-off apply must not change the saved colour")

    def test_a_profile_sets_its_colour(self):
        device = FakeDevice()
        with fake_controller(device), patch.object(dp, "CLI_CONNECT_TIMEOUT_S", 10):
            code, _, err = self.run_cli(["--profile", "Fortnite"])
        self.assertEqual(code, 0, err)
        self.assertTrue(lightbar_colours(device))
        self.assertEqual(lightbar_colours(device), {(0x3B, 0x82, 0xF6)})

    def test_no_controller_within_the_timeout_exits_1(self):
        device = FakeDevice()
        with fake_controller(device, found=False), patch.object(dp, "CLI_CONNECT_TIMEOUT_S", 0.5):
            code, _, err = self.run_cli(["--color", "ff8800"])
        self.assertEqual(code, 1)
        self.assertIn("no controller accepted the colour within 0.5 seconds", err)
        self.assertEqual(device.writes, [])


if __name__ == "__main__":
    unittest.main()

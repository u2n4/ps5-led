"""Regressions for the review-fleet findings that survived verification.

Every fix below passed the suite both before and after it was applied, which
is the whole reason this file exists: the defects were real and nothing
watched them. They are grouped here rather than scattered so the provenance
stays attached -- each test names the failure it prevents.

Findings that did NOT survive verification are deliberately absent: the
device.py "nested lock deadlocks" (no lock is ever re-entered, checked
structurally), the cli.py "--background was removed" and "missing import
time" (both present in the file), and "browser_args crashes on a % in the
URL" (the percent is in the format string, not the argument).
"""

import http.client
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from ps5led import bridge as br
from ps5led import config as cfg
from ps5led import launcher
from ps5led.device import DeviceManager, clamp_rgb
from ps5led.state import AppState


class TestConfigGetReturnsACopy(unittest.TestCase):
    """get() handed out the live object, so callers could mutate stored state.

    Worse than the aliasing itself: mutating in place never sets _dirty, so
    flush() skipped the write and the change lived until the process exited.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_mutating_a_returned_dict_does_not_reach_the_store(self):
        c = cfg.Config(self.path)
        window = c.get("window")
        window["width"] = 1
        self.assertNotEqual(c.get("window")["width"], 1)

    def test_mutating_a_returned_list_does_not_reach_the_store(self):
        c = cfg.Config(self.path)
        colour = c.get("colour")
        colour.append(999)
        self.assertEqual(len(c.get("colour")), 3)

    def test_a_stored_value_is_still_returned(self):
        # The copy must not become a copy of the default instead.
        c = cfg.Config(self.path)
        c.set("mode", "wave")
        self.assertEqual(c.get("mode"), "wave")


class TestConfigLoadMergesNestedDefaults(unittest.TestCase):
    """A shallow update() replaced whole sub-objects, dropping their siblings."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_a_partial_nested_object_keeps_its_sibling_defaults(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"window": {"fullscreen": True}}, fh)
        loaded = cfg.load(self.path)
        self.assertIs(loaded["window"]["fullscreen"], True)
        self.assertEqual(loaded["window"]["width"], cfg.DEFAULTS["window"]["width"])
        self.assertEqual(loaded["window"]["height"], cfg.DEFAULTS["window"]["height"])

    def test_a_stored_scalar_still_replaces_its_default(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"mode": "wave"}, fh)
        self.assertEqual(cfg.load(self.path)["mode"], "wave")

    def test_an_unknown_key_survives_the_round_trip(self):
        # Stated in the module docstring: a config from a newer build must not
        # be silently emptied by an older one.
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"from_the_future": 7}, fh)
        self.assertEqual(cfg.load(self.path)["from_the_future"], 7)

    def test_the_defaults_are_not_mutated_by_a_load(self):
        # The nested merge writes into merged[key]; if merged were not a deep
        # copy that write would land in DEFAULTS and leak into every later load.
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"window": {"width": 1}}, fh)
        cfg.load(self.path)
        self.assertEqual(cfg.DEFAULTS["window"]["width"], 1280)


class TestConfigSaveIsAtomic(unittest.TestCase):
    """Truncating in place could destroy every saved preference.

    load() answers a corrupt file with defaults and no complaint, so the loss
    is silent -- and this module is throttled precisely because a crash
    mid-write is expected.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_a_successful_save_leaves_no_temp_file(self):
        cfg.save({"mode": "wave"}, self.path)
        leftovers = [p.name for p in pathlib.Path(self.dir).iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_a_failed_rename_leaves_the_previous_config_intact(self):
        cfg.save({"mode": "keep-me"}, self.path)
        with mock.patch("ps5led.config.os.replace", side_effect=OSError("boom")):
            cfg.save({"mode": "clobber"}, self.path)
        self.assertEqual(cfg.load(self.path)["mode"], "keep-me")

    def test_a_failed_rename_cleans_up_its_temp_file(self):
        with mock.patch("ps5led.config.os.replace", side_effect=OSError("boom")):
            cfg.save({"mode": "wave"}, self.path)
        leftovers = [p.name for p in pathlib.Path(self.dir).iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual([], leftovers)

    def test_an_unwritable_path_still_does_not_raise(self):
        # The atomic write put with_name() outside the guard once; pathlib
        # validates there, so a NUL in the path raised before the try began.
        cfg.save({"mode": "wave"}, os.path.join(self.dir, "nope\x00bad", "c.json"))


class TestClampRgbNeverRaises(unittest.TestCase):
    """write_colour documents "never raises"; OverflowError escaped it.

    float('inf') and an int too large to become a float both raise
    OverflowError, not ValueError -- and json.load accepts JSON's Infinity
    literal, so a hand-edited config could carry one all the way here.
    """

    def test_infinity_is_not_a_colour(self):
        self.assertIsNone(clamp_rgb((float("inf"), 0, 0)))

    def test_negative_infinity_is_not_a_colour(self):
        self.assertIsNone(clamp_rgb((float("-inf"), 0, 0)))

    def test_an_int_too_large_for_a_float_is_not_a_colour(self):
        self.assertIsNone(clamp_rgb((10 ** 400, 0, 0)))

    def test_nan_is_not_a_colour(self):
        self.assertIsNone(clamp_rgb((float("nan"), 0, 0)))

    def test_write_colour_returns_false_instead_of_raising(self):
        manager = DeviceManager(AppState())
        self.assertFalse(manager.write_colour((float("inf"), 0, 0)))

    def test_an_ordinary_colour_still_clamps(self):
        # The guard must not have swallowed the normal path.
        self.assertEqual(clamp_rgb((300, -5, 12.6)), (255, 0, 13))


class TestBridgeHonoursItsHost(unittest.TestCase):
    """__init__ accepted a host and bind() used it; the guard and url did not.

    Passing anything but the default produced a URL nobody could load and a
    Host check nothing could satisfy.
    """

    def test_host_is_reported(self):
        b = br.Bridge(AppState(), cfg.Config(), host="localhost")
        self.assertEqual(b.host, "localhost")

    def test_url_carries_the_configured_host(self):
        b = br.Bridge(AppState(), cfg.Config(), host="localhost")
        self.assertIn("http://localhost:", b.url)

    def test_the_default_host_is_still_loopback(self):
        b = br.Bridge(AppState(), cfg.Config())
        self.assertEqual(b.host, "127.0.0.1")
        self.assertIn("http://127.0.0.1:", b.url)


class TestLauncherFallbackIsDetectable(unittest.TestCase):
    """launch() returns None when it had to use the default browser.

    That None is the whole signal: run_window used to hand it straight to
    wait_for_close, which returned 0 at once, and the caller's finally tore
    the bridge down under the page that had just opened.
    """

    def test_launch_returns_none_when_no_browser_is_found(self):
        with mock.patch.object(launcher, "find_browser", return_value=None):
            with mock.patch.object(launcher.webbrowser, "open") as opened:
                self.assertIsNone(launcher.launch("http://127.0.0.1:1/?t=x"))
        opened.assert_called_once()

    def test_wait_for_close_on_no_process_returns_immediately(self):
        # Correct in itself -- there is nothing to wait for. It is the caller
        # that must not treat this as "the user closed the window".
        self.assertEqual(launcher.wait_for_close(None), 0)


class TestPostBodyIsCapped(unittest.TestCase):
    """do_POST read Content-Length bytes with no ceiling.

    ThreadingHTTPServer gives every connection its own thread, so a request
    promising a body it never finishes sending holds one open indefinitely.
    The guard runs first, so this needs the token -- which makes it hygiene
    rather than a hole, and cheap enough that there is no reason to keep it.
    """

    def setUp(self):
        self.bridge = br.Bridge(AppState(), cfg.Config(path=None, throttle_seconds=9999))
        self.bridge.start()
        self.addCleanup(self.bridge.stop)
        self.host = "127.0.0.1:%d" % self.bridge.port
        self.path = "/api/cmd?t=%s" % self.bridge.token

    def post(self, body):
        # Transport errors are retried; a status never is. A localhost
        # http.server occasionally aborts a connection under a loaded suite,
        # and retrying the status would hide the very thing being asserted.
        last = None
        for _ in range(3):
            conn = http.client.HTTPConnection(self.host, timeout=10)
            try:
                conn.request("POST", self.path, body=body,
                             headers={"Host": self.host,
                                      "Content-Type": "application/json"})
                return conn.getresponse().status
            except (ConnectionError, http.client.HTTPException, OSError) as exc:
                last = exc
            finally:
                conn.close()
        raise AssertionError("transport kept failing: %r" % (last,))

    def test_an_oversized_body_is_refused(self):
        body = b'{"cmd":"colour","rgb":"' + b"a" * (br.MAX_BODY_BYTES + 1) + b'"}'
        self.assertEqual(self.post(body), 413)

    def test_an_ordinary_command_is_not_refused(self):
        # The cap must not be so tight that real traffic trips it.
        self.assertNotEqual(self.post(json.dumps({"cmd": "visible",
                                                  "value": True}).encode()), 413)

    def test_the_cap_leaves_room_for_a_real_command(self):
        self.assertGreater(br.MAX_BODY_BYTES, 4096)


if __name__ == "__main__":
    unittest.main()

import http.client
import json
import time
import unittest
import urllib.error
import urllib.request

from ps5led.bridge import Bridge, WEB_ROOT
from ps5led.config import Config
from ps5led.state import AppState


def get(url, headers=None, timeout=5):
    """Returns (status, body). A 4xx comes back as a status, not an exception."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def post(url, payload, headers=None, timeout=5):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers or {})
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


class BridgeCase(unittest.TestCase):
    def setUp(self):
        self.state = AppState()
        self.config = Config(path=None, throttle_seconds=9999)
        self.bridge = Bridge(self.state, self.config)
        self.bridge.start()
        self.addCleanup(self.bridge.stop)
        self.base = "http://127.0.0.1:%d" % self.bridge.port
        self.token = self.bridge.token
        self.origin = {"Origin": self.base}


class TestBinding(BridgeCase):
    def test_it_chose_a_real_port(self):
        self.assertGreater(self.bridge.port, 0)

    def test_url_carries_the_token(self):
        self.assertIn("t=" + self.token, self.bridge.url)

    def test_the_token_is_long_enough_to_be_unguessable(self):
        self.assertGreaterEqual(len(self.bridge.token), 20)

    def test_two_bridges_get_different_tokens(self):
        other = Bridge(self.state, self.config)
        self.assertNotEqual(other.token, self.bridge.token)


class TestGuard(BridgeCase):
    def test_no_token_is_refused(self):
        status, _ = get(self.base + "/api/boot", self.origin)
        self.assertEqual(status, 403)

    def test_wrong_token_is_refused(self):
        status, _ = get(self.base + "/api/boot?t=nope", self.origin)
        self.assertEqual(status, 403)

    def test_right_token_is_allowed(self):
        status, _ = get(self.base + "/api/boot?t=" + self.token, self.origin)
        self.assertEqual(status, 200)

    def test_a_foreign_origin_is_refused(self):
        status, _ = get(self.base + "/api/boot?t=" + self.token,
                        {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_a_missing_origin_is_allowed(self):
        # curl and the initial navigation send no Origin.
        status, _ = get(self.base + "/api/boot?t=" + self.token)
        self.assertEqual(status, 200)

    def test_a_foreign_host_header_is_refused(self):
        headers = dict(self.origin)
        headers["Host"] = "example.com"
        status, _ = get(self.base + "/api/boot?t=" + self.token, headers)
        self.assertEqual(status, 403)

    def test_static_files_do_not_need_the_token(self):
        # This assertion used to be its exact opposite, and that is what broke
        # the app: a browser asks for css/app.css and js/app.js with no token,
        # because index.html references them relatively, and an ES module's
        # imports cannot carry one at all. The page was served and then refused
        # everything it needed to run.
        for path in ("/index.html", "/css/app.css", "/js/app.js"):
            status, _ = get(self.base + path)
            self.assertEqual(status, 200, path)

    def test_the_api_still_needs_the_token(self):
        for path in ("/api/boot", "/api/stream"):
            status, _ = get(self.base + path, self.origin)
            self.assertEqual(status, 403, path)

    def test_an_unauthenticated_traversal_is_still_refused(self):
        # Static is open now, so _serve_static's traversal guard is the only
        # thing left between an anonymous caller and the rest of the disk.
        for path in ("/../ps5led/bridge.py",
                     "/%2e%2e/ps5led/bridge.py",
                     "/../../../Windows/win.ini"):
            status, _ = get(self.base + path)
            self.assertIn(status, (403, 404), path)


class TestStatic(BridgeCase):
    def test_root_serves_the_page(self):
        status, body = get(self.base + "/?t=" + self.token)
        self.assertEqual(status, 200)
        self.assertIn("<!doctype html", body.lower())

    def test_a_missing_file_is_404(self):
        status, _ = get(self.base + "/nope.js?t=" + self.token)
        self.assertEqual(status, 404)

    def test_directory_traversal_is_refused(self):
        status, _ = get(self.base + "/../ps5led/bridge.py?t=" + self.token)
        self.assertIn(status, (403, 404))

    def test_an_encoded_traversal_is_refused(self):
        status, _ = get(self.base + "/%2e%2e/ps5led/bridge.py?t=" + self.token)
        self.assertIn(status, (403, 404))

    def test_web_root_exists(self):
        self.assertTrue(WEB_ROOT.is_dir(), "web/ is missing from the repo")


class TestBoot(BridgeCase):
    def test_boot_is_json_with_the_expected_sections(self):
        status, body = get(self.base + "/api/boot?t=" + self.token)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        for key in ("config", "i18n", "version", "device", "modes"):
            self.assertIn(key, payload)

    def test_boot_carries_both_languages(self):
        _, body = get(self.base + "/api/boot?t=" + self.token)
        self.assertEqual(set(json.loads(body)["i18n"]), {"ar", "en"})

    def test_boot_never_leaks_the_token(self):
        _, body = get(self.base + "/api/boot?t=" + self.token)
        self.assertNotIn(self.token, body)


class TestStop(unittest.TestCase):
    def test_stop_releases_the_port(self):
        bridge = Bridge(AppState(), Config(path=None, throttle_seconds=9999))
        bridge.start()
        port = bridge.port
        bridge.stop()
        again = Bridge(AppState(), Config(path=None, throttle_seconds=9999),
                       port=port)
        again.start()
        self.addCleanup(again.stop)
        self.assertEqual(again.port, port)

    def test_stop_is_idempotent(self):
        bridge = Bridge(AppState(), Config(path=None, throttle_seconds=9999))
        bridge.start()
        bridge.stop()
        bridge.stop()


from ps5led.device import DEFAULT_RGB
from ps5led.engine import Engine


class FakeEngine(object):
    def __init__(self):
        self.mode = None
        self.colour = None
        self.speed = None
        self.settings = {}

    def set_mode(self, mode):
        self.mode = mode

    def set_colour(self, rgb):
        self.colour = tuple(rgb)

    def set_speed(self, speed):
        self.speed = speed

    def set_setting(self, key, value):
        self.settings[key] = value


class CommandCase(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.config = Config(path=None, throttle_seconds=9999)
        self.bridge = Bridge(AppState(), self.config, engine=self.engine)

    def run_cmd(self, **payload):
        return self.bridge.handle_command(payload)


class TestCommandValidation(CommandCase):
    def test_an_unknown_command_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="rm -rf")["ok"])

    def test_a_missing_cmd_is_refused(self):
        self.assertFalse(self.run_cmd(colour=[1, 2, 3])["ok"])

    def test_a_non_dict_payload_is_refused(self):
        self.assertFalse(self.bridge.handle_command([1, 2, 3])["ok"])


class TestModeCommand(CommandCase):
    def test_a_real_mode_is_accepted_and_persisted(self):
        self.assertTrue(self.run_cmd(cmd="set_mode", mode="rainbow")["ok"])
        self.assertEqual(self.engine.mode, "rainbow")
        self.assertEqual(self.config.get("mode"), "rainbow")

    def test_an_invented_mode_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="set_mode", mode="disco")["ok"])
        self.assertIsNone(self.engine.mode)


class TestColourCommand(CommandCase):
    def test_a_triple_is_accepted(self):
        self.assertTrue(self.run_cmd(cmd="set_colour", colour=[1, 2, 3])["ok"])
        self.assertEqual(self.engine.colour, (1, 2, 3))

    def test_a_hex_string_is_accepted(self):
        self.assertTrue(self.run_cmd(cmd="set_colour", colour="00aaff")["ok"])
        self.assertEqual(self.engine.colour, (0, 170, 255))

    def test_out_of_range_is_clamped_not_refused(self):
        self.assertTrue(self.run_cmd(cmd="set_colour", colour=[999, -1, 40])["ok"])
        self.assertEqual(self.engine.colour, (255, 0, 40))

    def test_nonsense_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="set_colour", colour="mauve")["ok"])

    def test_the_colour_is_persisted_as_a_list(self):
        self.run_cmd(cmd="set_colour", colour=[1, 2, 3])
        self.assertEqual(list(self.config.get("colour")), [1, 2, 3])
        json.dumps(self.config.snapshot())


class TestNumericCommands(CommandCase):
    def test_speed_is_clamped_to_the_engine_range(self):
        self.run_cmd(cmd="set_speed", speed=99)
        self.assertLessEqual(self.engine.speed, 5.0)
        self.run_cmd(cmd="set_speed", speed=-4)
        self.assertGreaterEqual(self.engine.speed, 0.1)

    def test_a_non_number_speed_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="set_speed", speed="fast")["ok"])

    def test_brightness_is_clamped_to_0_2_through_1(self):
        self.run_cmd(cmd="set_brightness", brightness=5)
        self.assertLessEqual(self.engine.settings["brightness"], 1.0)
        self.run_cmd(cmd="set_brightness", brightness=0)
        self.assertGreaterEqual(self.engine.settings["brightness"], 0.2)

    def test_duty_is_clamped_to_0_1_through_0_9(self):
        self.run_cmd(cmd="set_duty", duty=9)
        self.assertLessEqual(self.engine.settings["duty"], 0.9)


class TestLanguageAndShell(CommandCase):
    def test_a_known_language_is_persisted(self):
        self.assertTrue(self.run_cmd(cmd="set_language", language="en")["ok"])
        self.assertEqual(self.config.get("language"), "en")

    def test_an_unknown_language_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="set_language", language="kl")["ok"])

    def test_a_known_shell_is_persisted(self):
        self.assertTrue(self.run_cmd(cmd="set_shell", shell="black")["ok"])
        self.assertEqual(self.config.get("shell"), "black")

    def test_an_unknown_shell_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="set_shell", shell="plaid")["ok"])


class TestProfiles(CommandCase):
    def test_save_then_load_restores_the_settings(self):
        self.run_cmd(cmd="set_mode", mode="wave")
        self.run_cmd(cmd="set_colour", colour=[9, 8, 7])
        self.assertTrue(self.run_cmd(cmd="profile_save", name="night")["ok"])

        self.run_cmd(cmd="set_mode", mode="manual")
        self.assertTrue(self.run_cmd(cmd="profile_load", name="night")["ok"])
        self.assertEqual(self.engine.mode, "wave")
        self.assertEqual(self.engine.colour, (9, 8, 7))

    def test_loading_an_unknown_profile_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="profile_load", name="nope")["ok"])

    def test_delete_removes_it(self):
        self.run_cmd(cmd="profile_save", name="night")
        self.assertTrue(self.run_cmd(cmd="profile_delete", name="night")["ok"])
        self.assertFalse(self.run_cmd(cmd="profile_load", name="night")["ok"])

    def test_an_empty_name_is_refused(self):
        self.assertFalse(self.run_cmd(cmd="profile_save", name="  ")["ok"])

    def test_profiles_stay_json_serialisable(self):
        self.run_cmd(cmd="profile_save", name="night")
        json.dumps(self.config.snapshot())

    def test_a_stale_mode_reports_failure_not_silent_success(self):
        # A profile saved while "disco" was a real mode (or hand-edited on
        # disk) must not report success once the mode no longer exists --
        # loading it changes nothing, and the caller deserves to know that.
        self.run_cmd(cmd="set_mode", mode="wave")
        self.run_cmd(cmd="profile_save", name="stale")
        profiles = self.config.get("profiles")
        profiles["stale"]["mode"] = "disco"
        self.config.set("profiles", profiles)

        result = self.run_cmd(cmd="profile_load", name="stale")

        self.assertFalse(result["ok"])
        self.assertIn("mode", result["error"])

    def test_a_stale_colour_reports_failure_alongside_a_stale_mode(self):
        self.run_cmd(cmd="profile_save", name="stale")
        profiles = self.config.get("profiles")
        profiles["stale"]["mode"] = "disco"
        profiles["stale"]["colour"] = "mauve"
        self.config.set("profiles", profiles)

        result = self.run_cmd(cmd="profile_load", name="stale")

        self.assertFalse(result["ok"])
        self.assertIn("mode", result["error"])
        self.assertIn("colour", result["error"])

    def test_a_fully_valid_profile_still_reports_success(self):
        self.run_cmd(cmd="set_mode", mode="wave")
        self.run_cmd(cmd="profile_save", name="good")
        result = self.run_cmd(cmd="profile_load", name="good")
        self.assertTrue(result["ok"])


class TestOffAndVisible(CommandCase):
    def test_off_sets_black_without_changing_the_saved_colour(self):
        self.run_cmd(cmd="set_colour", colour=[9, 8, 7])
        self.assertTrue(self.run_cmd(cmd="off")["ok"])
        self.assertEqual(self.engine.colour, (0, 0, 0))
        self.assertEqual(list(self.config.get("colour")), [9, 8, 7],
                         "off is not a colour choice; it must not overwrite one")

    def test_visible_is_recorded(self):
        self.assertTrue(self.run_cmd(cmd="visible", visible=False)["ok"])
        self.assertFalse(self.bridge.page_visible)
        self.assertTrue(self.run_cmd(cmd="visible", visible=True)["ok"])
        self.assertTrue(self.bridge.page_visible)


class TestCommandOverHttp(BridgeCase):
    def test_a_command_without_the_token_is_refused(self):
        status, _ = post(self.base + "/api/cmd", {"cmd": "set_mode", "mode": "rainbow"},
                         self.origin)
        self.assertEqual(status, 403)

    def test_a_command_with_a_foreign_origin_is_refused(self):
        status, _ = post(self.base + "/api/cmd?t=" + self.token,
                         {"cmd": "set_mode", "mode": "rainbow"},
                         {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_a_valid_command_returns_ok(self):
        status, body = post(self.base + "/api/cmd?t=" + self.token,
                            {"cmd": "set_language", "language": "en"}, self.origin)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_a_malformed_body_is_a_clean_400_not_a_traceback(self):
        request = urllib.request.Request(
            self.base + "/api/cmd?t=" + self.token, data=b"{not json",
            headers={"Origin": self.base, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 400)


def open_stream(host_port, token, timeout=5):
    """Returns the raw HTTPResponse for /api/stream so a test can read events."""
    conn = http.client.HTTPConnection(host_port, timeout=timeout)
    conn.request("GET", "/api/stream?t=" + token, headers={"Host": host_port})
    return conn, conn.getresponse()


def read_event(response, deadline):
    """One SSE event as (name, data-dict), or None if the deadline passes."""
    name, data = None, []
    while time.time() < deadline:
        line = response.fp.readline()
        if not line:
            return None
        line = line.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif line == "" and name:
            return name, json.loads("".join(data))
    return None


class TestStream(BridgeCase):
    def test_the_stream_needs_the_token(self):
        conn = http.client.HTTPConnection("127.0.0.1:%d" % self.bridge.port, timeout=5)
        conn.request("GET", "/api/stream")
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()

    def test_content_type_is_event_stream(self):
        conn, response = open_stream("127.0.0.1:%d" % self.bridge.port, self.token)
        self.addCleanup(conn.close)
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.getheader("Content-Type"))

    def test_a_state_event_arrives_and_carries_the_expected_fields(self):
        self.state.update(rgb=(1, 2, 3), mode="wave", battery=55, connected=True)
        conn, response = open_stream("127.0.0.1:%d" % self.bridge.port, self.token)
        self.addCleanup(conn.close)
        deadline = time.time() + 5
        while time.time() < deadline:
            event = read_event(response, deadline)
            self.assertIsNotNone(event, "no event arrived")
            if event[0] == "state":
                for key in ("rgb", "mode", "battery", "connected"):
                    self.assertIn(key, event[1])
                return
        self.fail("no state event in 5s")

    def test_a_sensor_event_arrives_while_visible(self):
        self.state.update(gyro=(1.0, 2.0, 3.0), accel=(0.0, 1.0, 0.0), buttons=0)
        conn, response = open_stream("127.0.0.1:%d" % self.bridge.port, self.token)
        self.addCleanup(conn.close)
        deadline = time.time() + 5
        seen = set()
        while time.time() < deadline and "sensor" not in seen:
            event = read_event(response, deadline)
            if event is None:
                break
            seen.add(event[0])
        self.assertIn("sensor", seen)

    def test_no_sensor_events_once_the_page_reports_hidden(self):
        self.bridge.handle_command({"cmd": "visible", "visible": False})
        conn, response = open_stream("127.0.0.1:%d" % self.bridge.port, self.token)
        self.addCleanup(conn.close)
        deadline = time.time() + 3
        seen = set()
        while time.time() < deadline:
            event = read_event(response, deadline)
            if event is None:
                break
            seen.add(event[0])
            self.state.update(gyro=(time.time(), 0.0, 0.0))
        self.assertNotIn("sensor", seen, "sensor events kept flowing while hidden")

    def test_every_streamed_payload_is_json_serialisable(self):
        # touch is a tuple of tuples-or-None; a naive serialiser breaks on it.
        self.state.update(touch=((1, 2), None), gyro=(0.1, 0.2, 0.3))
        json.dumps(self.bridge.sensor_payload(self.state.snapshot()))
        json.dumps(self.bridge.state_payload(self.state.snapshot()))

    def test_state_payload_only_carries_state_fields(self):
        payload = self.bridge.state_payload(
            {"rgb": (1, 2, 3), "gyro": (1.0, 2.0, 3.0), "seq": 4})
        self.assertIn("rgb", payload)
        self.assertNotIn("gyro", payload, "sensor data must not ride the state event")

    def test_a_disconnecting_client_does_not_kill_the_server(self):
        conn, response = open_stream("127.0.0.1:%d" % self.bridge.port, self.token)
        read_event(response, time.time() + 5)
        conn.close()
        time.sleep(0.3)
        status, _ = get(self.base + "/api/boot?t=" + self.token)
        self.assertEqual(status, 200, "the server died with its client")


if __name__ == "__main__":
    unittest.main()

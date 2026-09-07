import json
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

    def test_the_guard_applies_to_static_files_too(self):
        status, _ = get(self.base + "/index.html")
        self.assertEqual(status, 403)


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


if __name__ == "__main__":
    unittest.main()

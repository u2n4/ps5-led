"""The local HTTP bridge.

Python owns the hardware and no UI; the page owns the UI and no hardware. This
is the only thing between them, so it is also the only attack surface, and every
request passes the same three-part guard: a per-launch token, a Host header that
is ours, and an Origin that is ours or absent.

The token is what makes a guessed port useless. The Origin check is what stops
another page on the machine from driving the controller.
"""

import json
import mimetypes
import pathlib
import posixpath
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from . import i18n
from .engine import MODES

WEB_ROOT = pathlib.Path(__file__).resolve().parent.parent / "web"
TOKEN_BYTES = 16

SHELLS = ("white", "black", "red")

_SPEED_RANGE = (0.1, 5.0)
_BRIGHTNESS_RANGE = (0.2, 1.0)
_DUTY_RANGE = (0.1, 0.9)

# Which config key each numeric command writes, and the range it is held to.
# The ranges match Engine.set_speed and colour_for's own expectations; a value
# outside them is a slider that has been driven past its own labels, so it is
# clamped rather than refused.
_NUMERIC = {
    "set_speed": ("speed", _SPEED_RANGE),
    "set_brightness": ("brightness", _BRIGHTNESS_RANGE),
    "set_duty": ("duty", _DUTY_RANGE),
}

_PROFILE_KEYS = ("mode", "colour", "speed", "brightness", "duty")


def parse_colour(value):
    """[r,g,b], (r,g,b) or "00aaff"/"#00aaff" to a clamped (r, g, b), or None."""
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) != 6:
            return None
        try:
            number = int(text, 16)
        except ValueError:
            return None
        value = ((number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF)
    try:
        r, g, b = value
    except (TypeError, ValueError):
        return None
    out = []
    for channel in (r, g, b):
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            return None
        out.append(max(0, min(255, int(round(channel)))))
    return tuple(out)


def _clamp(value, low, high):
    return max(low, min(high, value))


class _Handler(BaseHTTPRequestHandler):
    server_version = "PS5LED"
    sys_version = ""

    # BaseHTTPRequestHandler logs every request to stderr; a 60 Hz stream would
    # bury anything worth reading.
    def log_message(self, format, *args):
        pass

    @property
    def bridge(self):
        return self.server.bridge

    def _authorised(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("t", [""])[0] != self.bridge.token:
            return False
        expected_host = "127.0.0.1:%d" % self.bridge.port
        if (self.headers.get("Host") or "") != expected_host:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + expected_host:
            return False
        return True

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_GET(self):
        if not self._authorised():
            self._send(403, json.dumps({"error": "forbidden"}))
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/boot":
            self._send(200, json.dumps(self.bridge.boot_payload()))
            return
        if path == "/api/stream":
            self._stream()
            return
        self._serve_static(path)

    def do_POST(self):
        if not self._authorised():
            self._send(403, json.dumps({"error": "forbidden"}))
            return
        if urllib.parse.urlparse(self.path).path != "/api/cmd":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, json.dumps({"ok": False, "error": "malformed json"}))
            return
        self._send(200, json.dumps(self.bridge.handle_command(payload)))

    def _serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        # posixpath.normpath collapses ".." before the join, so a traversal
        # cannot escape; the resolve() below is the belt to that braces.
        relative = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self._send(403, json.dumps({"error": "outside the web root"}))
            return
        if not target.is_file():
            self._send(404, json.dumps({"error": "not found"}))
            return
        guessed = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed in ("application/javascript",):
            guessed += "; charset=utf-8"
        self._send(200, target.read_bytes(), guessed)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        # Without this a proxy or the browser may buffer the stream into
        # uselessness; there is no proxy here, but the header costs nothing and
        # documents the intent.
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        bridge = self.bridge
        state = bridge.state
        last_state = 0.0
        last_sensor = 0.0
        try:
            while bridge.running:
                now = time.monotonic()
                snapshot = state.snapshot()
                state_period = 1.0 / (bridge.STATE_HZ if bridge.page_visible
                                      else bridge.IDLE_HZ)
                if now - last_state >= state_period:
                    self._emit("state", bridge.state_payload(snapshot))
                    last_state = now
                if bridge.page_visible and now - last_sensor >= 1.0 / bridge.SENSOR_HZ:
                    self._emit("sensor", bridge.sensor_payload(snapshot))
                    last_sensor = now
                time.sleep(1.0 / (bridge.SENSOR_HZ * 2) if bridge.page_visible else 0.25)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            # The page navigated away or the window closed. Normal, not an error.
            pass

    def _emit(self, name, payload):
        body = "event: %s\ndata: %s\n\n" % (name, json.dumps(payload))
        self.wfile.write(body.encode("utf-8"))
        self.wfile.flush()


class Bridge(object):
    STATE_FIELDS = ("connected", "transport", "product", "rgb", "mode",
                    "battery", "charging", "gyro_scale")
    SENSOR_FIELDS = ("gyro", "accel", "sensor_timestamp", "buttons", "touch")
    STATE_HZ = 30
    SENSOR_HZ = 60
    IDLE_HZ = 2

    def __init__(self, state, config, manager=None, engine=None,
                 host="127.0.0.1", port=0):
        self._state = state
        self._config = config
        self._manager = manager
        self._engine = engine
        self._host = host
        self._requested_port = port
        self.token = secrets.token_urlsafe(TOKEN_BYTES)
        self.page_visible = True
        self.running = False
        self._server = None
        self._thread = None

    @property
    def port(self):
        return self._server.server_address[1] if self._server else 0

    @property
    def url(self):
        return "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)

    @property
    def state(self):
        return self._state

    @staticmethod
    def _jsonable(value):
        # touch is a tuple of (x, y) tuples and Nones; json handles tuples, but
        # normalising to lists keeps the wire shape stable for the page.
        if isinstance(value, tuple):
            return [Bridge._jsonable(item) for item in value]
        return value

    def state_payload(self, snapshot):
        return {key: self._jsonable(snapshot.get(key))
                for key in self.STATE_FIELDS if key in snapshot}

    def sensor_payload(self, snapshot):
        return {key: self._jsonable(snapshot.get(key))
                for key in self.SENSOR_FIELDS if key in snapshot}

    def boot_payload(self):
        device = self._manager.describe() if self._manager is not None else {}
        return {
            "version": __version__,
            "config": self._config.snapshot(),
            "i18n": i18n.all_strings(),
            "direction": dict(i18n.DIRECTION),
            "modes": list(MODES),
            "device": device,
        }

    def handle_command(self, payload):
        if not isinstance(payload, dict):
            return {"ok": False, "error": "payload must be an object"}
        cmd = payload.get("cmd")
        handler = getattr(self, "_cmd_" + str(cmd), None) if cmd else None
        if handler is None:
            return {"ok": False, "error": "unknown command: %r" % (cmd,)}
        try:
            return handler(payload)
        except Exception as exc:  # a bad command must not take the bridge down
            return {"ok": False, "error": str(exc)}

    def _cmd_set_mode(self, payload):
        mode = payload.get("mode")
        if mode not in MODES:
            return {"ok": False, "error": "unknown mode: %r" % (mode,)}
        if self._engine is not None:
            self._engine.set_mode(mode)
        self._config.set("mode", mode)
        return {"ok": True, "mode": mode}

    def _cmd_set_colour(self, payload):
        rgb = parse_colour(payload.get("colour"))
        if rgb is None:
            return {"ok": False, "error": "not a colour: %r" % (payload.get("colour"),)}
        if self._engine is not None:
            self._engine.set_colour(rgb)
        self._config.set("colour", list(rgb))
        return {"ok": True, "colour": list(rgb)}

    def _numeric(self, payload, cmd):
        key, (low, high) = _NUMERIC[cmd]
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"ok": False, "error": "%s must be a number" % key}
        value = _clamp(float(value), low, high)
        if self._engine is not None:
            if cmd == "set_speed":
                self._engine.set_speed(value)
            else:
                self._engine.set_setting(key, value)
        self._config.set(key, value)
        return {"ok": True, key: value}

    def _cmd_set_speed(self, payload):
        return self._numeric(payload, "set_speed")

    def _cmd_set_brightness(self, payload):
        return self._numeric(payload, "set_brightness")

    def _cmd_set_duty(self, payload):
        return self._numeric(payload, "set_duty")

    def _cmd_set_language(self, payload):
        language = payload.get("language")
        if language not in i18n.LANGUAGES:
            return {"ok": False, "error": "unknown language: %r" % (language,)}
        self._config.set("language", language)
        return {"ok": True, "language": language}

    def _cmd_set_shell(self, payload):
        shell = payload.get("shell")
        if shell not in SHELLS:
            return {"ok": False, "error": "unknown shell: %r" % (shell,)}
        self._config.set("shell", shell)
        return {"ok": True, "shell": shell}

    def _cmd_profile_save(self, payload):
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "a profile needs a name"}
        profiles = dict(self._config.get("profiles") or {})
        profiles[name] = {key: self._config.get(key) for key in _PROFILE_KEYS}
        self._config.set("profiles", profiles)
        return {"ok": True, "name": name}

    def _cmd_profile_load(self, payload):
        name = str(payload.get("name") or "").strip()
        saved = (self._config.get("profiles") or {}).get(name)
        if not saved:
            return {"ok": False, "error": "no profile named %r" % (name,)}
        if "mode" in saved:
            self._cmd_set_mode({"mode": saved["mode"]})
        if "colour" in saved:
            self._cmd_set_colour({"colour": saved["colour"]})
        for key in ("speed", "brightness", "duty"):
            if key in saved:
                self._numeric({key: saved[key]}, "set_" + key)
        return {"ok": True, "name": name}

    def _cmd_profile_delete(self, payload):
        name = str(payload.get("name") or "").strip()
        profiles = dict(self._config.get("profiles") or {})
        if name not in profiles:
            return {"ok": False, "error": "no profile named %r" % (name,)}
        del profiles[name]
        self._config.set("profiles", profiles)
        return {"ok": True, "name": name}

    def _cmd_off(self, payload):
        # Deliberately does not touch the saved colour: turning the bar off is
        # not a choice of colour, and overwriting it would lose the user's.
        if self._engine is not None:
            self._engine.set_colour((0, 0, 0))
        return {"ok": True}

    def _cmd_visible(self, payload):
        self.page_visible = bool(payload.get("visible", True))
        return {"ok": True, "visible": self.page_visible}

    def start(self):
        self.running = True
        self._server = ThreadingHTTPServer((self._host, self._requested_port), _Handler)
        self._server.daemon_threads = True
        self._server.bridge = self
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="ps5led-bridge", daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._server is None:
            return
        server, self._server = self._server, None
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

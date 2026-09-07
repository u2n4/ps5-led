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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from . import i18n
from .engine import MODES

WEB_ROOT = pathlib.Path(__file__).resolve().parent.parent / "web"
TOKEN_BYTES = 16


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
        self._serve_static(path)

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


class Bridge(object):
    def __init__(self, state, config, manager=None, engine=None,
                 host="127.0.0.1", port=0):
        self._state = state
        self._config = config
        self._manager = manager
        self._engine = engine
        self._host = host
        self._requested_port = port
        self.token = secrets.token_urlsafe(TOKEN_BYTES)
        self._server = None
        self._thread = None

    @property
    def port(self):
        return self._server.server_address[1] if self._server else 0

    @property
    def url(self):
        return "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)

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

    def start(self):
        self._server = ThreadingHTTPServer((self._host, self._requested_port), _Handler)
        self._server.daemon_threads = True
        self._server.bridge = self
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="ps5led-bridge", daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        server, self._server = self._server, None
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

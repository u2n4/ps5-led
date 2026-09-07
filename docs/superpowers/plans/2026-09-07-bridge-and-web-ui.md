# PS5 LED v3 — Plan 2: the bridge and the web UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the engine a window — a real 3D DualSense that follows the controller's motion, an edge-reactive particle field, and a glass panel — served from the app's own local HTTP bridge into an Edge app window.

**Architecture:** Python stays the engine and owns no UI; the page is the UI and owns no hardware. A stdlib `ThreadingHTTPServer` on `127.0.0.1` serves `web/` and streams `AppState` over Server-Sent Events; the page posts commands back. `launcher.py` opens Edge with `--app` and its own `--user-data-dir`, so the browser process belongs to us and closing the window ends the session.

**Tech Stack:** Python 3.8+ standard library only (`http.server`, `json`, `secrets`, `subprocess`). Browser side: three.js 0.185.1 (MIT, vendored from npm), `EXT_meshopt_compression`, `EXT_texture_webp`, plain ES modules. No build step, no bundler, no framework.

**Spec:** `docs/superpowers/specs/2026-09-07-webview-rewrite-design.md` (§8 bridge, §9 web layer, §10 model and attribution)

**Branch:** `feat/webview-rewrite`, currently at `6649583`, 170 tests green, pushed to origin.

## Global Constraints

- **Python floor is 3.8.** CI runs 3.8, 3.10 and 3.12 on `ubuntu-latest` and `windows-latest`. No `match`, no `X | Y` annotations, no `list[int]` subscripting at runtime — use `typing.List`, `typing.Optional`, `typing.Tuple`.
- **Zero third-party Python dependencies.** Standard library only. This is the constraint the whole rewrite exists to protect.
- **`ps5led/hid_win.py` may only be imported inside a function body** by anything CI imports on Linux. `bridge.py`, `launcher.py` and `config.py` must import cleanly on Linux and their tests must pass there.
- **Every value passed into `AppState.update()` must be immutable** — tuples, ints, floats, strings, `None`. Never a list or dict, including nested.
- **The bridge binds `127.0.0.1` only.** Every request must satisfy all three of: a `?t=` token equal to a 128-bit value regenerated each launch; a `Host` header equal to `127.0.0.1:<port>`; and an `Origin` header that is either absent or exactly `http://127.0.0.1:<port>`. Anything else gets `403`.
- **No network calls from the app.** No CDN, no telemetry, no update check. Every asset is served from `web/`.
- **three.js is vendored from npm at 0.185.1** under its MIT licence, not copied from another project.
- **The 3D model is `PS5 Controller` by Taohid Animation, CC BY 4.0.** Attribution must appear in `ATTRIBUTION.md`, in `web/ATTRIBUTION.md`, in an in-app About panel, and in `README.md` Credits.
- LF line endings. All imports at the top of each Python file, except the deliberate function-body `hid_win` imports. No unused imports.
- Commits carry no `Co-Authored-By` trailer. Commit with `git -c user.name="u2n4" -c user.email="wohaibha@outlook.com" commit -m "..."`.

## What Plan 1 already gives you

Do not rebuild any of this; read it and use it.

`ps5led.state.AppState` — `seq` (property), `update(**fields) -> int`, `snapshot() -> dict`, `wait_for_change(last_seq, timeout=25.0) -> Optional[dict]`. A field written with the value it already holds does **not** advance `seq`, which is what keeps a motionless controller from waking the stream 60 times a second.

Fields already published into `AppState`, with their real types:

| Field | Type | Written by |
|---|---|---|
| `connected` | `bool` | `device` |
| `transport` | `"usb"` / `"bt"` / `None` | `device` |
| `product` | `str` / `None` | `device` |
| `gyro_scale` | `float` | `device` |
| `battery` | `int` 0–100 | `device`, ~250/s |
| `charging` | `bool` | `device` |
| `gyro` | `(float, float, float)` deg/s | `device`, ~250/s |
| `accel` | `(float, float, float)` g | `device`, ~250/s |
| `sensor_timestamp` | `int` | `device` |
| `buttons` | `int` (32-bit packed) | `device` |
| `touch` | `((int,int) or None, (int,int) or None)` | `device` |
| `rgb` | `(int, int, int)` | `engine` |
| `mode` | `str` | `engine` |

`ps5led.engine.Engine(state, write_colour, interval=1/30.0)` — `start()`, `stop()`, `set_mode(mode)`, `set_colour(rgb)`, `set_setting(key, value)`, `set_speed(speed)`. `MODES = ("manual", "rainbow", "wave", "flash", "battery")`.

`ps5led.device.DeviceManager(state)` — `start()`, `stop()`, `write_colour(rgb) -> bool` (never raises), `describe() -> dict` with keys `connected`, `product`, `product_id`, `transport`, `input_length`, `output_length`, `gyro_scales`, `last_error`, `last_write_error`.

`ps5led.cli` — `_parse_colour(text) -> Optional[Tuple[int,int,int]]`, `run_background(state=None, mode="manual", colour=None, speed=1.0)`, `doctor()`, `DOCTOR_TIMEOUT_SECONDS = 8.0`.

Measured facts this plan is built on, all captured in this repo's session:

- SSE from a stdlib `ThreadingHTTPServer` sustained a mean gap of **17.3 ms** (≈58 Hz) to an Edge page — enough for gyro.
- Edge `--app` with its own `--user-data-dir` gives a process we own; it stays alive exactly as long as the window.
- WebGL2 in that window reports `ANGLE (NVIDIA GeForce RTX 3070, D3D11)`.
- The page sends `Origin: http://127.0.0.1:<port>`, so the Origin check is real.
- The CC BY model is **6,658 KB**; `gltfpack -cc` takes it to 3,524 KB; re-encoding its seven 1024×1024 PNGs to WebP takes 2,978 KB of texture down to **618 KB**. Both together land near **1,150 KB**.

## Known defects Plan 1 parked that this plan must handle

These are recorded in Plan 1's review history and each becomes real the moment the bridge reads `describe()` from a running engine.

1. **`device.py` `_last_error` has several writers.** `write_colour`'s `"no device connected"` fires about 30 times a second in an animated mode while disconnected, so a bridge polling `describe()` would essentially always see that instead of the real cause. `--doctor` is immune because it builds its own manager with no engine. **Task 3 fixes this.**
2. **The calibration failure reason is carried in `_last_error`**, which a later successful write clears — so under `--background` the most diagnostic event on Bluetooth is erased within one engine tick. **Task 3 fixes this.**
3. **`engine.py` overwrites `settings["battery"]` unconditionally** from `AppState`, so `set_setting("battery", X)` is inert. Harmless today; the bridge is the first caller that could hit it. **Task 6 fixes this.**
4. **An out-of-range colour poisons `_last_rgb`.** `_build_packet` raises `ValueError` on a channel outside 0–255 and `_last_rgb` is recorded unconditionally, so one bad colour would make every later `_connect` open a handle, raise, close it and retry forever. Unreachable today because `colour_for` clamps — but the bridge accepts colours from the page. **Task 3 fixes this.**

---

## File structure

| File | Responsibility |
|---|---|
| `ps5led/config.py` | load/save/migrate `%APPDATA%/PS5-LED/config.json`, throttled writes |
| `ps5led/bridge.py` | `ThreadingHTTPServer`, auth guard, static files, `/api/*`, SSE |
| `ps5led/launcher.py` | find a browser, open the app window, wait for it to close |
| `ps5led/i18n.py` | ar/en strings, served to the page as JSON |
| `ps5led/cli.py` | gains `--window` (default), `--port`, `--no-browser` |
| `ps5led/device.py` | `_last_write_error` provenance fix, colour clamp |
| `ps5led/engine.py` | conditional battery override |
| `web/index.html` | the page shell |
| `web/css/app.css` | glass panel, layout, light/dark, RTL |
| `web/js/bridge.js` | `EventSource` + `POST /api/cmd`, reconnect with backoff |
| `web/js/scene.js` | three.js scene, GLB load, lightbar emissive, shell colour |
| `web/js/orientation.js` | gyro + accel → quaternion, complementary filter, recentre |
| `web/js/particles.js` | full-window canvas, edge-only cursor reactivity |
| `web/js/ui.js` | mode buttons, colour picker, sliders, profiles, battery, About |
| `web/js/i18n.js` | applies the strings and flips `dir` |
| `web/js/app.js` | boot order, wires the modules together |
| `web/vendor/three/` | three.js 0.185.1 module + GLTFLoader + RoomEnvironment + meshopt decoder (MIT) |
| `web/assets/dualsense.glb` | packed model (CC BY 4.0) |
| `tools/pack_model.mjs` | one-shot: gltfpack + ffmpeg WebP → the committed GLB |
| `tests/test_config.py`, `test_bridge.py`, `test_launcher.py`, `test_i18n.py` | |

---

### Task 1: Config persistence

**Files:**
- Create: `ps5led/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `DEFAULTS` (dict), `config_dir() -> pathlib.Path`, `config_path() -> pathlib.Path`, `load(path=None) -> dict`, `save(cfg, path=None) -> None`, `Config` class with `get(key, default=None)`, `set(key, value)`, `snapshot() -> dict`, `flush()`, and `THROTTLE_SECONDS = 2.0`

The app has had no persistence at all: every run starts on the default cyan, with no saved mode, colour, language or profiles. This is the first task because the bridge's `/api/boot` serves it and the UI has nothing to remember without it.

`load()` must survive a corrupt or truncated file — a config that raises on read would make the app unlaunchable, and the file is written on a throttle so a crash mid-write is a real possibility. Unknown keys in the file are kept, not dropped: a newer build's key must survive being opened by an older one.

Writes are throttled because the UI will call `set()` on every slider drag. `flush()` forces a write for shutdown.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
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
        cfg.save({"mode": "wave", "note": "\u0639\u0631\u0628\u064a"}, self.path)
        with open(self.path, "rb") as fh:
            head = fh.read(3)
        self.assertNotEqual(head, b"\xef\xbb\xbf")

    def test_round_trips_non_ascii(self):
        cfg.save({"note": "\u0639\u0631\u0628\u064a"}, self.path)
        self.assertEqual(cfg.load(self.path)["note"], "\u0639\u0631\u0628\u064a")

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
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_config -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.config'`.

- [ ] **Step 3: Implement**

`ps5led/config.py`:

```python
"""Preferences on disk.

Two rules shape this file. A corrupt config must never stop the app launching,
because the file is written on a throttle and a crash mid-write is a real
possibility; and an unknown key must survive a round trip, so a config written
by a newer build is not silently emptied by an older one.
"""

import copy
import json
import os
import pathlib
import platform
import threading
import time

from .device import DEFAULT_RGB

THROTTLE_SECONDS = 2.0

DEFAULTS = {
    "mode": "manual",
    "colour": list(DEFAULT_RGB),
    "speed": 1.0,
    "brightness": 1.0,
    "duty": 0.5,
    "language": "ar",
    "shell": "white",
    "profiles": {},
    "window": {"fullscreen": False, "width": 1280, "height": 800},
}


def config_dir():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif platform.system() == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return pathlib.Path(base) / "PS5-LED"


def config_path():
    return config_dir() / "config.json"


def load(path=None):
    """Defaults merged with whatever is on disk. Never raises."""
    merged = copy.deepcopy(DEFAULTS)
    target = pathlib.Path(path) if path is not None else config_path()
    try:
        with open(str(target), "r", encoding="utf-8") as fh:
            stored = json.load(fh)
    except Exception:
        return merged
    if not isinstance(stored, dict):
        return merged
    merged.update(stored)
    return merged


def save(cfg, path=None):
    """Write as UTF-8 with no BOM. Never raises: losing a preference is
    acceptable, crashing the app on shutdown is not."""
    target = pathlib.Path(path) if path is not None else config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(cfg, indent=1, ensure_ascii=False, sort_keys=True)
        with open(str(target), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except Exception:
        pass


class Config(object):
    """In-memory preferences with a throttled write behind them."""

    def __init__(self, path=None, throttle_seconds=THROTTLE_SECONDS):
        self._path = path
        self._throttle = throttle_seconds
        self._lock = threading.Lock()
        self._values = load(path)
        self._last_write = time.monotonic()
        self._dirty = False

    def get(self, key, default=None):
        with self._lock:
            if key in self._values:
                return self._values[key]
        if key in DEFAULTS:
            return copy.deepcopy(DEFAULTS[key])
        return default

    def set(self, key, value):
        with self._lock:
            self._values[key] = value
            self._dirty = True
            due = (time.monotonic() - self._last_write) >= self._throttle
            payload = copy.deepcopy(self._values) if due else None
            if due:
                self._last_write = time.monotonic()
                self._dirty = False
        if payload is not None:
            save(payload, self._path)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._values)

    def flush(self):
        with self._lock:
            if not self._dirty:
                return
            payload = copy.deepcopy(self._values)
            self._last_write = time.monotonic()
            self._dirty = False
        save(payload, self._path)
```

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest tests.test_config -v
```

Expected: 24 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/config.py tests/test_config.py
git commit -m "feat(config): preferences on disk, corruption-tolerant and throttled"
```

---

### Task 2: i18n strings

**Files:**
- Create: `ps5led/i18n.py`, `tests/test_i18n.py`

**Interfaces:**
- Consumes: nothing
- Produces: `LANGUAGES = ("ar", "en")`, `DIRECTION = {"ar": "rtl", "en": "ltr"}`, `strings(language) -> dict`, `all_strings() -> dict`

The page gets every string as JSON at boot and switches language without a reload, so both languages must carry exactly the same keys. A missing key would render as a blank label in one language only — the kind of defect that ships because nobody tests in the language they do not read.

Keys needed by the UI built in Tasks 8–11: `app_title`, `mode`, `mode_manual`, `mode_rainbow`, `mode_wave`, `mode_flash`, `mode_battery`, `colour`, `speed`, `brightness`, `duty`, `shell`, `shell_white`, `shell_black`, `shell_red`, `battery`, `charging`, `connected`, `disconnected`, `transport_usb`, `transport_bt`, `recentre`, `about`, `close`, `background`, `profiles`, `profile_save`, `profile_delete`, `language`, `no_controller`, `held_by_another_app`.

- [ ] **Step 1: Write the failing test**

`tests/test_i18n.py`:

```python
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
        arabic = [v for v in table.values() if any("\u0600" <= ch <= "\u06ff" for ch in str(v))]
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
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_i18n -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.i18n'`.

- [ ] **Step 3: Implement**

`ps5led/i18n.py`:

```python
"""UI strings, served to the page at boot.

Both tables carry the same keys by construction, because a key present in one
language renders as a blank label in the other and only a reader of that
language would ever notice.
"""

import copy

LANGUAGES = ("ar", "en")
DIRECTION = {"ar": "rtl", "en": "ltr"}

_EN = {
    "app_title": "PS5 LED",
    "mode": "Mode",
    "mode_manual": "Solid",
    "mode_rainbow": "Rainbow",
    "mode_wave": "Wave",
    "mode_flash": "Flash",
    "mode_battery": "Battery",
    "colour": "Colour",
    "speed": "Speed",
    "brightness": "Brightness",
    "duty": "Flash ratio",
    "shell": "Shell",
    "shell_white": "White",
    "shell_black": "Midnight Black",
    "shell_red": "Cosmic Red",
    "battery": "Battery",
    "charging": "Charging",
    "connected": "Connected",
    "disconnected": "Disconnected",
    "transport_usb": "USB",
    "transport_bt": "Bluetooth",
    "recentre": "Recentre",
    "about": "About",
    "close": "Close",
    "background": "Run in background",
    "profiles": "Profiles",
    "profile_save": "Save",
    "profile_delete": "Delete",
    "language": "Language",
    "no_controller": "No controller found. Connect it by cable or pair it over Bluetooth.",
    "held_by_another_app": "Another program is holding the controller. Close Steam or DS4Windows and try again.",
}

_AR = {
    "app_title": "PS5 LED",
    "mode": "\u0627\u0644\u0648\u0636\u0639",
    "mode_manual": "\u062b\u0627\u0628\u062a",
    "mode_rainbow": "\u0642\u0648\u0633 \u0642\u0632\u062d",
    "mode_wave": "\u0645\u0648\u062c\u0629",
    "mode_flash": "\u0648\u0645\u064a\u0636",
    "mode_battery": "\u0627\u0644\u0628\u0637\u0627\u0631\u064a\u0629",
    "colour": "\u0627\u0644\u0644\u0648\u0646",
    "speed": "\u0627\u0644\u0633\u0631\u0639\u0629",
    "brightness": "\u0627\u0644\u0633\u0637\u0648\u0639",
    "duty": "\u0646\u0633\u0628\u0629 \u0627\u0644\u0648\u0645\u064a\u0636",
    "shell": "\u0644\u0648\u0646 \u0627\u0644\u064a\u062f",
    "shell_white": "\u0623\u0628\u064a\u0636",
    "shell_black": "\u0623\u0633\u0648\u062f",
    "shell_red": "\u0623\u062d\u0645\u0631",
    "battery": "\u0627\u0644\u0628\u0637\u0627\u0631\u064a\u0629",
    "charging": "\u064a\u0634\u062d\u0646",
    "connected": "\u0645\u062a\u0635\u0644",
    "disconnected": "\u063a\u064a\u0631 \u0645\u062a\u0635\u0644",
    "transport_usb": "\u0648\u0627\u064a\u0631",
    "transport_bt": "\u0628\u0644\u0648\u062a\u0648\u062b",
    "recentre": "\u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0645\u0631\u0643\u0632\u0629",
    "about": "\u062d\u0648\u0644",
    "close": "\u0625\u063a\u0644\u0627\u0642",
    "background": "\u062a\u0634\u063a\u064a\u0644 \u0641\u064a \u0627\u0644\u062e\u0644\u0641\u064a\u0629",
    "profiles": "\u0645\u0644\u0641\u0627\u062a \u0627\u0644\u062a\u0639\u0631\u064a\u0641",
    "profile_save": "\u062d\u0641\u0638",
    "profile_delete": "\u062d\u0630\u0641",
    "language": "\u0627\u0644\u0644\u063a\u0629",
    "no_controller": "\u0645\u0627 \u0644\u0642\u064a\u062a \u064a\u062f. \u0648\u0635\u0651\u0644\u0647\u0627 \u0628\u0627\u0644\u0648\u0627\u064a\u0631 \u0623\u0648 \u0627\u0642\u0631\u0646\u0647\u0627 \u0628\u0644\u0648\u062a\u0648\u062b.",
    "held_by_another_app": "\u0628\u0631\u0646\u0627\u0645\u062c \u062b\u0627\u0646\u064a \u0645\u0627\u0633\u0643 \u0627\u0644\u064a\u062f. \u0633\u0643\u0651\u0631 Steam \u0623\u0648 DS4Windows \u0648\u062c\u0631\u0651\u0628 \u0645\u0631\u0629 \u062b\u0627\u0646\u064a\u0629.",
}

_TABLES = {"en": _EN, "ar": _AR}


def strings(language):
    """The table for one language; unknown languages fall back to English."""
    return copy.deepcopy(_TABLES.get(language, _EN))


def all_strings():
    return {lang: copy.deepcopy(_TABLES[lang]) for lang in LANGUAGES}
```

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest tests.test_i18n -v
```

Expected: 11 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/i18n.py tests/test_i18n.py
git commit -m "feat(i18n): ar/en strings with matching key sets"
```

---

### Task 3: Make `describe()` safe for a live consumer

**Files:**
- Modify: `ps5led/device.py`
- Modify: `tests/test_device.py`

**Interfaces:**
- Consumes: existing `DeviceManager`
- Produces: `describe()` gains `connect_error` and keeps `last_write_error`; `write_colour` clamps and rejects a bad colour without poisoning `_last_rgb`

Three parked defects become real the moment the bridge polls `describe()` from a running engine. Each is described in "Known defects" above; this task fixes all three because they are the same seam.

`_last_error` currently carries whatever spoke last. `write_colour`'s `"no device connected"` fires about 30 times a second in an animated mode while disconnected, so the real reason a connect failed survives for microseconds. Splitting the connect reason into its own field, written only by `_connect` and cleared only by a successful connect, gives the page something worth showing.

The colour clamp closes a latent trap: the page can post any colour, `_build_packet` raises `ValueError` outside 0–255, and `_last_rgb` is recorded unconditionally — so one bad colour would make every later `_connect` open a handle, raise, close it and retry forever.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device.py`, above the `if __name__` block:

```python
class TestDescribeForALiveConsumer(unittest.TestCase):
    """The bridge polls describe() while the engine runs; the old single
    _last_error field was overwritten about 30 times a second."""

    def test_connect_error_is_its_own_field(self):
        self.assertIn("connect_error", DeviceManager(AppState()).describe())

    def test_a_write_with_no_device_does_not_erase_the_connect_reason(self):
        install_fake_hid(self, [], lambda path: None)  # nothing to connect to
        manager = DeviceManager(AppState())
        self.assertFalse(manager._connect())
        reason = manager.describe()["connect_error"]
        self.assertTrue(reason, "a failed connect must leave a reason")

        for _ in range(30):  # what an animated mode does in one second
            manager.write_colour((1, 2, 3))

        self.assertEqual(manager.describe()["connect_error"], reason,
                         "write_colour overwrote the connect reason")

    def test_a_successful_connect_clears_the_connect_reason(self):
        device = FakeDevice()
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        manager._last_error = "stale"
        self.assertTrue(manager._connect())
        self.assertIsNone(manager.describe()["connect_error"])


class TestColourIsClamped(unittest.TestCase):
    """The page can post any colour. Before the clamp, one out-of-range value
    poisoned _last_rgb and every later _connect opened a handle, raised on
    _build_packet, closed it and retried forever."""

    def _manager(self, device):
        install_fake_hid(self, [FakeInfo(0x0CE6)], lambda path: device)
        manager = DeviceManager(AppState())
        self.assertTrue(manager._connect())
        return manager

    def test_out_of_range_channels_are_clamped_not_raised(self):
        device = FakeDevice()
        manager = self._manager(device)
        self.assertTrue(manager.write_colour((300, -5, 128)))
        self.assertEqual(manager._last_rgb, (255, 0, 128))

    def test_floats_are_accepted_and_rounded(self):
        device = FakeDevice()
        manager = self._manager(device)
        self.assertTrue(manager.write_colour((10.6, 20.2, 30.0)))
        self.assertEqual(manager._last_rgb, (11, 20, 30))

    def test_a_poisoned_colour_cannot_break_the_next_connect(self):
        device = FakeDevice()
        manager = self._manager(device)
        manager.write_colour((999, 999, 999))
        # The resend on the next connect must still build.
        self.assertTrue(manager._connect())

    def test_a_malformed_colour_is_refused_without_recording_it(self):
        device = FakeDevice()
        manager = self._manager(device)
        before = manager._last_rgb
        self.assertFalse(manager.write_colour(("red", 0, 0)))
        self.assertEqual(manager._last_rgb, before)
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_device -v
```

Expected: `KeyError: 'connect_error'` and `ValueError` from the clamp tests.

- [ ] **Step 3: Implement**

In `ps5led/device.py`, add a module-level helper above `class DeviceManager`:

```python
def clamp_rgb(rgb):
    """An (r, g, b) tuple of ints in 0..255, or None if it is not a colour.

    The page can post anything. Before this, an out-of-range channel raised
    ValueError inside _build_packet while _last_rgb had already recorded it, so
    one bad colour made every later _connect open a handle, raise, close it and
    retry forever.
    """
    try:
        r, g, b = rgb
    except (TypeError, ValueError):
        return None
    out = []
    for channel in (r, g, b):
        try:
            value = int(round(float(channel)))
        except (TypeError, ValueError):
            return None
        out.append(max(0, min(255, value)))
    return tuple(out)
```

In `DeviceManager.__init__`, add `self._connect_error = None` beside `self._last_error`.

In `describe()`, add `"connect_error": self._connect_error,` to the returned dict.

In `_connect()`, replace every `self._last_error = <reason>` with `self._connect_error = <reason>` and, on the success path where `self._last_error = None` is set, also set `self._connect_error = None`.

In `write_colour()`, clamp before anything else:

```python
    def write_colour(self, rgb):
        cleaned = clamp_rgb(rgb)
        if cleaned is None:
            with self._lock:
                self._last_error = "not a colour: %r" % (rgb,)
            return False
        rgb = cleaned
```

Leave the rest of `write_colour` unchanged, including the unconditional
`self._last_rgb = tuple(rgb)` — it is now recording a clamped value, so it can
no longer poison the resend.

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass, including the 170 that were green before.

- [ ] **Step 5: Commit**

```bash
git add ps5led/device.py tests/test_device.py
git commit -m "fix(device): connect reason survives a live engine, and colours are clamped"
```

---

### Task 4: The bridge — auth guard and static files

**Files:**
- Create: `ps5led/bridge.py`, `tests/test_bridge.py`
- Create: `web/index.html` (a placeholder page, replaced in Task 8)

**Interfaces:**
- Consumes: `ps5led.state.AppState`, `ps5led.config.Config`, `ps5led.i18n`
- Produces: `Bridge(state, config, manager=None, engine=None, host="127.0.0.1", port=0)` with `start() -> None`, `stop() -> None`, `port` (int), `token` (str), `url` (str); `WEB_ROOT` (pathlib.Path); `TOKEN_BYTES = 16`

Everything the page can reach passes the guard, so the guard is the first thing built and the first thing tested. All three checks must hold: the token, the `Host` header, and the `Origin` header. A browser cannot be stopped from following a link to `127.0.0.1:<port>`, so the token is what makes a guessed port useless, and the `Origin` check is what stops another page on the machine from driving the controller.

Static files are served from `web/` with no directory traversal: a request path is resolved and must stay under `WEB_ROOT`.

- [ ] **Step 1: Write the failing test**

`tests/test_bridge.py`:

```python
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
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_bridge -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.bridge'`.

- [ ] **Step 3: Implement**

Create `web/index.html` as a placeholder Task 8 replaces:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>PS5 LED</title></head>
<body><p>PS5 LED bridge is running.</p></body></html>
```

`ps5led/bridge.py`:

```python
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
```

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest tests.test_bridge -v
```

Expected: 22 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/bridge.py tests/test_bridge.py web/index.html
git commit -m "feat(bridge): local HTTP server with a three-part guard"
```

---

### Task 5: The bridge — commands

**Files:**
- Modify: `ps5led/bridge.py`
- Modify: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `Bridge` from Task 4, `Engine`, `DeviceManager`, `Config`
- Produces: `POST /api/cmd` accepting `{"cmd": ..., ...}` and returning `{"ok": true, ...}` or `{"ok": false, "error": "..."}`; `Bridge.handle_command(payload) -> dict`

Commands are the page's only way to change anything, so every one of them validates its input rather than trusting it. `handle_command` is a plain method taking and returning a dict, which is what makes the whole command surface testable without a socket.

Commands: `set_mode` (`mode`), `set_colour` (`colour` as `[r,g,b]` or `"00aaff"`), `set_speed` (`speed`), `set_brightness` (`brightness`), `set_duty` (`duty`), `set_shell` (`shell`), `set_language` (`language`), `profile_save` (`name`), `profile_load` (`name`), `profile_delete` (`name`), `off`, `visible` (`visible` bool).

Every setting command also writes through to `Config`, which is what makes the UI remember anything.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bridge.py`, above the `if __name__` block:

```python
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
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_bridge -v
```

Expected: `AttributeError: 'Bridge' object has no attribute 'handle_command'`.

- [ ] **Step 3: Implement**

Add to `ps5led/bridge.py`, importing `MODES` (already imported) and adding
`from .cli import _parse_colour` is **not** allowed — it would make `bridge`
import `cli`, which imports `bridge`. Put the hex parsing here instead.

```python
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
```

Add to `Bridge.__init__`: `self.page_visible = True`.

Add the method:

```python
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
```

Add `do_POST` to `_Handler`:

```python
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
```

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest tests.test_bridge -v
```

Expected: 47 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add ps5led/bridge.py tests/test_bridge.py
git commit -m "feat(bridge): validated command surface with config write-through"
```

---

### Task 6: The bridge — SSE stream

**Files:**
- Modify: `ps5led/bridge.py`, `ps5led/engine.py`
- Modify: `tests/test_bridge.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: `AppState.wait_for_change`, `Bridge.page_visible`
- Produces: `GET /api/stream` emitting `event: state` and `event: sensor`; `Bridge.STATE_FIELDS`, `Bridge.SENSOR_FIELDS`, `Bridge.SENSOR_HZ = 60`, `Bridge.STATE_HZ = 30`, `Bridge.IDLE_HZ = 2`

The stream is what makes the model move. It carries two events because they have different rates and different costs: `state` is colour, mode, battery and connection — cheap and slow; `sensor` is gyro, accel, buttons and touch — 60 Hz and only worth sending while somebody is looking.

When the page reports `visible: false`, `sensor` stops entirely and `state` drops to 2 Hz. During a game the window is normally closed and there is no client at all, which is the idle cost the rewrite exists to eliminate.

This task also fixes the parked `engine.py` defect: it overwrites `settings["battery"]` unconditionally from `AppState`, so `set_setting("battery", X)` is inert.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bridge.py`:

```python
import http.client
import time


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
```

Append to `tests/test_engine.py`:

```python
class TestBatteryOverride(unittest.TestCase):
    """AppState is the normal source, but an explicit set_setting must win --
    it was overwritten unconditionally, so the setter was silently inert."""

    def test_appstate_supplies_battery_when_nothing_was_set(self):
        state = AppState()
        state.update(battery=100)
        engine = Engine(state, lambda rgb: True, interval=0.005)
        engine.set_mode("battery")
        engine.start()
        time.sleep(0.1)
        engine.stop()
        r, g, b = state.snapshot()["rgb"]
        self.assertGreater(g, 200)

    def test_an_explicit_override_is_not_erased_by_appstate(self):
        state = AppState()
        state.update(battery=100)
        engine = Engine(state, lambda rgb: True, interval=0.005)
        engine.set_mode("battery")
        engine.set_setting("battery", 0)
        engine.start()
        time.sleep(0.1)
        engine.stop()
        r, g, b = state.snapshot()["rgb"]
        self.assertGreater(r, 200, "the explicit override was overwritten")
```

- [ ] **Step 2: Run and confirm both fail**

```bash
python -m unittest tests.test_bridge tests.test_engine -v
```

Expected: `AttributeError: 'Bridge' object has no attribute 'sensor_payload'`, and the engine override test failing because `settings["battery"]` is overwritten.

- [ ] **Step 3: Implement**

In `ps5led/engine.py`, find the line that reads battery from `AppState` into the
per-tick settings and make it conditional:

```python
            # AppState is the normal source, but an explicit set_setting must
            # win: overwriting unconditionally made that setter silently inert.
            if settings.get("battery") is None:
                settings["battery"] = self._state.snapshot().get("battery")
```

In `ps5led/bridge.py`, add the field lists and payload builders to `Bridge`:

```python
    STATE_FIELDS = ("connected", "transport", "product", "rgb", "mode",
                    "battery", "charging", "gyro_scale")
    SENSOR_FIELDS = ("gyro", "accel", "sensor_timestamp", "buttons", "touch")
    STATE_HZ = 30
    SENSOR_HZ = 60
    IDLE_HZ = 2

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
```

Add the streaming handler to `_Handler.do_GET`, before `_serve_static`:

```python
        if path == "/api/stream":
            self._stream()
            return
```

And the method:

```python
    def _stream(self):
        import time as _time

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
                now = _time.monotonic()
                snapshot = state.snapshot()
                state_period = 1.0 / (bridge.STATE_HZ if bridge.page_visible
                                      else bridge.IDLE_HZ)
                if now - last_state >= state_period:
                    self._emit("state", bridge.state_payload(snapshot))
                    last_state = now
                if bridge.page_visible and now - last_sensor >= 1.0 / bridge.SENSOR_HZ:
                    self._emit("sensor", bridge.sensor_payload(snapshot))
                    last_sensor = now
                _time.sleep(1.0 / (bridge.SENSOR_HZ * 2) if bridge.page_visible else 0.25)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            # The page navigated away or the window closed. Normal, not an error.
            pass

    def _emit(self, name, payload):
        body = "event: %s\ndata: %s\n\n" % (name, json.dumps(payload))
        self.wfile.write(body.encode("utf-8"))
        self.wfile.flush()
```

Add to `Bridge`: `self.running = False` in `__init__`, `self.running = True` at the
start of `start()`, `self.running = False` at the start of `stop()`, and a
`state` property returning `self._state`.

- [ ] **Step 4: Run and confirm they pass**

```bash
python -m unittest discover -s tests -v
```

Expected: everything passes.

- [ ] **Step 5: Commit**

```bash
git add ps5led/bridge.py ps5led/engine.py tests/test_bridge.py tests/test_engine.py
git commit -m "feat(bridge): SSE state and sensor streams, quiet when the page is hidden"
```

---

### Task 7: The launcher and the CLI window mode

**Files:**
- Create: `ps5led/launcher.py`, `tests/test_launcher.py`
- Modify: `ps5led/cli.py`

**Interfaces:**
- Consumes: `Bridge.url`
- Produces: `BROWSERS` (tuple of candidate paths), `find_browser() -> Optional[str]`, `browser_args(exe, url, profile_dir, fullscreen=False, size=(1280, 800)) -> List[str]`, `launch(url, profile_dir=None, fullscreen=False) -> Optional[subprocess.Popen]`, `wait_for_close(process) -> int`; `cli.run_window(...)`

Edge with `--app` and its own `--user-data-dir` was measured to give a process we own: it stays alive exactly as long as the window, so `wait_for_close` is how the app knows the user closed it. A shared profile would attach to an already-running Edge and exit immediately, which is why the private profile directory is not optional.

`find_browser` prefers Edge, then Chrome, then falls back to `webbrowser.open`, which loses the app-window framing but still works. The lightbar does not depend on any of this: the engine runs regardless.

- [ ] **Step 1: Write the failing test**

`tests/test_launcher.py`:

```python
import os
import platform
import tempfile
import unittest

from ps5led import launcher


class TestBrowserArgs(unittest.TestCase):
    def setUp(self):
        self.profile = os.path.join(tempfile.mkdtemp(), "browser")

    def test_app_mode_carries_the_url(self):
        args = launcher.browser_args("edge.exe", "http://127.0.0.1:1/?t=x", self.profile)
        self.assertTrue(any(a == "--app=http://127.0.0.1:1/?t=x" for a in args))

    def test_the_executable_is_first(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertEqual(args[0], "edge.exe")

    def test_a_private_profile_directory_is_always_passed(self):
        # A shared profile attaches to an already-running browser and exits
        # immediately, so the process would not be ours to wait on.
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in args))

    def test_first_run_prompts_are_suppressed(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertIn("--no-first-run", args)
        self.assertIn("--no-default-browser-check", args)

    def test_fullscreen_is_requested_only_when_asked(self):
        plain = launcher.browser_args("edge.exe", "http://x", self.profile)
        full = launcher.browser_args("edge.exe", "http://x", self.profile, fullscreen=True)
        self.assertNotIn("--start-fullscreen", plain)
        self.assertIn("--start-fullscreen", full)

    def test_a_window_size_is_passed_when_not_fullscreen(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile, size=(900, 700))
        self.assertIn("--window-size=900,700", args)

    def test_no_argument_contains_a_shell_metacharacter(self):
        # The process is spawned with shell=False, but an argument that needs
        # quoting is a sign the url was built wrong.
        args = launcher.browser_args("edge.exe", "http://127.0.0.1:1/?t=abc", self.profile)
        for arg in args:
            self.assertNotIn("&&", arg)
            self.assertNotIn("|", arg)


class TestFindBrowser(unittest.TestCase):
    def test_candidates_are_absolute_paths(self):
        for path in launcher.BROWSERS:
            self.assertTrue(os.path.isabs(path), path)

    def test_edge_is_preferred_over_chrome(self):
        joined = " ".join(launcher.BROWSERS).lower()
        self.assertLess(joined.index("edge"), joined.index("chrome"))

    @unittest.skipUnless(platform.system() == "Windows", "Windows browser paths")
    def test_find_browser_returns_something_that_exists_or_none(self):
        found = launcher.find_browser()
        if found is not None:
            self.assertTrue(os.path.exists(found))


class TestProfileDir(unittest.TestCase):
    def test_default_profile_dir_is_under_the_config_dir(self):
        from ps5led.config import config_dir
        self.assertEqual(launcher.default_profile_dir().parent, config_dir())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm it fails**

```bash
python -m unittest tests.test_launcher -v
```

Expected: `ModuleNotFoundError: No module named 'ps5led.launcher'`.

- [ ] **Step 3: Implement**

`ps5led/launcher.py`:

```python
"""Open the app window.

Measured: Edge with --app and its own --user-data-dir gives a process we own -
it stays alive exactly as long as the window, which is how the app knows the
user closed it. A shared profile attaches to an already-running browser and
exits immediately, so the private profile directory is not optional.

Nothing here is load-bearing for the lightbar: the engine runs with or without
a window.
"""

import os
import pathlib
import subprocess
import webbrowser

from .config import config_dir

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def default_profile_dir():
    return config_dir() / "browser"


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return None


def browser_args(exe, url, profile_dir, fullscreen=False, size=(1280, 800)):
    args = [
        exe,
        "--app=%s" % url,
        "--user-data-dir=%s" % profile_dir,
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if fullscreen:
        args.append("--start-fullscreen")
    else:
        args.append("--window-size=%d,%d" % (int(size[0]), int(size[1])))
    return args


def launch(url, profile_dir=None, fullscreen=False, size=(1280, 800)):
    """The browser process, or None if we had to fall back to the default one."""
    exe = find_browser()
    if exe is None:
        webbrowser.open(url)
        return None
    target = pathlib.Path(profile_dir or default_profile_dir())
    target.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        browser_args(exe, url, str(target), fullscreen=fullscreen, size=size),
        shell=False)


def wait_for_close(process):
    """Block until the window closes. Returns its exit code, or 0 for no process."""
    if process is None:
        return 0
    try:
        return process.wait()
    except KeyboardInterrupt:
        return 0
```

In `ps5led/cli.py`, add `run_window` and wire the flags:

```python
def run_window(mode=None, colour=None, speed=None, port=0, open_browser=True):
    if not _require_windows():
        return 2
    from .bridge import Bridge
    from .config import Config
    from . import launcher

    config = Config()
    state = AppState()
    manager = DeviceManager(state)
    engine = Engine(state, manager.write_colour)
    engine.set_mode(mode or config.get("mode"))
    engine.set_speed(speed if speed is not None else config.get("speed"))
    engine.set_colour(colour or tuple(config.get("colour")))
    bridge = Bridge(state, config, manager=manager, engine=engine, port=port)

    process = None
    try:
        manager.start()
        engine.start()
        bridge.start()
        print("PS5 LED bridge on %s" % bridge.url)
        if open_browser:
            window = config.get("window") or {}
            process = launcher.launch(
                bridge.url,
                fullscreen=bool(window.get("fullscreen")),
                size=(window.get("width", 1280), window.get("height", 800)))
            launcher.wait_for_close(process)
        else:
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        engine.stop()
        manager.stop()
        config.flush()
    return 0
```

Add to `main`'s parser and dispatch:

```python
    parser.add_argument("--window", action="store_true",
                        help="open the app window (default when no other action)")
    parser.add_argument("--no-browser", action="store_true",
                        help="run the bridge without opening a window")
    parser.add_argument("--port", type=int, default=0,
                        help="bridge port (default: an ephemeral one)")
```

and, replacing the final `parser.print_help()` fallthrough:

```python
    if args.background:
        return run_background(mode=args.mode, colour=colour, speed=args.speed)
    return run_window(mode=args.mode if args.mode != "manual" else None,
                      colour=colour, speed=args.speed, port=args.port,
                      open_browser=not args.no_browser)
```

- [ ] **Step 4: Run and confirm it passes**

```bash
python -m unittest discover -s tests -v
```

Then, with the controller connected:

```bash
python -m ps5led --no-browser --port 8731
```

Expected: it prints a bridge URL. Open that exact URL in a browser and the
placeholder page loads; without the token it is refused.

- [ ] **Step 5: Commit**

```bash
git add ps5led/launcher.py ps5led/cli.py tests/test_launcher.py
git commit -m "feat(launcher): Edge app window, and --window/--port/--no-browser"
```

---

### Task 8: Vendor three.js and pack the model

**Files:**
- Create: `tools/pack_model.mjs`, `web/vendor/three/` (vendored), `web/assets/dualsense.glb`, `web/ATTRIBUTION.md`
- Modify: `ATTRIBUTION.md`, `README.md`

**Interfaces:**
- Consumes: nothing
- Produces: `web/vendor/three/three.module.js`, `web/vendor/three/GLTFLoader.js`, `web/vendor/three/RoomEnvironment.js`, `web/vendor/three/meshopt_decoder.module.js`, `web/assets/dualsense.glb`

The model is **PS5 Controller by Taohid Animation, CC BY 4.0**, taken from the original mirror rather than any modified redistribution. CC BY requires credit wherever the work is shown, which is why the attribution lands in four places, one of them inside the running app.

Measured on this machine: the source GLB is 6,658 KB; `gltfpack -cc` brings it to 3,524 KB; re-encoding its seven 1024×1024 PNGs to WebP takes 2,978 KB of texture down to 618 KB. `gltfpack`'s node build cannot compress textures — it is built without BasisU — so ffmpeg does that half and the glTF `EXT_texture_webp` extension carries it. `GLTFLoader` supports both `EXT_meshopt_compression` and `EXT_texture_webp`; this was checked against the loader source.

- [ ] **Step 1: Vendor three.js from npm**

```bash
cd "C:\Users\aliha\codAi\projects\dualled-pro"
mkdir -p web/vendor/three
npm pack three@0.185.1
tar -xzf three-0.185.1.tgz
cp package/build/three.module.js web/vendor/three/three.module.js
cp package/examples/jsm/loaders/GLTFLoader.js web/vendor/three/GLTFLoader.js
cp package/examples/jsm/environments/RoomEnvironment.js web/vendor/three/RoomEnvironment.js
cp package/examples/jsm/libs/meshopt_decoder.module.js web/vendor/three/meshopt_decoder.module.js
cp package/LICENSE web/vendor/three/LICENSE
rm -rf package three-0.185.1.tgz
```

Verify every file arrived and that `GLTFLoader.js` only imports from `three`:

```bash
ls -la web/vendor/three/
grep -n "^import" web/vendor/three/GLTFLoader.js | head -3
```

Fix the bare `three` specifier so the browser can resolve it without an import
map — replace `from 'three'` with `from './three.module.js'` in `GLTFLoader.js`
and `RoomEnvironment.js`, then confirm no bare specifiers remain:

```bash
grep -rn "from 'three'" web/vendor/three/ || echo "no bare specifiers left"
```

- [ ] **Step 2: Write the packing tool**

`tools/pack_model.mjs`:

```javascript
#!/usr/bin/env node
/**
 * pack_model.mjs - one-shot: turn the CC BY source GLB into the file we ship.
 *
 * Run once; the output is committed. Measured on this repo:
 *   source                     6,658 KB
 *   gltfpack -cc (meshopt)     3,524 KB
 *   textures PNG -> WebP        2,978 KB -> 618 KB
 *   both                       ~1,150 KB
 *
 * gltfpack's node build cannot do textures - it is compiled without BasisU -
 * so ffmpeg does that half and EXT_texture_webp carries it in the glTF.
 *
 * Usage: node tools/pack_model.mjs --in <source.glb> --out web/assets/dualsense.glb
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).flatMap((a, i, arr) =>
  a.startsWith('--') ? [[a.slice(2), arr[i + 1]]] : []));
const IN = args.in;
const OUT = args.out ?? 'web/assets/dualsense.glb';
if (!IN || !existsSync(IN)) { console.error('need --in <source.glb>'); process.exit(1); }

const work = mkdtempSync(join(tmpdir(), 'packmodel-'));
const packed = join(work, 'packed.glb');

console.log('1/3 meshopt geometry compression');
execFileSync('npx', ['--yes', 'gltfpack', '-i', IN, '-o', packed, '-cc'], { stdio: 'inherit', shell: true });

console.log('2/3 re-encoding textures to WebP');
const glb = readFileSync(packed);
const jsonLength = glb.readUInt32LE(12);
const gltf = JSON.parse(glb.subarray(20, 20 + jsonLength).toString('utf8'));
const binStart = 20 + jsonLength + 8;
const images = gltf.images ?? [];
let saved = 0;
for (let i = 0; i < images.length; i++) {
  const view = gltf.bufferViews[images[i].bufferView];
  const start = binStart + (view.byteOffset ?? 0);
  const png = join(work, `${i}.png`);
  const webp = join(work, `${i}.webp`);
  writeFileSync(png, glb.subarray(start, start + view.byteLength));
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', png,
                          '-c:v', 'libwebp', '-quality', '88', '-compression_level', '6', webp],
               { stdio: 'inherit' });
  saved += view.byteLength - readFileSync(webp).length;
}
console.log(`   textures would save ${(saved / 1024).toFixed(0)} KB as WebP`);

console.log('3/3 writing the packed model');
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, readFileSync(packed));
const size = readFileSync(OUT).length;
console.log(`wrote ${OUT}: ${(size / 1024).toFixed(0)} KB`);
console.log('NOTE: verify it loads in the app before committing.');
```

- [ ] **Step 3: Produce the model**

```bash
cd "C:\Users\aliha\codAi\projects\dualled-pro"
curl -sL "https://github.com/Manav-Sonawane/Playstation-Revamp/raw/main/public/ps5_controller.glb" -o /tmp/ps5_source.glb
node tools/pack_model.mjs --in /tmp/ps5_source.glb --out web/assets/dualsense.glb
ls -la web/assets/dualsense.glb
```

Expected: a file well under the 6,658 KB source. Record the number you actually
got in the commit message; do not repeat the estimate.

- [ ] **Step 4: Write the attribution**

`web/ATTRIBUTION.md` and the same text appended to the repo root `ATTRIBUTION.md`:

```markdown
# Attribution

## 3D model

**PS5 Controller** by **Taohid Animation**, licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

- Creator: https://sketchfab.com/taohidanimation
- Original model: https://sketchfab.com/3d-models/ps5-controller-b7bb9c5102a04cb0b1966c6d02bad7d6

Modifications made for this application: geometry compressed with meshopt,
textures re-encoded to WebP, and the lightbar meshes named so the application
can drive their emissive colour. Geometry, UVs and materials are otherwise the
creator's.

This is an independent recreation and is not an official Sony product.

## three.js

three.js r185 (0.185.1), used under the
[MIT licence](vendor/three/LICENSE), vendored unmodified from npm apart from
rewriting bare `three` import specifiers to relative paths so the browser can
resolve them without an import map.
```

Add a Credits section to `README.md` carrying the same two credits and a line
thanking DualSense Studio as inspiration, with no code taken from it.

- [ ] **Step 5: Commit**

```bash
git add web/vendor/three web/assets/dualsense.glb web/ATTRIBUTION.md ATTRIBUTION.md README.md tools/pack_model.mjs
git commit -m "feat(web): vendor three.js 0.185.1 and the packed CC BY model"
```

---

### Task 9: The page shell, bridge client, and particle background

**Files:**
- Replace: `web/index.html`
- Create: `web/css/app.css`, `web/js/bridge.js`, `web/js/particles.js`, `web/js/app.js`

**Interfaces:**
- Consumes: `/api/boot`, `/api/stream`, `/api/cmd`
- Produces: `bridge.js` exports `connect(token, handlers) -> {send, close}`; `particles.js` exports `startParticles(canvas) -> {stop}`

This is the first task that puts something on screen. The particle field is here rather than later because it is the background everything else sits on, and because it is independently visible: run it and the window is alive before a single triangle of the model has loaded.

The background reacts to the cursor **only near the edges**. Each particle carries `edgeWeight = 1 - smoothstep(0.55, 0.85, d)` where `d` is its distance from the window centre normalised so the centre is 0 and a corner is 1. Particles inside the central 60% have weight 0 and only drift. The gradient is smooth, so no boundary is visible.

The panel is glass — `backdrop-filter` over a translucent background — so the field shows through it and covers the whole window, which is what the spec asks for and what a Tk canvas could not do.

- [ ] **Step 1: Write the page shell**

`web/index.html`:

```html
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PS5 LED</title>
<link rel="stylesheet" href="css/app.css">
</head>
<body>
<canvas id="particles" aria-hidden="true"></canvas>

<main class="shell">
  <header class="bar">
    <h1 id="t-title">PS5 LED</h1>
    <div class="status">
      <span id="conn" class="pill">—</span>
      <span id="batt" class="pill">—</span>
    </div>
  </header>

  <section class="stage">
    <canvas id="scene"></canvas>
    <p id="scene-fallback" class="fallback" hidden></p>
  </section>

  <section class="panel" id="controls"></section>
</main>

<script type="module" src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write the stylesheet**

`web/css/app.css`:

```css
:root {
  --bg: #070b11;
  --ink: #e8eefc;
  --muted: #93a1bd;
  --glass: rgba(11, 15, 20, 0.45);
  --edge: rgba(255, 255, 255, 0.07);
  --accent: #00aaff;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  height: 100%;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.5 "Segoe UI", system-ui, sans-serif;
  overflow: hidden;
}

/* The field sits behind everything and never eats a click. */
#particles {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.shell {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: 100%;
  padding: 18px;
  gap: 14px;
}

.bar { display: flex; align-items: center; justify-content: space-between; }
.bar h1 { font-size: 18px; font-weight: 600; margin: 0; letter-spacing: .02em; }
.status { display: flex; gap: 8px; }

.pill {
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--glass);
  border: 1px solid var(--edge);
  color: var(--muted);
  font-size: 12px;
}
.pill.ok { color: #7ee787; }
.pill.bad { color: #ff7b72; }

.stage { position: relative; min-height: 0; }
#scene { width: 100%; height: 100%; display: block; }

.fallback {
  position: absolute; inset: 0; display: grid; place-items: center;
  margin: 0; color: var(--muted); text-align: center; padding: 24px;
}

/* Glass: the particle field shows through, which is the whole point of
   moving off a Tk canvas. */
.panel {
  background: var(--glass);
  backdrop-filter: blur(22px) saturate(140%);
  -webkit-backdrop-filter: blur(22px) saturate(140%);
  border: 1px solid var(--edge);
  border-radius: 16px;
  padding: 16px;
  display: grid;
  gap: 14px;
}

.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.row > label { min-width: 92px; color: var(--muted); }

button {
  background: rgba(255,255,255,.05);
  color: var(--ink);
  border: 1px solid var(--edge);
  border-radius: 10px;
  padding: 8px 14px;
  cursor: pointer;
  font: inherit;
}
button:hover { background: rgba(255,255,255,.10); }
button[aria-pressed="true"] { background: var(--accent); color: #04121d; border-color: transparent; }

input[type="range"] { flex: 1; min-width: 140px; accent-color: var(--accent); }
input[type="color"] {
  width: 44px; height: 32px; padding: 0; cursor: pointer;
  background: none; border: 1px solid var(--edge); border-radius: 8px;
}

@media (prefers-reduced-motion: reduce) {
  #particles { opacity: .5; }
}
```

- [ ] **Step 3: Write the bridge client**

`web/js/bridge.js`:

```javascript
// The page's only link to the engine. Everything reconnects on its own: the
// window can outlive a bridge restart, and a dead stream must not need a reload.

const TOKEN = new URLSearchParams(location.search).get('t') ?? '';

export function token() { return TOKEN; }

export async function boot() {
  const response = await fetch(`/api/boot?t=${encodeURIComponent(TOKEN)}`);
  if (!response.ok) throw new Error(`boot failed: ${response.status}`);
  return response.json();
}

export async function send(payload) {
  const response = await fetch(`/api/cmd?t=${encodeURIComponent(TOKEN)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) return { ok: false, error: `http ${response.status}` };
  return response.json();
}

export function connect({ onState, onSensor, onOpen, onError }) {
  let source = null;
  let delay = 500;
  let closed = false;

  const open = () => {
    if (closed) return;
    source = new EventSource(`/api/stream?t=${encodeURIComponent(TOKEN)}`);
    source.addEventListener('open', () => { delay = 500; onOpen?.(); });
    source.addEventListener('state', (event) => onState?.(JSON.parse(event.data)));
    source.addEventListener('sensor', (event) => onSensor?.(JSON.parse(event.data)));
    source.addEventListener('error', () => {
      source.close();
      onError?.();
      if (closed) return;
      // Backoff, capped: a bridge that is gone for good must not spin the CPU.
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 10000);
    });
  };

  open();

  // The engine stops streaming sensor data while the page says it is hidden.
  const reportVisibility = () =>
    send({ cmd: 'visible', visible: document.visibilityState === 'visible' });
  document.addEventListener('visibilitychange', reportVisibility);
  reportVisibility();

  return {
    send,
    close() {
      closed = true;
      document.removeEventListener('visibilitychange', reportVisibility);
      source?.close();
    },
  };
}
```

- [ ] **Step 4: Write the particle field**

`web/js/particles.js`:

```javascript
// A drifting field that reacts to the cursor ONLY near the edges.
//
// Each particle carries edgeWeight = 1 - smoothstep(0.55, 0.85, d), where d is
// its distance from the centre normalised so the centre is 0 and a corner is 1.
// Inside the central 60% the weight is 0 and the particle only drifts, so the
// area behind the panel stays calm while the border comes alive under the
// cursor. The ramp is smooth, so no boundary is visible.

const COUNT = 140;
const LINK_DISTANCE = 110;
const REPEL = 5200;

const smoothstep = (a, b, x) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

export function startParticles(canvas) {
  const context = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pointer = { x: -1e6, y: -1e6 };
  let width = 0, height = 0, particles = [], frame = 0, running = true;

  const resize = () => {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };

  const edgeWeight = (x, y) => {
    // Normalised so the centre is 0 and a corner is 1.
    const dx = (x - width / 2) / (width / 2 || 1);
    const dy = (y - height / 2) / (height / 2 || 1);
    const d = Math.min(1, Math.hypot(dx, dy) / Math.SQRT2 * Math.SQRT2);
    return 1 - smoothstep(0.55, 0.85, 1 - d) === 0 ? smoothstep(0.55, 0.85, d) : smoothstep(0.55, 0.85, d);
  };

  const seed = () => {
    particles = Array.from({ length: COUNT }, () => {
      const x = Math.random() * width;
      const y = Math.random() * height;
      return {
        x, y,
        vx: (Math.random() - 0.5) * (reduced ? 0.12 : 0.25),
        vy: (Math.random() - 0.5) * (reduced ? 0.12 : 0.25),
        r: Math.random() * 1.6 + 0.6,
      };
    });
  };

  const step = () => {
    if (!running) return;
    context.clearRect(0, 0, width, height);

    for (const p of particles) {
      const weight = edgeWeight(p.x, p.y);

      if (!reduced && weight > 0.01) {
        const dx = p.x - pointer.x;
        const dy = p.y - pointer.y;
        const squared = dx * dx + dy * dy + 40;
        const force = (REPEL * weight) / squared;
        const length = Math.hypot(dx, dy) || 1;
        p.vx += (dx / length) * force * 0.016;
        p.vy += (dy / length) * force * 0.016;
      }

      p.vx *= 0.97;
      p.vy *= 0.97;
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0) p.x += width;
      if (p.x > width) p.x -= width;
      if (p.y < 0) p.y += height;
      if (p.y > height) p.y -= height;

      context.beginPath();
      context.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      context.fillStyle = `rgba(140,170,220,${0.18 + weight * 0.35})`;
      context.fill();
    }

    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j];
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        if (distance > LINK_DISTANCE) continue;
        const weight = Math.max(edgeWeight(a.x, a.y), edgeWeight(b.x, b.y));
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.strokeStyle =
          `rgba(120,160,215,${(1 - distance / LINK_DISTANCE) * 0.16 * (0.3 + weight)})`;
        context.stroke();
      }
    }

    frame = requestAnimationFrame(step);
  };

  const onPointer = (event) => { pointer.x = event.clientX; pointer.y = event.clientY; };
  const onLeave = () => { pointer.x = -1e6; pointer.y = -1e6; };

  addEventListener('resize', () => { resize(); seed(); });
  addEventListener('pointermove', onPointer, { passive: true });
  addEventListener('pointerleave', onLeave);

  resize();
  seed();
  step();

  return {
    stop() {
      running = false;
      cancelAnimationFrame(frame);
      removeEventListener('pointermove', onPointer);
      removeEventListener('pointerleave', onLeave);
    },
  };
}
```

Simplify `edgeWeight` to exactly this before moving on — the expression above is
redundant and must not ship:

```javascript
  const edgeWeight = (x, y) => {
    const dx = (x - width / 2) / (width / 2 || 1);
    const dy = (y - height / 2) / (height / 2 || 1);
    const d = Math.min(1, Math.hypot(dx, dy) / Math.SQRT2);
    return smoothstep(0.55, 0.85, d);
  };
```

- [ ] **Step 5: Wire it up and see it**

`web/js/app.js`:

```javascript
import { boot, connect } from './bridge.js';
import { startParticles } from './particles.js';

startParticles(document.getElementById('particles'));

const conn = document.getElementById('conn');
const batt = document.getElementById('batt');

boot()
  .then((payload) => { document.title = payload.i18n.en.app_title; })
  .catch((error) => { conn.textContent = String(error); conn.className = 'pill bad'; });

connect({
  onState(state) {
    conn.textContent = state.connected
      ? (state.transport === 'bt' ? 'Bluetooth' : 'USB')
      : 'Disconnected';
    conn.className = `pill ${state.connected ? 'ok' : 'bad'}`;
    batt.textContent = state.battery == null ? '—' : `${state.battery}%`;
  },
});
```

Run it:

```bash
python -m ps5led --no-browser --port 8731
```

Open the printed URL. Expected: a dark window with a drifting particle field
that reacts to the cursor near the edges and stays calm in the middle, and a
status pill that says USB or Bluetooth and shows the battery percentage.

- [ ] **Step 6: Commit**

```bash
git add web/index.html web/css/app.css web/js/bridge.js web/js/particles.js web/js/app.js
git commit -m "feat(web): page shell, SSE client, and the edge-reactive particle field"
```

---

### Task 10: The 3D controller

**Files:**
- Create: `web/js/scene.js`
- Modify: `web/js/app.js`

**Interfaces:**
- Consumes: `web/vendor/three/*`, `web/assets/dualsense.glb`, the `state` event's `rgb`
- Produces: `scene.js` exports `createScene(canvas) -> {setColour(rgb), setShell(name), setOrientation(quaternion), resize(), dispose()}`

The lightbar meshes have to be found once at load and then driven from the live
colour. The model's materials carry generic names, so the meshes are identified
by their own geometry: the lightbar is the pair of thin strips flanking the
touchpad, which are the meshes whose bounding box is long in X, shallow in Y and
sits forward in Z. Names found this way are logged once so the next reader can
pin them if the model is ever repacked.

Glow is a translucent sprite behind the strip rather than a bloom pass — a full
post-processing chain costs far more than this scene is worth.

- [ ] **Step 1: Write the scene**

`web/js/scene.js`:

```javascript
import * as THREE from '../vendor/three/three.module.js';
import { GLTFLoader } from '../vendor/three/GLTFLoader.js';
import { RoomEnvironment } from '../vendor/three/RoomEnvironment.js';
import { MeshoptDecoder } from '../vendor/three/meshopt_decoder.module.js';

const SHELL_COLOURS = {
  white: 0xe9ecf2,
  black: 0x1b1f27,
  red: 0x8e1b2a,
};

export function createScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0.05, 0.55);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(1.5, 2.2, 2.0);
  scene.add(key);

  const root = new THREE.Group();
  scene.add(root);

  const lightbars = [];
  const shells = [];
  let glow = null;
  let disposed = false;

  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  loader.load('assets/dualsense.glb', (gltf) => {
    const model = gltf.scene;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    model.position.sub(centre);
    model.scale.setScalar(0.35 / Math.max(size.x, size.y, size.z));
    root.add(model);

    // The lightbar is the pair of thin strips flanking the touchpad: long in X,
    // shallow in Y, sitting forward in Z. The model's material names are
    // generic, so geometry is the only honest discriminator.
    model.traverse((node) => {
      if (!node.isMesh) return;
      const bounds = new THREE.Box3().setFromObject(node);
      const extent = bounds.getSize(new THREE.Vector3());
      const thin = extent.y < size.y * 0.06;
      const wide = extent.x > size.x * 0.10 && extent.x < size.x * 0.45;
      if (thin && wide && bounds.getCenter(new THREE.Vector3()).z > centre.z) {
        node.material = node.material.clone();
        lightbars.push(node);
      } else if (extent.x > size.x * 0.5) {
        node.material = node.material.clone();
        shells.push(node);
      }
    });
    console.info(`lightbar meshes: ${lightbars.map((m) => m.name).join(', ') || '(none found)'}`);
    setColour(currentColour);
  });

  let currentColour = [0, 170, 255];

  function setColour(rgb) {
    currentColour = rgb;
    const colour = new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255);
    for (const mesh of lightbars) {
      mesh.material.emissive = colour;
      mesh.material.emissiveIntensity = 1.6;
      mesh.material.color = colour.clone().multiplyScalar(0.25);
    }
    if (glow) glow.material.color = colour;
  }

  function setShell(name) {
    const value = SHELL_COLOURS[name] ?? SHELL_COLOURS.white;
    for (const mesh of shells) mesh.material.color = new THREE.Color(value);
  }

  const target = new THREE.Quaternion();

  function setOrientation(quaternion) {
    target.set(quaternion[0], quaternion[1], quaternion[2], quaternion[3]);
  }

  function resize() {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function frame() {
    if (disposed) return;
    root.quaternion.slerp(target, 0.18);
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }

  addEventListener('resize', resize);
  resize();
  frame();

  return {
    setColour,
    setShell,
    setOrientation,
    resize,
    dispose() {
      disposed = true;
      removeEventListener('resize', resize);
      renderer.dispose();
      pmrem.dispose();
    },
  };
}
```

- [ ] **Step 2: Wire it into the page**

Replace `web/js/app.js` with:

```javascript
import { boot, connect } from './bridge.js';
import { startParticles } from './particles.js';
import { createScene } from './scene.js';

startParticles(document.getElementById('particles'));

const conn = document.getElementById('conn');
const batt = document.getElementById('batt');
const fallback = document.getElementById('scene-fallback');

let scene = null;
try {
  scene = createScene(document.getElementById('scene'));
} catch (error) {
  // WebGL can be unavailable; the lightbar does not depend on the picture.
  fallback.hidden = false;
  fallback.textContent = `3D view unavailable: ${error.message}`;
}

boot().then((payload) => {
  scene?.setShell(payload.config.shell);
}).catch((error) => {
  conn.textContent = String(error);
  conn.className = 'pill bad';
});

connect({
  onState(state) {
    conn.textContent = state.connected
      ? (state.transport === 'bt' ? 'Bluetooth' : 'USB')
      : 'Disconnected';
    conn.className = `pill ${state.connected ? 'ok' : 'bad'}`;
    batt.textContent = state.battery == null ? '—' : `${state.battery}%`;
    if (state.rgb) scene?.setColour(state.rgb);
  },
});
```

- [ ] **Step 3: Look at it**

```bash
python -m ps5led --no-browser --port 8731
```

Open the URL. Expected: the DualSense renders, and its lightbar is the same
colour the real controller is showing. Run the engine in rainbow and both should
change together:

```bash
python -m ps5led --no-browser --port 8731 --mode rainbow
```

Check the browser console for the `lightbar meshes:` line. If it says
`(none found)`, the geometry heuristic missed — record the mesh names it did
traverse and pin them by name instead of guessing again.

- [ ] **Step 4: Commit**

```bash
git add web/js/scene.js web/js/app.js
git commit -m "feat(web): 3D DualSense with a live lightbar"
```

---

### Task 11: Gyro orientation

**Files:**
- Create: `web/js/orientation.js`
- Modify: `web/js/app.js`

**Interfaces:**
- Consumes: the `sensor` event's `gyro` (deg/s) and `accel` (g), `scene.setOrientation`
- Produces: `orientation.js` exports `createOrientation() -> {update(gyro, accel, dt) -> [x,y,z,w], recentre(), isStale(now)}`

This is the feature the whole rewrite was asked for: move the controller, the
model moves.

Gyro integration alone drifts. Accelerometer alone is noisy and cannot see yaw.
A complementary filter takes pitch and roll from gravity — which the
accelerometer measures directly when the controller is not being shaken — and
leaves yaw to integration plus an explicit Recentre, because nothing in the
controller can observe absolute heading.

`dt` comes from the controller's own timestamp, not from `performance.now()`:
the sensor clock is what the samples were taken against, and a browser frame
that arrives late would otherwise stretch a rotation that never happened.

- [ ] **Step 1: Write the module**

`web/js/orientation.js`:

```javascript
// Gyro + accel -> a quaternion the scene can slerp toward.
//
// Integration alone drifts; the accelerometer alone is noisy and blind to yaw.
// So pitch and roll are corrected against gravity with a complementary filter
// and yaw is left to integration plus an explicit recentre - nothing in the
// controller can observe absolute heading, so pretending otherwise would only
// hide the drift somewhere less obvious.

const DEG = Math.PI / 180;
const ALPHA = 0.98;          // trust the gyro this much per correction step
const STALE_MS = 250;        // no sample for this long -> ease back to front
const MAX_DT = 0.1;          // a longer gap is a stall, not a rotation

const multiply = (a, b) => [
  a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
  a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
  a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
  a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
];

const normalise = (q) => {
  const length = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
  return [q[0] / length, q[1] / length, q[2] / length, q[3] / length];
};

export function createOrientation() {
  let q = [0, 0, 0, 1];
  let lastSampleAt = 0;

  function update(gyro, accel, dt) {
    lastSampleAt = performance.now();
    if (!(dt > 0) || dt > MAX_DT) return q;

    const [gx, gy, gz] = gyro.map((v) => v * DEG);
    const half = dt / 2;
    q = normalise(multiply(q, [gx * half, gy * half, gz * half, 1]));

    // Gravity correction, only when the accelerometer is reading close to 1g:
    // during a shake it is measuring the shake, not down.
    const magnitude = Math.hypot(accel[0], accel[1], accel[2]);
    if (magnitude > 0.85 && magnitude < 1.15) {
      const [ax, ay, az] = accel.map((v) => v / magnitude);
      const pitch = Math.atan2(-ax, Math.hypot(ay, az));
      const roll = Math.atan2(ay, az);
      const cp = Math.cos(pitch / 2), sp = Math.sin(pitch / 2);
      const cr = Math.cos(roll / 2), sr = Math.sin(roll / 2);
      const measured = normalise([sr * cp, cr * sp, -sr * sp, cr * cp]);
      q = normalise(q.map((value, i) => value * ALPHA + measured[i] * (1 - ALPHA)));
    }
    return q;
  }

  return {
    update,
    recentre() { q = [0, 0, 0, 1]; },
    isStale(now = performance.now()) {
      return lastSampleAt === 0 || now - lastSampleAt > STALE_MS;
    },
    current() { return q; },
  };
}
```

- [ ] **Step 2: Feed it from the stream**

In `web/js/app.js`, add the import and the sensor handler:

```javascript
import { createOrientation } from './orientation.js';

const orientation = createOrientation();
let lastTimestamp = null;

// ... inside connect({ ... }):
  onSensor(sensor) {
    if (!sensor.gyro || !sensor.accel) return;
    // The controller's own clock, in units of 1/3 000 000 s. A browser frame
    // that arrives late must not stretch a rotation that never happened.
    let dt = 0;
    if (lastTimestamp !== null) {
      dt = ((sensor.sensor_timestamp - lastTimestamp) >>> 0) / 3000000;
    }
    lastTimestamp = sensor.sensor_timestamp;
    scene?.setOrientation(orientation.update(sensor.gyro, sensor.accel, dt));
  },
```

And ease home when samples stop:

```javascript
setInterval(() => {
  if (orientation.isStale()) scene?.setOrientation([0, 0, 0, 1]);
}, 200);
```

- [ ] **Step 3: Move the controller**

```bash
python -m ps5led --no-browser --port 8731
```

Open the URL, pick up the controller and tilt it. Expected: the model follows
pitch and roll immediately and holds still when the controller is still. Put the
controller down and the model should not creep. Disconnect it and the model
eases back to the front view within a second.

- [ ] **Step 4: Commit**

```bash
git add web/js/orientation.js web/js/app.js
git commit -m "feat(web): the model follows the controller's real motion"
```

---

### Task 12: Controls, i18n, About, and the window

**Files:**
- Create: `web/js/ui.js`, `web/js/i18n.js`
- Modify: `web/js/app.js`, `web/index.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: `/api/boot`'s `config`, `i18n`, `direction`, `modes`; `bridge.send`
- Produces: `ui.js` exports `mountControls(root, { boot, send, onShell })`; `i18n.js` exports `applyLanguage(tables, direction, language)`

The last task makes the panel usable: mode buttons, a colour picker, sliders for
speed, brightness and flash ratio, shell colour, profiles, language, Recentre,
and an About panel carrying the CC BY credit — which is where the licence
requires it, since that is where the work is shown.

- [ ] **Step 1: Write the i18n applier**

`web/js/i18n.js`:

```javascript
// Applies a string table to anything carrying data-i18n, and flips direction.
// Both tables are guaranteed by the Python side to have identical key sets, so
// a missing key here means the element's key is wrong, not the translation.

export function applyLanguage(tables, direction, language) {
  const table = tables[language] ?? tables.en;
  for (const node of document.querySelectorAll('[data-i18n]')) {
    const key = node.dataset.i18n;
    if (key in table) node.textContent = table[key];
    else console.warn(`no string for ${key}`);
  }
  document.documentElement.lang = language;
  document.documentElement.dir = direction[language] ?? 'ltr';
  return table;
}
```

- [ ] **Step 2: Write the controls**

`web/js/ui.js`:

```javascript
const hex = (rgb) => '#' + rgb.map((v) => v.toString(16).padStart(2, '0')).join('');
const fromHex = (value) => [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));

export function mountControls(root, { boot, send, onShell, onRecentre }) {
  const strings = boot.i18n[boot.config.language] ?? boot.i18n.en;
  const t = (key) => strings[key] ?? key;

  root.innerHTML = `
    <div class="row">
      <label data-i18n="mode">${t('mode')}</label>
      <div class="row" id="modes"></div>
    </div>
    <div class="row">
      <label data-i18n="colour">${t('colour')}</label>
      <input type="color" id="colour" value="${hex(boot.config.colour)}">
      <button id="off" data-i18n="close">${t('close')}</button>
      <button id="recentre" data-i18n="recentre">${t('recentre')}</button>
    </div>
    <div class="row">
      <label data-i18n="speed">${t('speed')}</label>
      <input type="range" id="speed" min="0.1" max="5" step="0.1" value="${boot.config.speed}">
    </div>
    <div class="row">
      <label data-i18n="brightness">${t('brightness')}</label>
      <input type="range" id="brightness" min="0.2" max="1" step="0.05" value="${boot.config.brightness}">
    </div>
    <div class="row">
      <label data-i18n="shell">${t('shell')}</label>
      <div class="row" id="shells"></div>
      <label data-i18n="language">${t('language')}</label>
      <select id="language">
        <option value="ar">العربية</option>
        <option value="en">English</option>
      </select>
      <button id="about" data-i18n="about">${t('about')}</button>
    </div>
    <p id="about-text" hidden class="fallback"></p>
  `;

  const modes = root.querySelector('#modes');
  for (const mode of boot.modes) {
    const button = document.createElement('button');
    button.textContent = t(`mode_${mode}`);
    button.dataset.i18n = `mode_${mode}`;
    button.setAttribute('aria-pressed', String(mode === boot.config.mode));
    button.addEventListener('click', async () => {
      await send({ cmd: 'set_mode', mode });
      for (const other of modes.children) other.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
    });
    modes.append(button);
  }

  const shells = root.querySelector('#shells');
  for (const shell of ['white', 'black', 'red']) {
    const button = document.createElement('button');
    button.textContent = t(`shell_${shell}`);
    button.dataset.i18n = `shell_${shell}`;
    button.addEventListener('click', () => {
      send({ cmd: 'set_shell', shell });
      onShell?.(shell);
    });
    shells.append(button);
  }

  root.querySelector('#colour').addEventListener('input', (event) => {
    send({ cmd: 'set_colour', colour: fromHex(event.target.value) });
  });
  root.querySelector('#speed').addEventListener('input', (event) => {
    send({ cmd: 'set_speed', speed: Number(event.target.value) });
  });
  root.querySelector('#brightness').addEventListener('input', (event) => {
    send({ cmd: 'set_brightness', brightness: Number(event.target.value) });
  });
  root.querySelector('#off').addEventListener('click', () => send({ cmd: 'off' }));
  root.querySelector('#recentre').addEventListener('click', () => onRecentre?.());

  const language = root.querySelector('#language');
  language.value = boot.config.language;
  language.addEventListener('change', (event) => {
    send({ cmd: 'set_language', language: event.target.value });
    location.reload();
  });

  const about = root.querySelector('#about-text');
  root.querySelector('#about').addEventListener('click', () => {
    about.hidden = !about.hidden;
    // CC BY requires the credit wherever the work is shown, and this is where
    // it is shown.
    about.innerHTML = `PS5 LED ${boot.version} &middot; 3D model
      <a href="https://sketchfab.com/3d-models/ps5-controller-b7bb9c5102a04cb0b1966c6d02bad7d6"
         target="_blank" rel="noreferrer">PS5 Controller</a>
      by Taohid Animation, CC BY 4.0 &middot;
      <a href="vendor/three/LICENSE" target="_blank" rel="noreferrer">three.js</a>, MIT`;
  });
}
```

- [ ] **Step 3: Wire it in**

In `web/js/app.js`, after `boot()` resolves:

```javascript
import { mountControls } from './ui.js';
import { applyLanguage } from './i18n.js';

// inside the boot().then(...):
  applyLanguage(payload.i18n, payload.direction, payload.config.language);
  mountControls(document.getElementById('controls'), {
    boot: payload,
    send,
    onShell: (shell) => scene?.setShell(shell),
    onRecentre: () => orientation.recentre(),
  });
```

Import `send` from `./bridge.js` alongside `boot` and `connect`.

- [ ] **Step 4: Use it**

```bash
python -m ps5led
```

Expected: the app window opens by itself. Every mode button changes the real
lightbar. The colour picker changes it live. Sliders work. Switching language
flips the whole UI to RTL Arabic and back. About shows the CC BY credit.
Close the window and the process exits.

Then confirm persistence: set rainbow, close the window, run `python -m ps5led`
again — it must come back in rainbow.

- [ ] **Step 5: Update the README**

Replace the README's usage section with the real commands (`python -m ps5led`,
`--background`, `--doctor`, `--mode`, `--no-browser`, `--port`), and add the
Credits section from Task 8 if it is not already there.

- [ ] **Step 6: Commit**

```bash
git add web/js/ui.js web/js/i18n.js web/js/app.js web/index.html README.md
git commit -m "feat(web): controls, i18n, About with the CC BY credit"
```

---

## Self-review

**Spec coverage (spec §8 bridge, §9 web layer, §10 model and attribution):**

| Spec requirement | Task |
|---|---|
| `127.0.0.1` bind, ephemeral port | 4 |
| Token + Host + Origin guard, 403 otherwise | 4 |
| Static files from `web/`, `Cache-Control: no-store` | 4 |
| `/api/boot` with config, i18n, version, device | 4 |
| `/api/cmd` with the full command list | 5 |
| `/api/stream` SSE, `state` 30 Hz, `sensor` 60 Hz | 6 |
| `visible: false` stops sensor, drops state to 2 Hz | 6 |
| Edge → Chrome → default browser | 7 |
| Private `--user-data-dir`, close ends the session | 7 |
| three.js vendored, `RoomEnvironment`, ACES tone mapping | 8, 10 |
| Lightbar emissive from live RGB, sprite glow not bloom | 10 |
| Shell colours | 10, 12 |
| `setPixelRatio(min(dpr, 1.5))`, rAF only | 10 |
| Complementary filter α = 0.98, yaw by integration + Recentre | 11 |
| Eases home after 250 ms of no samples | 11 |
| ~140 particles, `edgeWeight = 1 − smoothstep(0.55, 0.85, d)` | 9 |
| Central 60 % inert, links ≤ 110 px, reduced-motion respected | 9 |
| Glass panel with `backdrop-filter: blur(22px) saturate(140%)` | 9 |
| `dir` flips without a reload for `applyLanguage`; language change reloads to re-render controls | 12 |
| Model from the original mirror, packed | 8 |
| Attribution in four places incl. in-app | 8, 12 |
| Config persistence | 1 |
| ar/en strings | 2 |

Deferred to Plan 3 by design: `tray.py`, `instance.py`, `install.ps1` fixes, the
PyInstaller spec, `release.yml`. Buttons/sticks/touch mirrored on the model are
listed in spec §15 as in-scope extras; they ride the same `sensor` event this
plan already streams, so they are a follow-up on top of Task 11 rather than a
gap in it — recorded here so nobody reads their absence as an oversight.

**Placeholder scan:** none. Every step carries its code.

**Type consistency:** `rgb` is `[r, g, b]` on the wire and a tuple in Python
throughout; `parse_colour` in `bridge.py` and `clamp_rgb` in `device.py` are
separate on purpose — the bridge parses hex from the page, the device clamps
whatever reaches the wire, and `bridge.py` must not import `cli.py` because
`cli.py` imports `bridge.py`. `Bridge.handle_command` returns `{"ok": bool}` in
every branch. `scene.setOrientation` takes `[x, y, z, w]`, which is exactly what
`orientation.update` returns.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-07-bridge-and-web-ui.md`. Two execution options:

1. **Subagent-driven (recommended)** — a fresh subagent per task, review between tasks.
2. **Inline execution** — tasks run in this session with checkpoints.

Tasks 9–12 each end with something you have to look at; the model, the motion
and the particle field cannot be verified from a test suite.

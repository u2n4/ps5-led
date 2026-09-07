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

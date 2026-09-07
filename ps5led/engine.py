"""Lighting modes.

The colour maths is a pure function so it can be tested without a thread and
without a controller. The thread only advances a phase and writes when the
result actually changed — a solid colour costs one write, not thirty a second.
"""

import math
import threading

MODES = ("manual", "rainbow", "wave", "flash", "battery")

_DEFAULT_COLOUR = (0, 170, 255)


def hsv_to_rgb(h, s, v):
    """HSV in [0, 1] to 8-bit RGB."""
    h = h % 1.0
    if s <= 0:
        level = int(v * 255)
        return (level, level, level)
    sector = int(h * 6.0)
    offset = h * 6.0 - sector
    p = v * (1.0 - s)
    q = v * (1.0 - s * offset)
    t = v * (1.0 - s * (1.0 - offset))
    table = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))
    return tuple(int(channel * 255) for channel in table[sector % 6])


def _scale(rgb, factor):
    return tuple(max(0, min(255, int(channel * factor))) for channel in rgb)


def colour_for(mode, phase, settings):
    """The colour this mode shows at ``phase`` in [0, 1)."""
    base = settings.get("colour") or _DEFAULT_COLOUR
    brightness = settings.get("brightness", 1.0)

    if mode == "rainbow":
        return hsv_to_rgb(phase, 1.0, brightness)
    if mode == "wave":
        factor = (math.sin(phase * 2 * math.pi) + 1.0) / 2.0
        return _scale(base, brightness * (0.15 + 0.85 * factor))
    if mode == "flash":
        duty = settings.get("duty", 0.5)
        return _scale(base, brightness) if phase < duty else (0, 0, 0)
    if mode == "battery":
        level = settings.get("battery")
        if level is not None:
            # 0 % red through 100 % green, along the hue circle's short arc.
            return hsv_to_rgb((level / 100.0) / 3.0, 1.0, brightness)
    return _scale(base, brightness)


class Engine(threading.Thread):
    """Drives ``write_colour`` at a fixed interval, only when the colour changed."""

    def __init__(self, state, write_colour, interval=1 / 30.0):
        threading.Thread.__init__(self, name="ps5led-engine", daemon=True)
        self._state = state
        self._write = write_colour
        self._interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._mode = "manual"
        self._settings = {"colour": _DEFAULT_COLOUR, "brightness": 1.0,
                          "duty": 0.5, "battery": None}
        self._speed = 1.0
        self._last_written = None

    def set_mode(self, mode):
        with self._lock:
            self._mode = mode

    def set_colour(self, rgb):
        with self._lock:
            self._settings["colour"] = tuple(rgb)

    def set_setting(self, key, value):
        with self._lock:
            self._settings[key] = value

    def set_speed(self, speed):
        with self._lock:
            self._speed = max(0.1, min(5.0, float(speed)))

    def stop(self):
        self._stop.set()
        if self.is_alive():
            self.join(timeout=2.0)

    def run(self):
        phase = 0.0
        while not self._stop.is_set():
            with self._lock:
                mode = self._mode
                settings = dict(self._settings)
                speed = self._speed
            rgb = colour_for(mode, phase, settings)
            if rgb != self._last_written:
                self._last_written = rgb
                self._state.update(rgb=rgb, mode=mode)
                try:
                    self._write(rgb)
                except Exception:
                    # A device that vanished is DeviceManager's problem to
                    # notice and recover from; the engine must keep running.
                    pass
            phase = (phase + self._interval * speed * 0.5) % 1.0
            self._stop.wait(self._interval)

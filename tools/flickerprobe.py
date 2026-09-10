"""Measure what the lightbar write path actually does under the Rainbow load.

Ali reports the bar blinking off and back, worse over Bluetooth. His config
runs Rainbow, which the engine drives at 60 output reports a second,
unconditionally. Nothing in the app records write latency, write failures or
silent reconnects, so this reproduces the engine's exact cadence against the
real controller and records all three.

    python tools/flickerprobe.py [seconds] [hz]

Prints per-write latency percentiles, every write that failed or stalled,
and every connect/disconnect transition seen while running.
"""
import colorsys
import pathlib
import statistics
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ps5led.device as devmod  # noqa: E402
from ps5led.device import DeviceManager  # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
HZ = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
# Third argument picks the transport when the pad is on both, as it is when
# the cable is in while it is also paired. The manager's own choice is first
# match in enumeration order, which is USB here; the flicker is reported over
# Bluetooth, so that is the one that needs measuring.
PREFER = sys.argv[3] if len(sys.argv) > 3 else None
if PREFER:
    _orig_choose = devmod.choose_device

    def _prefer(infos):
        wanted = [i for i in infos if i.transport == PREFER]
        return _orig_choose(wanted) if wanted else _orig_choose(infos)

    devmod.choose_device = _prefer


class State:
    def __init__(self):
        self.v = {}
        self.lock = threading.Lock()
        self.transitions = []

    def update(self, **kw):
        with self.lock:
            before = self.v.get("connected")
            self.v.update(kw)
            after = self.v.get("connected")
            if "connected" in kw and before != after:
                self.transitions.append((time.monotonic(), after,
                                         kw.get("transport") or self.v.get("transport")))

    def snapshot(self):
        with self.lock:
            return dict(self.v)


state = State()
m = DeviceManager(state)
m.start()

t0 = time.monotonic()
while time.monotonic() - t0 < 15 and not state.snapshot().get("connected"):
    time.sleep(0.1)
snap = state.snapshot()
if not snap.get("connected"):
    print("no controller connected; last_error:", m.describe().get("last_error"))
    m.stop()
    sys.exit(1)
print("connected: %s over %s" % (snap.get("product"), snap.get("transport")))
print("driving %.0f Hz for %.0f s, Rainbow pattern (speed 5.0)\n" % (HZ, SECONDS))

lat = []
fails = []
stalls = []
started = time.monotonic()
interval = 1.0 / HZ
n = 0
prev_rgb = None
identical = 0
while time.monotonic() - started < SECONDS:
    u = ((time.monotonic() - started) % 5.0) / 5.0
    r, g, b = [int(255 * x) for x in colorsys.hsv_to_rgb(u, 1.0, 0.9)]
    rgb = (r, g, b)
    if rgb == prev_rgb:
        identical += 1
    prev_rgb = rgb
    t = time.perf_counter()
    ok = m.write_colour(rgb)
    dt = (time.perf_counter() - t) * 1000.0
    lat.append(dt)
    n += 1
    if not ok:
        d = m.describe()
        fails.append((round(time.monotonic() - started, 2), d.get("last_error"), d.get("last_write_error")))
    if dt > 100:
        stalls.append((round(time.monotonic() - started, 2), round(dt, 1)))
    time.sleep(interval)

# Anything after this instant is our own teardown, not the device dropping.
stopped_at = time.monotonic()
m.stop()
state.transitions = [t for t in state.transitions if t[0] < stopped_at]

lat_sorted = sorted(lat)
p = lambda q: lat_sorted[min(len(lat_sorted) - 1, int(q * len(lat_sorted)))]
print("writes attempted     :", n)
print("identical to previous:", identical, "(%.0f%% of frames carried no change)" % (100.0 * identical / max(1, n)))
print("latency ms  median %.2f  p95 %.2f  p99 %.2f  max %.2f" % (
    statistics.median(lat), p(0.95), p(0.99), max(lat)))
print("writes > 100 ms      :", len(stalls), stalls[:10])
print("write failures       :", len(fails))
for f in fails[:10]:
    print("    t=%ss  last_error=%r  last_write_error=%r" % f)
print("connect transitions  :", len(state.transitions))
for ts, conn, tr in state.transitions:
    print("    t=%.2fs  %s  %s" % (ts - started, "CONNECTED" if conn else "DROPPED", tr))
print()
if fails or len(state.transitions) > 1:
    print("VERDICT: the write path is failing or reconnecting under this load")
elif stalls:
    print("VERDICT: writes are stalling; the link cannot keep up with this rate")
else:
    print("VERDICT: writes are clean at this rate on this transport")

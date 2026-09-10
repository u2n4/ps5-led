"""Run the app's REAL engine in Rainbow against the real controller and measure.

tools/flickerprobe.py drives DeviceManager directly, which bypasses the
per-transport rate gate in Engine._send. This drives the Engine itself, so
what is measured is what the app does.

    python tools/engineprobe.py [seconds]

Reports the transport, writes that reached the device, write failures,
and connect/disconnect transitions while running.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import dualled_pro as dp  # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0

backend = dp.Backend()
transitions = []
_orig_update = backend.update


def spy_update(**kw):
    before = backend.snapshot().get("connected")
    _orig_update(**kw)
    if "connected" in kw and kw["connected"] != before:
        transitions.append((time.monotonic(), kw["connected"], backend.snapshot().get("transport")))


backend.update = spy_update
backend.connect()
t0 = time.monotonic()
while time.monotonic() - t0 < 15 and not backend.snapshot().get("connected"):
    time.sleep(0.1)
snap = backend.snapshot()
if not snap.get("connected"):
    print("no controller; last_error:", backend._manager.describe().get("last_error"))
    backend.close(); sys.exit(1)
print("connected: %s over %s" % (snap.get("product"), snap.get("transport")))

engine = dp.Engine(backend)
engine.mode = "Rainbow"; engine.speed = 5.0
sent = [0]; failed = [0]
_orig_send = engine._send


def counting_send(rgb, force=False):
    ok = _orig_send(rgb, force=force)
    sent[0] += 1
    if not ok: failed[0] += 1
    return ok


engine._send = counting_send
writes_before = None
started = time.monotonic()
engine.start()
time.sleep(SECONDS)
engine.stop_evt.set(); engine.join(timeout=3)
stopped_at = time.monotonic()
backend.close()
transitions = [t for t in transitions if t[0] < stopped_at]

elapsed = stopped_at - started
print("engine ticks (_send calls) : %d  (%.0f/s)" % (sent[0], sent[0] / elapsed))
print("write failures             : %d" % failed[0])
print("connect transitions        : %d" % len(transitions))
for ts, conn, tr in transitions:
    print("    t=%.2fs  %s  %s" % (ts - started, "CONNECTED" if conn else "DROPPED", tr))
if failed[0] or len(transitions) > 1:
    print("VERDICT: the engine still fails or drops the link on this transport")
else:
    print("VERDICT: clean -- no failures, no drops, over %s" % snap.get("transport"))

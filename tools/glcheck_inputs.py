"""Do the model's parts actually move when the controller's do?

Wiring a transform proves nothing on its own -- a pivot in the wrong place, an
empty index list, or a part name that never matches all render identically to
"nothing moved". So this renders a resting controller, then renders each input
in turn, and compares the framebuffers.

Synthetic samples, deliberately: this has to be reproducible without hands on
the hardware. Whether bit 4 really is Square is a question for the real
controller, and tools/buttoncheck.py answers that one.
"""
import pathlib
import sys
import time
import tkinter as tk

# Run from tools/; the app lives one level up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tkinter import ttk

import dualled_pro as dp
from OpenGL import GL

import controller_gl as cg

REST = {"connected": True, "gyro": (0, 0, 0), "accel": (0.001, 0.962, 0.152),
        "sensor_timestamp": None, "left_stick": (0.0, 0.0),
        "right_stick": (0.0, 0.0), "triggers": (0.0, 0.0), "buttons": 8}


def sample(**over):
    s = dict(REST)
    s.update(over)
    return s


root = tk.Tk()
root.geometry("700x300")
ttk.Style().configure("Card.TFrame")
view = dp.ControllerView(root, controller_type="ps5", width=680, height=260,
                         bg="#0b0f14")
view.pack(fill="both", expand=True)
if view.backend != "gl":
    print("backend is", view.backend, "- cannot test part motion")
    root.destroy(); sys.exit(1)

gl = view.gl
gl.orbit.gyro_enabled = False

def render(s):
    view.update_inputs(s)
    target = gl.frame_count + 2
    deadline = time.time() + 15
    while time.time() < deadline and gl.frame_count < target:
        gl.request_draw(); root.update(); time.sleep(0.03)
    gl.tkMakeCurrent()
    w, h = gl.winfo_width(), gl.winfo_height()
    GL.glReadBuffer(GL.GL_FRONT)
    raw = GL.glReadPixels(0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    return bytes(raw)


base = render(sample())

# The split has to produce two non-empty halves, or a "part" silently renders
# nothing and every comparison below would read as "no movement".
parts = {}
for entry in gl.meshes:
    parts.setdefault(entry[5], 0)
    parts[entry[5]] += len(entry[3])
print("index counts per part:")
for name in sorted(parts, key=lambda k: (k is None, k)):
    print("   %-14s %d" % (name or "(static)", parts[name]))
missing = [p for p in ("stick_left", "stick_right", "trigger_left",
                       "trigger_right", "bumper_left", "bumper_right",
                       "square", "circle", "triangle", "cross", "dpad",
                       "touchpad") if not parts.get(p)]
print("parts with no geometry:", missing or "none")
print()


cases = [
    ("left stick pushed",  sample(left_stick=(1.0, 0.0))),
    ("right stick pushed", sample(right_stick=(0.0, 1.0))),
    ("L2 pulled",          sample(triggers=(1.0, 0.0))),
    ("R2 pulled",          sample(triggers=(0.0, 1.0))),
    ("square held",        sample(buttons=8 | (1 << cg.BUTTON_BITS["square"]))),
    ("circle held",        sample(buttons=8 | (1 << cg.BUTTON_BITS["circle"]))),
    ("triangle held",      sample(buttons=8 | (1 << cg.BUTTON_BITS["triangle"]))),
    ("cross held",         sample(buttons=8 | (1 << cg.BUTTON_BITS["cross"]))),
    ("d-pad up",           sample(buttons=0)),
    ("L1 held",            sample(buttons=8 | (1 << 8))),
    ("R1 held",            sample(buttons=8 | (1 << 9))),
    ("touchpad clicked",   sample(buttons=8 | (1 << 17))),
]

print("%-20s %12s" % ("input", "pixels moved"))
results = []
for label, s in cases:
    frame = render(s)
    moved = sum(1 for a, b in zip(base, frame) if a != b) // 3
    results.append((label, moved))
    print("%-20s %12d" % (label, moved))
    render(sample())          # back to rest between cases

# R1 and R2 shared one mesh once, so pressing R2 moved the bumper too. If they
# are still fused these two frames are identical.
r2 = render(sample(triggers=(0.0, 1.0)))
render(sample())
r1 = render(sample(buttons=8 | (1 << 9)))
render(sample())
separated = sum(1 for a, b in zip(r1, r2) if a != b) // 3
print()
print("R1 frame vs R2 frame, pixels differing:", separated,
      "(0 would mean they still move together)")

print()
dead = [label for label, moved in results if moved < 50]
if missing:
    print("VERDICT: some parts have no geometry —", ", ".join(missing))
    code = 1
elif dead:
    print("VERDICT: these inputs moved nothing —", ", ".join(dead))
    code = 1
elif separated < 50:
    print("VERDICT: R1 and R2 still move together")
    code = 1
else:
    print("VERDICT: every input moves its part")
    code = 0
root.destroy()
sys.exit(code)

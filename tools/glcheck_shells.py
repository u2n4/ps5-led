"""Do Ali's five shell palettes actually reach the 3D model?

Wiring set_scene() is not proof. This renders each palette, reads the
framebuffer back, and checks the picture really changes -- and that it changes
towards the palette's own shell colour, not just into noise.
"""
import pathlib
import sys

# Run from tools/; the app lives one level up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import sys
import time
import tkinter as tk
from tkinter import ttk

import dualled_pro as dp
from OpenGL import GL

root = tk.Tk()
root.geometry("700x300")
ttk.Style().configure("Card.TFrame")
view = dp.ControllerView(root, controller_type="ps5", width=680, height=260,
                         bg="#0b0f14")
view.pack(fill="both", expand=True)
if view.backend != "gl":
    print("backend is", view.backend, "- cannot test the 3D palette")
    root.destroy(); sys.exit(1)

view.set_led_color(0, 170, 255)


def render():
    target = view.gl.frame_count + 2
    deadline = time.time() + 15
    while time.time() < deadline and view.gl.frame_count < target:
        view.gl.request_draw(); root.update(); time.sleep(0.03)
    view.gl.tkMakeCurrent()
    w, h = view.gl.winfo_width(), view.gl.winfo_height()
    GL.glReadBuffer(GL.GL_FRONT)
    raw = GL.glReadPixels(0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def near(pixels, colour, tol=45):
    r0, g0, b0 = colour
    return sum(1 for r, g, b in pixels
               if abs(r - r0) < tol and abs(g - g0) < tol and abs(b - b0) < tol)


frames = {}
print("%-9s %-18s %-12s %s" % ("shell", "its shell colour", "matching px", "changed vs white"))
for key in ("white", "black", "red", "blue", "purple"):
    # set_shell ignores a repeat of the current key, so force a real switch.
    view._shell = "___"
    view.set_shell(key)
    px = render()
    frames[key] = px
    colour = dp._DS_SHELLS[key]["shell"]
    changed = "-" if key == "white" else str(
        sum(1 for a, b in zip(px, frames["white"]) if a != b))
    print("%-9s %-18s %-12s %s" % (key, str(colour), near(px, colour), changed))

total = len(frames["white"])
distinct_frames = len({tuple(v[::997]) for v in frames.values()})
print()
print("distinct rendered images across the five palettes:", distinct_frames, "of 5")
ok = distinct_frames == 5 and all(near(frames[k], dp._DS_SHELLS[k]["shell"]) > 200
                                  for k in frames)
print("VERDICT:", "all five palettes reach the 3D model"
      if ok else "THE PALETTES ARE NOT REACHING THE MODEL")
root.destroy()
sys.exit(0 if ok else 1)

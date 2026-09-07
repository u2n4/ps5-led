"""Prove the OpenGL preview actually renders, and that the LED colour lands.

Constructing the widget proves nothing: the context is created lazily on map,
and a failure there is exactly the case the fallback exists for. So this maps
the widget, pumps Tk until frames appear, and reads back the framebuffer to
check the lightbar colour is really on screen.
"""
import sys
import time
import tkinter as tk
from tkinter import ttk

import dualled_pro as dp

root = tk.Tk()
root.title("render proof")
root.geometry("700x300")
ttk.Style().configure("Card.TFrame")

view = dp.ControllerView(root, controller_type="ps5", width=680, height=260,
                         bg="#0b0f14")
view.pack(fill="both", expand=True)

if view.backend != "gl":
    print("backend is", view.backend, "- nothing to prove here")
    root.destroy()
    sys.exit(1)

LED = (255, 32, 0)
view.set_shell("white")
view.set_led_color(*LED)

deadline = time.time() + 25
while time.time() < deadline and view.gl.frame_count < 3:
    view.gl.request_draw()
    root.update()
    time.sleep(0.05)

gl = view.gl
print("frames drawn   :", gl.frame_count)
print("renderer       :", gl.renderer_info or "(none reported)")
print("failed flag    :", gl._failed)

if gl.frame_count:
    times = list(gl.frame_times)
    if len(times) > 2:
        span = times[-1] - times[0]
        if span > 0:
            print("frame rate     : %.1f fps over %d frames"
                  % ((len(times) - 1) / span, len(times)))

# Read the framebuffer back and look for the lightbar colour actually on screen.
try:
    from OpenGL import GL
    gl.tkMakeCurrent()
    w, h = gl.winfo_width(), gl.winfo_height()
    GL.glReadBuffer(GL.GL_FRONT)
    raw = GL.glReadPixels(0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    near = sum(1 for r, g, b in px
               if abs(r - LED[0]) < 40 and abs(g - LED[1]) < 40 and abs(b - LED[2]) < 40)
    distinct = len({p for p in px})
    print("pixels read    :", len(px))
    print("distinct colours:", distinct)
    print("pixels matching the LED colour:", near)
    print()
    if distinct > 50 and near > 0:
        print("VERDICT: the model is rendering and the lightbar is showing the LED colour")
    elif distinct > 50:
        print("VERDICT: something is rendering, but the LED colour was not found on screen")
    else:
        print("VERDICT: the surface is blank")
except Exception as exc:
    print("framebuffer read failed:", type(exc).__name__, exc)

root.destroy()

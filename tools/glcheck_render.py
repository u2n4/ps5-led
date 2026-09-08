"""Prove the OpenGL preview actually renders, and that the LED colour lands.

Constructing the widget proves nothing: the context is created lazily on map,
and a failure there is exactly the case the fallback exists for. So this maps
the widget, pumps Tk until frames appear, and reads back the framebuffer to
check the lightbar colour is really on screen.
"""
import pathlib
import sys

# Run from tools/; the app lives one level up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import argparse
import json
import struct
import zlib
import statistics
import time
import tkinter as tk
from tkinter import ttk

import dualled_pro as dp

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=pathlib.Path)
args = parser.parse_args()

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

from OpenGL import GL


def frame():
    if view.gl is None:
        raise AssertionError("renderer fell back: %r" % getattr(view, "_gl_error", None))
    before = view.gl.frame_count
    view.gl.request_draw()
    root.update()
    assert view.gl is not None and view.gl.frame_count > before, "no frame presented"


def pixels():
    gl = view.gl
    gl.tkMakeCurrent()
    w, h = gl.winfo_width(), gl.winfo_height()
    GL.glReadBuffer(GL.GL_FRONT)
    return w, h, bytes(GL.glReadPixels(0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE))


def png(path, w, h, raw):
    def chunk(kind, data):
        return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
    rows = b"".join(b"\0"+raw[y*w*3:(y+1)*w*3] for y in reversed(range(h)))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">2I5B",w,h,8,2,0,0,0))+
                     chunk(b"IDAT", zlib.compress(rows))+chunk(b"IEND",b""))


try:
    root.update()
    frame()
    results = {"renderer": view.gl.renderer_info, "exact_rgb_pixels": {}}
    for led in (LED, (17,93,201), (0,255,0), (187,28,216)):
        view.set_led_color(*led)
        frame()
        w, h, raw = pixels()
        count = sum(raw[i:i+3] == bytes(led) for i in range(0,len(raw),3))
        assert count > 20, ("exact lightbar RGB absent", led, count)
        results["exact_rgb_pixels"][str(led)] = count
    # Generate actual Tk mouse events, including capture/release, not direct rotations.
    gl = view.gl
    gl.event_generate("<ButtonPress-1>", x=180,y=140)
    gl.frame_times.clear()
    durations = []
    started = time.perf_counter()
    for i in range(120):
        tick = time.perf_counter()
        gl.event_generate("<B1-Motion>", x=180+i*2, y=140+(i%20))
        frame()
        durations.append((time.perf_counter()-tick)*1000)
    elapsed = time.perf_counter()-started
    gl.event_generate("<ButtonRelease-1>", x=418,y=159)
    held = gl.orbit.rotation
    for i in range(30):
        view.update_inputs({"connected":False})
        root.update()
    assert gl.orbit.rotation == held and not gl.orbit.dragging
    results["drag"] = {"frames":120,"elapsed_s":round(elapsed,3),
                        "presented_fps":round(120/elapsed,1),
                        "event_to_present_p95_ms":round(sorted(durations)[113],2),
                        "render_median_ms":round(statistics.median(gl.frame_times),2)}
    assert results["drag"]["event_to_present_p95_ms"] < 33.34, "drag misses 30 fps frame budget"
    results["holds_after_release"] = True
    view.reset_view()
    frame()
    assert gl.orbit.rotation == (0,0,0,1)
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True)
        png(args.output/"controller-front.png", *pixels())
        gl.orbit.rotate(-32,22)
        frame()
        png(args.output/"controller-orbit.png", *pixels())
        (args.output/"render.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(json.dumps(results,indent=2))
    print("PASS: exact RGB pixels, mouse drag, static hold, reset and frame budget")
finally:
    root.destroy()

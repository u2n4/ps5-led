"""Does the preview survive a missing OpenGL, and does it use it when present?

Run with no argument to test whatever is installed. Run with `--block-gl` to
simulate the machine this actually ships to, where the two pip packages did
not land -- the case that used to kill the lightbar after a PowerShell install.
"""
import pathlib
import sys

# Run from tools/; the app lives one level up.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import sys
import tkinter as tk

if "--block-gl" in sys.argv:
    # Make the imports fail exactly as they would on a machine without them.
    # find_spec, not find_module: the old hook was removed in Python 3.12, so a
    # finder written against it silently blocks nothing and the test passes on
    # the very path it claims to be disabling.
    class _Blocked:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("OpenGL", "pyopengltk"):
                raise ImportError("blocked for the fallback test: %s" % name)
            return None

    sys.meta_path.insert(0, _Blocked())
    sys.modules.pop("controller_gl", None)
    for mod in [m for m in sys.modules if m.split(".")[0] in ("OpenGL", "pyopengltk")]:
        sys.modules.pop(mod, None)

import dualled_pro as dp

root = tk.Tk()
root.withdraw()
try:
    from tkinter import ttk
    ttk.Style().configure("Card.TFrame")
    view = dp.ControllerView(root, controller_type="ps5", width=680, height=260,
                             bg="#0b0f14")
    print("backend            :", view.backend)
    print("gl widget          :", "yes" if view.gl is not None else "no")
    print("canvas widget      :", "yes" if view.canvas is not None else "no")
    if view.backend == "canvas":
        print("why not gl         :", type(getattr(view, "_gl_error", None)).__name__,
              getattr(view, "_gl_error", ""))

    # The contract the rest of the app calls into, on whichever backend is live.
    view.on_click = lambda e=None: None
    view.set_led_color(255, 0, 128)
    view.set_shell("red")
    view.set_mode("Rainbow")
    view.set_controller_type("ps5")
    view.redraw()
    view.update_inputs({"connected": True, "gyro": (0, 0, 0),
                        "accel": (0.001, 0.962, 0.152),
                        "sensor_timestamp": 1000, "right_stick": (0.0, 0.0)})
    view.set_gyro_enabled(False)
    view.reset_view()
    print("full contract      : OK (no exception)")
    print("led held           :", view._led)
    print("shell held         :", view._shell)
    print()
    print("VERDICT: the preview works on the", view.backend, "backend")
finally:
    root.destroy()

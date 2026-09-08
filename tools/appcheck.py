"""Exercise the real App/Engine/preview using a simulated HID boundary.

Never opens a controller; settings are isolated. Native Tk events and rendered
frames are real. This complements, and never substitutes for, hardware checks.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(args.output / "isolated-settings")
import dualled_pro as dp


class SimulatedHid:
    def __init__(self, state):
        self.state, self.fail, self.connected = state, False, False
        self.writes = []

    def start(self):
        self.connected = True
        self.state.update(connected=True, product="Simulated HID", product_id=0x0ce6,
                          transport="usb", battery=75, charging=False,
                          gyro=(0,0,0), accel=(0.001,0.962,0.152),
                          sensor_timestamp=0, right_stick=(0,0), buttons=8)

    def write_colour(self, rgb):
        if self.fail or not self.connected:
            return False
        self.writes.append(tuple(rgb))
        self.state.update(applied_rgb=tuple(rgb), applied_at=time.monotonic())
        return True

    def stop(self):
        self.connected = False
        self.state.update(connected=False, applied_rgb=None)


dp.CFG.update(language="ar", fullscreen_on_start=False, last_mode="Manual",
              color="#00aaff", bgr_swap=False, stick_view=True)
dp.CFG["auto_sleep"]["enabled"] = False
errors = []
app = None


def pump(seconds=0.15):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        app.update()
        time.sleep(0.005)
    assert not errors, errors
    assert app.ctrl3d.gl is not None, repr(getattr(app.ctrl3d,"_gl_error",None))


def capture(path):
    app.lift()
    app.focus_force()
    pump(0.1)
    env = dict(os.environ)
    for key, value in dict(TK3D_X=app.winfo_rootx(),TK3D_Y=app.winfo_rooty(),
                           TK3D_W=app.winfo_width(),TK3D_H=app.winfo_height(),
                           TK3D_CAPTURE=path).items(): env[key]=str(value)
    script = '''
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Bitmap]::new([int]$env:TK3D_W,[int]$env:TK3D_H)
$gfx = [System.Drawing.Graphics]::FromImage($img)
try {
 $gfx.CopyFromScreen([int]$env:TK3D_X,[int]$env:TK3D_Y,0,0,$img.Size)
 $img.Save($env:TK3D_CAPTURE,[System.Drawing.Imaging.ImageFormat]::Png)
} finally { $gfx.Dispose(); $img.Dispose() }
'''
    subprocess.run(["powershell.exe","-NoProfile","-Command",script],env=env,check=True)


try:
    with patch("ps5led.device.DeviceManager", SimulatedHid):
        app = dp.App()
        app.report_callback_exception = lambda *exc: errors.append(repr(exc))
        app.geometry("1200x1020+50+10")
        app.focus_force()
        pump(0.4)
        app.geometry("1200x900+50+30")
        pump(0.3)
        assert app.card.winfo_reqheight() <= app.card.winfo_height()+2, "settings clipped at default size"
        manager = app.backend._manager
        assert app.ctrl3d.gl.frame_count > 0
        assert not app.gyro_view_var.get() and not app.ctrl3d.gl.orbit.gyro_enabled
        # Success -> failure while the connection stays up -> disconnect.
        dp.CFG["bgr_swap"] = True
        app.set_color_hex("#115dc9")
        pump()
        assert app.ctrl3d._led == (201,93,17)
        manager.fail = True
        app.set_color_hex("#ee7722")
        assert app.ctrl3d._led == (201,93,17), "picker bypassed successful RGB"
        pump()
        assert app.ctrl3d._led == (201,93,17)
        manager.stop()
        pump()
        assert app.ctrl3d._led == (0,0,0) and app.preview.cget("bg") == "#000000"
        assert app.s["view_waiting"] in app.view_state_var.get()
        manager.fail = False
        manager.start()
        dp.CFG["bgr_swap"] = False
        app.engine.set_color((0,170,255))
        pump()
        assert app.ctrl3d._led == (0,170,255)
        # All existing effects continue through the actual engine thread.
        effect_checks = []
        for mode in dp.MODE_CODE:
            app.engine.set_mode(mode)
            app.engine.set_speed(0.1)
            pump(0.28)
            wire = app.backend.snapshot()["applied_rgb"]
            assert wire is not None
            effect_checks.append(mode)
        app.engine.set_mode("Manual")
        app.set_color_hex("#00aaff")
        pump()
        for key in app._shell_keys:
            app.shell_cmb.current(app._shell_keys.index(key))
            app.shell_cmb.event_generate("<<ComboboxSelected>>")
            pump(0.04)
            assert app.ctrl3d._shell == key
        app.shell_cmb.current(0)
        app.shell_cmb.event_generate("<<ComboboxSelected>>")
        app.gyro_view_check.invoke()
        assert app.ctrl3d.gl.orbit.gyro_enabled
        app.gyro_view_check.invoke()
        app.stick_view_check.invoke()
        assert not app.ctrl3d.gl.orbit.stick_enabled
        app.stick_view_check.invoke()
        app.lang_cmb.set("English")
        app.on_lang()
        assert app.gyro_view_check.cget("text") == dp.STR["en"]["gyro_view"]
        assert app.stick_view_check.cget("text") == dp.STR["en"]["stick_view"]
        pump()
        capture(args.output/"app-en.png")
        app.lang_cmb.set("العربية")
        app.on_lang()
        app.attributes("-fullscreen", True)
        pump(0.3)
        capture(args.output/"app-ar.png")
        # No new frames while hidden; producer/connection can keep running.
        app.withdraw()
        pump(0.15)
        before = app.ctrl3d.gl.frame_count
        pump(0.45)
        assert app.ctrl3d.gl.frame_count == before
        report = dict(hardware="simulated HID boundary; no hardware accessed",
                      layout={"card_requested":app.card.winfo_reqheight(),"card_actual":app.card.winfo_height()},
                      renderer=app.ctrl3d.gl.renderer_info,
                      successful_rgb_only=True, bgr=True, disconnect_clears_preview=True,
                      reconnect=True, gyro_default_off=True, gyro_toggle=True,
                      stick_toggle=True, five_shells=True, bilingual_labels=True,
                      hidden_frames=0, effect_modes=effect_checks, callback_errors=errors)
        (args.output/"app.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report,indent=2))
finally:
    if app is not None:
        app.bg.stop()
        app.quit_app()

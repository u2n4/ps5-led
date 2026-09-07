"""Does a fresh quick-install actually run?

The installer does not copy the repository. It downloads a specific list of
files, and a list is easy to get wrong -- one missing module and the app dies
on a machine nobody tested. So this builds a directory holding EXACTLY what
install.ps1 fetches, nothing else, and starts the app there.

It runs the check twice: once as a machine that got the optional viewer
packages, and once as a machine that did not. The second is the one that
matters, because a pip failure after a PowerShell install is the original bug
this whole project exists to fix.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent

# Mirrors install.ps1 exactly. Keep the two in step: a file added to the app
# and forgotten here is invisible until someone installs from scratch.
ROOT_FILES = ["dualled_pro.py", "requirements.txt", "controller_gl.py",
              "ATTRIBUTION.md"]
PS5LED_MODULES = ["__init__", "hid_win", "dualsense", "dualshock4", "crc", "device"]
ASSETS = ["dualsense.mesh.json.gz"]
OPTIONAL_ASSETS = ["dualsense-svgrepo.svg", "app.ico"]

PROBE = '''
import sys, tkinter as tk
from tkinter import ttk
import dualled_pro as dp
root = tk.Tk(); root.withdraw()
ttk.Style().configure("Card.TFrame")
view = dp.ControllerView(root, controller_type="ps5", width=680, height=260, bg="#0b0f14")
view.on_click = lambda e=None: None
view.set_led_color(0, 170, 255)
view.set_shell("red")
view.set_mode("Rainbow")
view.redraw()
view.update_inputs({"connected": False})
print("BACKEND:" + view.backend)
root.destroy()
'''

BLOCK = '''
class _Blocked:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("OpenGL", "pyopengltk"):
            raise ImportError("no viewer packages on this machine")
        return None
sys.meta_path.insert(0, _Blocked())
'''


def build(target):
    target.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in ROOT_FILES:
        src = REPO / name
        if src.is_file():
            shutil.copy2(src, target / name)
        else:
            missing.append(name)
    (target / "ps5led").mkdir(exist_ok=True)
    for module in PS5LED_MODULES:
        src = REPO / "ps5led" / (module + ".py")
        if src.is_file():
            shutil.copy2(src, target / "ps5led" / (module + ".py"))
        else:
            missing.append("ps5led/%s.py" % module)
    (target / "assets").mkdir(exist_ok=True)
    for name in ASSETS:
        src = REPO / "assets" / name
        if src.is_file():
            shutil.copy2(src, target / "assets" / name)
        else:
            missing.append("assets/" + name)
    for name in OPTIONAL_ASSETS:
        src = REPO / "assets" / name
        if src.is_file():
            shutil.copy2(src, target / "assets" / name)
    return missing


def run(target, block):
    script = ("import sys\n" + (BLOCK if block else "")) + PROBE
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(target),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=180)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


tmp = pathlib.Path(tempfile.mkdtemp(prefix="installcheck-"))
try:
    missing = build(tmp / "app")
    total = sum(1 for _ in (tmp / "app").rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in (tmp / "app").rglob("*") if f.is_file())
    print("files the installer places :", total)
    print("total download size        : %.2f MB" % (size / 1024 / 1024))
    print("missing from the repo      :", missing or "none")
    print()

    failures = []
    for label, block in (("with the optional viewer packages", False),
                         ("WITHOUT them (pip failed / offline)", True)):
        code, out = run(tmp / "app", block)
        backend = next((l.split(":", 1)[1] for l in out.splitlines()
                        if l.startswith("BACKEND:")), None)
        print("%-38s exit %-3s backend %s" % (label, code, backend or "-"))
        if code != 0 or backend is None:
            failures.append(label)
            print(out.strip()[-700:])
    print()
    if missing:
        print("VERDICT: the installer's file list is incomplete —", ", ".join(missing))
    elif failures:
        print("VERDICT: a fresh install does NOT run —", "; ".join(failures))
    else:
        print("VERDICT: a fresh install runs, with or without the optional packages")
    sys.exit(1 if (missing or failures) else 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

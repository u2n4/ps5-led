"""Does the portable EXE run on a machine that has nothing installed?

This is the question the whole single-file build exists to answer, and it
cannot be answered on the machine that built it: this one has Python,
PyOpenGL, pyopengltk and a controller driver already. Most people have none of
that -- which is the whole reason the lightbar used to go dead after an
install.

So the EXE is launched with Python stripped out of PATH and every Python
environment variable cleared, and with APPDATA pointed at an empty directory so
it writes a fresh config and a fresh log. Then the log says which preview
backend it actually got.

Deliberately NOT proof of a clean Windows install -- system DLLs and the GPU
driver are still this machine's. It proves the EXE carries its own Python and
its own OpenGL, which is what the packaging is for.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / "dist" / "PS5-LED.exe"
RUN_SECONDS = 25


def clean_env(appdata):
    """The environment of somebody who never installed Python."""
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUTF8",
                 "PYTHONDONTWRITEBYTECODE", "VIRTUAL_ENV", "CONDA_PREFIX"):
        env.pop(name, None)
    kept, dropped = [], []
    for part in env.get("PATH", "").split(os.pathsep):
        low = part.lower()
        # WindowsApps too: it carries a python.exe stub that ships with
        # Windows, and leaving it in makes the "no Python here" claim untrue
        # even though the stub only opens the Store.
        if ("python" in low or "conda" in low or low.endswith("\\scripts")
                or "windowsapps" in low):
            dropped.append(part)
        else:
            kept.append(part)
    env["PATH"] = os.pathsep.join(kept)
    env["APPDATA"] = str(appdata)
    env["LOCALAPPDATA"] = str(appdata)
    return env, dropped


def main():
    if not EXE.is_file():
        print("no EXE at", EXE)
        print("build it with:  python -m PyInstaller --noconfirm PS5-LED.spec")
        return 1

    size_mb = EXE.stat().st_size / 1024 / 1024
    print("EXE            : %s" % EXE.name)
    print("size           : %.1f MB" % size_mb)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="exececheck-"))
    try:
        appdata = tmp / "AppData"
        appdata.mkdir()
        env, dropped = clean_env(appdata)
        print("PATH entries removed (python/conda): %d" % len(dropped))
        for part in dropped:
            print("   -", part)
        # Prove the sabotage worked: no python should be reachable now.
        found = shutil.which("python", path=env["PATH"])
        print("python on the stripped PATH:", found or "none (good)")

        print("\nlaunching, %d seconds ..." % RUN_SECONDS)
        proc = subprocess.Popen([str(EXE)], env=env, cwd=str(tmp))
        deadline = time.time() + RUN_SECONDS
        log_path = None
        while time.time() < deadline:
            hits = list(appdata.rglob("app.log"))
            if hits and hits[0].stat().st_size:
                log_path = hits[0]
                text = log_path.read_text(encoding="utf-8", errors="replace")
                # Wait for the CONTROLLER line, not just the preview one. The
                # first version stopped at "preview:" and terminated the app a
                # second before it logged "controller connected", so a working
                # run read as a controller that was never found.
                if "controller connected" in text or "controller disconnected" in text and (
                        time.time() > deadline - RUN_SECONDS + 12):
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.5)

        alive = proc.poll() is None
        print("still running   :", alive)
        if not alive:
            print("exit code       :", proc.returncode)

        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path else ""
        if text:
            print("\n--- its log ---")
            print(text.strip()[-900:])

        backend = None
        m = re.search(r"preview: (OpenGL|built-in drawing)", text)
        if m:
            backend = "gl" if m.group(1) == "OpenGL" else "canvas"
        pad = re.search(r"controller connected: (.+)", text)
        print("controller       :", pad.group(1).strip() if pad
              else "not detected during this run")

        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

        print()
        if not alive:
            print("VERDICT: the EXE exited on its own - it does NOT run standalone")
            return 1
        if backend is None:
            print("VERDICT: it stayed up, but never logged which preview it chose")
            return 1
        if backend == "canvas":
            print("VERDICT: it runs, but WITHOUT the 3D - the bundled OpenGL did not load")
            return 1
        print("VERDICT: runs standalone with the 3D preview, no Python on PATH")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

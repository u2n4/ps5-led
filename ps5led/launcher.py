"""Open the app window.

Measured: Edge with --app and its own --user-data-dir gives a process we own -
it stays alive exactly as long as the window, which is how the app knows the
user closed it. A shared profile attaches to an already-running browser and
exits immediately, so the private profile directory is not optional.

Nothing here is load-bearing for the lightbar: the engine runs with or without
a window.
"""

import os
import pathlib
import subprocess
import webbrowser

from .config import config_dir

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def default_profile_dir():
    return config_dir() / "browser"


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return None


def browser_args(exe, url, profile_dir, fullscreen=False, size=(1280, 800)):
    args = [
        exe,
        "--app=%s" % url,
        "--user-data-dir=%s" % profile_dir,
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if fullscreen:
        args.append("--start-fullscreen")
    else:
        args.append("--window-size=%d,%d" % (int(size[0]), int(size[1])))
    return args


def launch(url, profile_dir=None, fullscreen=False, size=(1280, 800)):
    """The browser process, or None if we had to fall back to the default one."""
    exe = find_browser()
    if exe is None:
        webbrowser.open(url)
        return None
    target = pathlib.Path(profile_dir or default_profile_dir())
    target.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        browser_args(exe, url, str(target), fullscreen=fullscreen, size=size),
        shell=False)


def wait_for_close(process):
    """Block until the window closes. Returns its exit code, or 0 for no process."""
    if process is None:
        return 0
    try:
        return process.wait()
    except KeyboardInterrupt:
        return 0

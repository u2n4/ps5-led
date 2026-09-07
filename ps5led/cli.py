"""Command line entry points."""

import argparse
import json
import platform
import sys
import time

from . import __version__
from . import dualsense as ds
from .device import DeviceManager
from .engine import MODES, Engine
from .state import AppState


def _parse_colour(text):
    """Accept 00aaff, #00aaff or 0x00aaff; return an (r, g, b) tuple or None."""
    if text is None:
        return None
    cleaned = text.strip().lstrip("#")
    if cleaned[:2].lower() == "0x":
        cleaned = cleaned[2:]
    if len(cleaned) != 6:
        raise ValueError("colour must be six hex digits, e.g. 00aaff, not %r" % (text,))
    try:
        value = int(cleaned, 16)
    except ValueError:
        raise ValueError("colour must be six hex digits, e.g. 00aaff, not %r" % (text,))
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)

# How long --doctor gives a connection to either succeed or explain itself.
# _connect can spend over a second in HidD_GetFeature and another full second
# in a write timeout on a sleeping Bluetooth controller, and the read that
# switches Bluetooth into full reports happens in the same pass.
DOCTOR_TIMEOUT_SECONDS = 8.0
_DOCTOR_POLL_SECONDS = 0.05

_EXCLUSIVE_HINT = (
    "  - Another program (Steam, DS4Windows) may hold it exclusively.\n"
    "    Close it, or turn off its controller support, and run this again."
)


def _require_windows():
    if platform.system() != "Windows":
        sys.stderr.write("PS5 LED drives controllers on Windows only.\n")
        return False
    return True


def _wait_for_device(manager, timeout=DOCTOR_TIMEOUT_SECONDS):
    """Poll describe() until the device connects or an error says why it did not.

    A fixed sleep is a race, not a wait. Wait too little on Bluetooth and
    last_error is still None, so the user reads "connected: false,
    last_error: null" and learns nothing -- which is the exact silent failure
    --doctor exists to replace.
    """
    deadline = time.monotonic() + timeout
    while True:
        info = manager.describe()
        if info["connected"] or info["last_error"] or info["last_write_error"]:
            return info
        if time.monotonic() >= deadline:
            return info
        time.sleep(_DOCTOR_POLL_SECONDS)


def doctor():
    """Print what the app can see. This is what a silent failure looks like now.

    Exit code is part of the answer, not decoration: 0 only when the controller
    was actually opened and driven, so --doctor works as a scripted health
    check instead of reporting success over a dead device.
    """
    if not _require_windows():
        return 2
    from .hid_win import enumerate_devices

    print("PS5 LED %s" % __version__)
    devices = enumerate_devices(ds.VENDOR_ID)
    if not devices:
        print("\nNo Sony HID device found.")
        print("  - Is the controller connected by cable or paired over Bluetooth?")
        print(_EXCLUSIVE_HINT)
        return 1
    print("\nSony HID interfaces:")
    for info in devices:
        print("  %-32s pid=%#06x in=%-3d out=%-3d feat=%-3d transport=%s"
              % (info.product, info.product_id, info.input_length,
                 info.output_length, info.feature_length, info.transport))

    manager = DeviceManager(AppState())
    try:
        manager.start()
        view = _wait_for_device(manager)
    finally:
        manager.stop()

    print("\nengine view:")
    print(json.dumps(view, indent=2, default=str))
    if view["connected"]:
        return 0

    reason = view["last_error"] or view["last_write_error"]
    print("\nThe interface above was listed but could not be driven.")
    if reason:
        print("  reason: %s" % reason)
        if "cannot open" in reason.lower():
            print(_EXCLUSIVE_HINT)
    else:
        print("  - Nothing failed within %.0f s and nothing connected either:"
              % DOCTOR_TIMEOUT_SECONDS)
        print("    the interfaces above are Sony HID endpoints this app does")
        print("    not drive (unrecognised product id or report size).")
    return 1


def run_background(state=None, mode="manual", colour=None, speed=1.0):
    if not _require_windows():
        return 2
    state = state or AppState()
    manager = DeviceManager(state)
    engine = Engine(state, manager.write_colour)
    engine.set_mode(mode)
    engine.set_speed(speed)
    if colour is not None:
        engine.set_colour(colour)
    try:
        manager.start()
        engine.start()
        print("PS5 LED running in %s mode at speed %s. Ctrl+C to stop." % (mode, speed))
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Reached however the block above exits, including a failure between
        # the two start() calls -- otherwise the reader thread outlives the
        # process's only reference to it and keeps the handle.
        engine.stop()
        manager.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ps5led")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--doctor", action="store_true",
                        help="report what the app can see, and why it failed")
    parser.add_argument("--background", action="store_true",
                        help="run the engine with no window")
    parser.add_argument("--mode", default="manual", choices=list(MODES),
                        help="lighting mode (default: manual)")
    parser.add_argument("--color", "--colour", dest="colour", default=None,
                        metavar="RRGGBB",
                        help="hex colour for the modes that use one, e.g. 00aaff")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="animation speed, 0.1 to 5.0 (default: 1.0)")
    args = parser.parse_args(argv)

    if args.doctor:
        return doctor()
    if args.background:
        try:
            colour = _parse_colour(args.colour)
        except ValueError as exc:
            parser.error(str(exc))
        return run_background(mode=args.mode, colour=colour, speed=args.speed)
    parser.print_help()
    return 0

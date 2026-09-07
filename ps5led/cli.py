"""Command line entry points."""

import argparse
import json
import platform
import sys
import time

from . import __version__
from .device import DeviceManager
from .engine import Engine
from .state import AppState


def _require_windows():
    if platform.system() != "Windows":
        sys.stderr.write("PS5 LED drives controllers on Windows only.\n")
        return False
    return True


def doctor():
    """Print what the app can see. This is what a silent failure looks like now."""
    if not _require_windows():
        return 2
    from .hid_win import enumerate_devices

    print("PS5 LED %s" % __version__)
    devices = enumerate_devices(0x054C)
    if not devices:
        print("\nNo Sony HID device found.")
        print("  - Is the controller connected by cable or paired over Bluetooth?")
        print("  - Another program (Steam, DS4Windows) may hold it exclusively.")
        return 1
    print("\nSony HID interfaces:")
    for info in devices:
        print("  %-32s pid=%#06x in=%-3d out=%-3d feat=%-3d transport=%s"
              % (info.product, info.product_id, info.input_length,
                 info.output_length, info.feature_length, info.transport))

    state = AppState()
    manager = DeviceManager(state)
    manager.start()
    time.sleep(1.5)
    print("\nengine view:")
    print(json.dumps(manager.describe(), indent=2, default=str))
    manager.stop()
    return 0


def run_background(state=None):
    if not _require_windows():
        return 2
    state = state or AppState()
    manager = DeviceManager(state)
    manager.start()
    engine = Engine(state, manager.write_colour)
    engine.start()
    print("PS5 LED running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
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
    args = parser.parse_args(argv)

    if args.doctor:
        return doctor()
    if args.background:
        return run_background()
    parser.print_help()
    return 0

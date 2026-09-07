"""Operator tool: capture what the engine actually sees, including the two
failures real hardware found that no unit test could.

    python tools/diagnose.py enumerate     # every Sony HID interface, raw caps
    python tools/diagnose.py watch         # live connect/drop/reconnect trace

`enumerate` answers the Bluetooth question: `choose_device` accepts a device
only when its transport resolves, and transport is derived solely from
HidP_GetCaps().InputReportByteLength being 64 (USB) or 78 (Bluetooth). Anything
else becomes "unknown" and the device is dropped with no message at all. This
prints the real numbers for every interface, accepted or not, so a rejection
stops being invisible.

`watch` answers the reconnect question. It runs the same DeviceManager the app
runs and prints every state transition with a timestamp, so unplugging and
replugging shows whether the reader notices the loss at all.

Not part of the test suite: it needs a controller in your hand.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ps5led import dualsense as ds
from ps5led import dualshock4 as ds4
from ps5led.device import DeviceManager, choose_device
from ps5led.state import AppState

KNOWN = {
    0x0CE6: "DualSense", 0x0DF2: "DualSense Edge",
    0x05C4: "DualShock 4 v1", 0x09CC: "DualShock 4 v2", 0x0BA0: "DS4 USB dongle",
}


def stamp():
    return time.strftime("%H:%M:%S")


def cmd_enumerate():
    from ps5led.hid_win import enumerate_devices

    infos = enumerate_devices(ds.VENDOR_ID)
    if not infos:
        print("No Sony HID interface found at all.")
        print("  - Bluetooth: is the controller actually paired AND connected?")
        print("  - Another program (Steam, DS4Windows) cannot hide a device from this")
        print("    listing, because enumeration opens with zero access rights.")
        return 1

    print("Sony HID interfaces present: %d\n" % len(infos))
    accepted = choose_device(infos)
    for info in infos:
        name = KNOWN.get(info.product_id, "unknown product")
        mark = "  <== the engine would use this" if accepted and info.path == accepted.path else ""
        print("  %s (pid=%#06x)" % (name, info.product_id))
        print("    product string : %s" % (info.product or "(none)"))
        print("    input  report  : %d bytes" % info.input_length)
        print("    output report  : %d bytes" % info.output_length)
        print("    feature report : %d bytes" % info.feature_length)
        print("    transport      : %s%s" % (info.transport, mark))
        if info.transport == "unknown":
            print("    ^^ REJECTED. The transport table only knows 64 (USB) and 78")
            print("       (Bluetooth). This device reports %d, so choose_device skips" % info.input_length)
            print("       it and the lightbar is never touched.")
        driveable = info.product_id in ds.PRODUCT_IDS + ds4.PRODUCT_IDS
        if not driveable:
            print("    ^^ not a controller this app drives")
        print()

    if accepted is None:
        print("RESULT: no device accepted. The lightbar will not respond.")
        return 1
    print("RESULT: would drive %s over %s." % (accepted.product, accepted.transport))
    return 0


def cmd_watch(seconds):
    state = AppState()
    manager = DeviceManager(state)
    manager.start()
    print("Watching for %d s. Unplug the controller, wait, plug it back in.\n" % seconds)
    print("%-8s  %-9s  %-9s  %s" % ("time", "connected", "transport", "last_error / note"))
    print("-" * 78)

    last = None
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            d = manager.describe()
            key = (d["connected"], d["transport"], d["last_error"], d.get("last_write_error"))
            if key != last:
                note = d["last_error"] or d.get("last_write_error") or ""
                print("%-8s  %-9s  %-9s  %s"
                      % (stamp(), str(d["connected"]).lower(), d["transport"] or "-", note[:44]))
                last = key
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n(stopped early)")
    finally:
        manager.stop()

    print("\nWhat the trace means:")
    print("  connected true -> false on unplug  = the reader noticed the loss.")
    print("  it never flips to false            = the reader is stuck on a dead")
    print("                                       handle and will never reconnect.")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="diagnose")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("enumerate", help="print raw HID capabilities for every Sony interface")
    w = sub.add_parser("watch", help="trace connect/drop/reconnect while you unplug and replug")
    w.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Windows only.")
        return 2
    if args.cmd == "enumerate":
        return cmd_enumerate()
    if args.cmd == "watch":
        return cmd_watch(args.seconds)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

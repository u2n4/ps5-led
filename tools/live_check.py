"""Operator tool: prove the lightbar responds on real hardware.

    python tools/live_check.py            # cycle red, green, blue, then restore
    python tools/live_check.py --watch    # stream motion and battery for 10 s

Not part of the test suite: it needs a controller in your hand. Run it after
every change to the HID transport or the DualSense/DualShock 4 protocol
modules -- a green unit suite proves the bytes are shaped right, not that a
real controller reacts to them.
"""

import argparse
import sys
import time

sys.path.insert(0, ".")

from ps5led import dualsense as ds
from ps5led import dualshock4 as ds4
from ps5led.crc import OUTPUT_SEED, ps_crc32
from ps5led.hid_win import HidDevice, HidError, enumerate_devices


def pick():
    # type: () -> object
    """Enumerate Sony HID interfaces and return the first controller we drive."""
    devices = enumerate_devices(ds.VENDOR_ID)
    if not devices:
        raise SystemExit("No Sony controller found. Connect one and try again.")
    print("Sony HID interfaces present:")
    for info in devices:
        print("  %s  pid=%#06x  in=%d out=%d feat=%d  transport=%s"
              % (info.product, info.product_id, info.input_length,
                 info.output_length, info.feature_length, info.transport))
    for info in devices:
        if info.product_id in ds.PRODUCT_IDS + ds4.PRODUCT_IDS:
            return info
    raise SystemExit(
        "Sony device present but not a controller we drive "
        "(DualSense pid in %s, DualShock 4 pid in %s)."
        % ([hex(p) for p in ds.PRODUCT_IDS], [hex(p) for p in ds4.PRODUCT_IDS]))


def _report_write_failure(name, packet, transport, exc):
    """Print everything needed to diagnose a failed write without guessing.

    Per the plan: if Bluetooth ever misbehaves, the three likely causes are the
    CRC being computed over the wrong span, the setup packet being skipped, or
    the report never reaching 78 bytes -- all three are visible below.
    """
    print("\nFAILED writing %s: %s" % (name, exc))
    print("  transport = %s" % transport)
    print("  length    = %d bytes" % len(packet))
    print("  packet    = %s" % packet.hex())
    if transport == "bt" and len(packet) > 4:
        expected = ps_crc32(OUTPUT_SEED, bytes(packet[:-4]))
        carried = int.from_bytes(packet[-4:], "little")
        print("  crc check = expected %08x, carried %08x (%s)"
              % (expected, carried, "OK" if expected == carried else "MISMATCH"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true",
                        help="after the colour cycle, stream motion and battery "
                             "for 10 s (DualSense only)")
    args = parser.parse_args()

    info = pick()
    is_ds5 = info.product_id in ds.PRODUCT_IDS
    print("\nusing %s over %s\n" % (info.product, info.transport))

    try:
        dev = HidDevice.open(info.path)
    except HidError as exc:
        raise SystemExit(
            "Could not open %s for read/write: %s\n"
            "This usually means another program is holding the controller "
            "exclusively -- close Steam (or its controller support) or "
            "DS4Windows and try again." % (info.path, exc))

    with dev:
        scales = None
        if is_ds5:
            # Three outcomes, not two. "unavailable (None)" -- what this printed
            # when the read succeeded and parse_calibration rejected the data --
            # named neither the failure nor the reason, and this is the one read
            # whose failure explains a Bluetooth pad stuck in its reduced report.
            raw = dev.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
            if raw is None:
                scales = None
                print("calibration: feature report %#04x refused (%s)"
                      % (ds.FEATURE_CALIBRATION, dev.last_error))
            else:
                scales = ds.parse_calibration(raw)
                if scales is None:
                    print("calibration: feature report %#04x returned implausible "
                          "data (%d bytes): %s"
                          % (ds.FEATURE_CALIBRATION, len(raw), raw.hex()))
                else:
                    print("calibration: scales %s" % (scales,))

            setup = ds.build_output(info.transport, info.output_length,
                                    lightbar_setup=True, seq=0)
            try:
                dev.write(setup)
            except HidError as exc:
                _report_write_failure("lightbar-setup", setup, info.transport, exc)
                raise SystemExit(1)
            time.sleep(0.05)

        seq = 1
        for name, rgb in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                          ("blue", (0, 0, 255)), ("restored", (0, 170, 255))):
            if is_ds5:
                packet = ds.build_output(info.transport, info.output_length,
                                         rgb=rgb, seq=seq)
            else:
                packet = ds4.build_output(info.transport, rgb)
            try:
                dev.write(packet)
            except HidError as exc:
                _report_write_failure(name, packet, info.transport, exc)
                raise SystemExit(1)
            seq += 1
            print("wrote %-9s %s  (%d bytes: %s)" % (name, rgb, len(packet), packet.hex()))
            time.sleep(0.8)

        if args.watch and not is_ds5:
            print("\n--watch streams DualSense motion/battery only; "
                  "this is a DualShock 4, skipping.\n")
        elif args.watch:
            print("\nwatching for 10 s -- move the controller\n")
            scale = scales[0] if scales else ds.DEFAULT_GYRO_SCALE
            deadline = time.time() + 10
            saw_full_report = False
            while time.time() < deadline:
                try:
                    data = dev.read(timeout_ms=200)
                except HidError as exc:
                    print("\nread failed: %s" % exc)
                    break
                if not data:
                    continue
                # Test the report id, not the length. The Windows HID class
                # driver pads every short input report up to
                # InputReportByteLength, so the reduced Bluetooth report does
                # not arrive as 10 bytes -- it arrives as 78, and only its id
                # (0x01 rather than the full report's 0x31) still gives it away.
                # A length test here could never fire, which would have left the
                # Bluetooth bring-up nobody has done yet with no message at all.
                if (info.transport == ds.TRANSPORT_BT
                        and data[0] != ds.INPUT_REPORT_BT):
                    print("\rgot report id %#04x, not the full %#04x -- the "
                          "calibration read did not switch this controller into "
                          "full reports          " % (data[0], ds.INPUT_REPORT_BT),
                          end="")
                    continue
                state = ds.parse_input(data)
                if state is None:
                    continue
                saw_full_report = True
                print("\rbatt %3d%% state %d  gyro %8.1f %8.1f %8.1f deg/s   "
                      % (state.battery_percent, state.charge_state,
                         state.gyro_raw[0] * scale, state.gyro_raw[1] * scale,
                         state.gyro_raw[2] * scale), end="")
            print()
            if not saw_full_report:
                print("no input report was parsed in 10 s -- check the cable "
                      "or the Bluetooth pairing")


if __name__ == "__main__":
    main()

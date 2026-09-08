"""No hardware: verify native HID packet bytes and publication boundaries."""
import ast
from pathlib import Path
import struct
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from ps5led import dualsense as ds
from ps5led.crc import INPUT_SEED, append_crc32, check_crc32, OUTPUT_SEED
from ps5led.device import DeviceManager, BOOT_COLOUR_WRITES


def app_classes():
    # Extract only the adapter/engine to avoid app config/log/atexit side effects.
    source = Path(__file__).parents[1].joinpath("dualled_pro.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in ("Backend", "Engine", "clamp", "hex_to_rgb", "rgb_to_hex")]
    namespace = dict(threading=threading, time=time, CFG={"color": "#123456"},
                     MODE_CODE={"Manual": "manual"}, log=lambda *args: None)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "dualled_pro.py", "exec"), namespace)
    return namespace


class Sink:
    def __init__(self): self.values = {}
    def update(self, **values): self.values.update(values)


class FakeDevice:
    last_error = "fixture has no calibration"
    def __init__(self): self.writes = []; self.closed = False; self.failure = False
    def write(self, packet):
        if self.failure: raise OSError("fixture write failure")
        self.writes.append(packet)
    def get_feature(self, *args): return None
    def close(self): self.closed = True


def info(transport="usb", ds4=False):
    return types.SimpleNamespace(product_id=0x09cc if ds4 else 0x0ce6,
                                 product="Fixture controller", transport=transport,
                                 path="fixture", input_length=64,
                                 output_length=547 if transport == "bt" else 48)


def connect(manager, device, transport="usb", ds4=False):
    fake = types.ModuleType("ps5led.hid_win")
    fake.HidDevice = types.SimpleNamespace(open=lambda path: device)
    fake.enumerate_devices = lambda vid: [info(transport, ds4)]
    with patch.dict(sys.modules, {"ps5led.hid_win": fake}), patch.object(manager._stop, "wait", return_value=False):
        return manager._connect()


class NativeBackendTests(unittest.TestCase):
    def test_boot_publishes_last_successful_rgb_only_after_repeats(self):
        sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
        manager.write_colour((18, 52, 86))
        original = device.write
        def write(packet):
            self.assertFalse(sink.values.get("connected", False))
            self.assertNotIn("applied_rgb", sink.values)
            original(packet)
        device.write = write
        self.assertTrue(connect(manager, device))
        self.assertEqual(len(device.writes), 1 + BOOT_COLOUR_WRITES)
        self.assertEqual(sink.values["applied_rgb"], (18, 52, 86))
        for packet in device.writes[1:]: self.assertEqual(packet[45:48], bytes((18, 52, 86)))

    def test_bt_windows_547_output_builds_78_with_crc_and_exact_rgb(self):
        sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
        self.assertTrue(connect(manager, device, "bt"))
        self.assertTrue(manager.write_colour((255, 19, 6)))
        packet = device.writes[-1]
        self.assertEqual(len(packet), 78)
        self.assertEqual(packet[47:50], bytes((255, 19, 6)))
        self.assertTrue(check_crc32(OUTPUT_SEED, packet))
        self.assertEqual(sink.values["applied_rgb"], (255, 19, 6))

    def test_ds4_bt_uses_reused_protocol(self):
        sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
        self.assertTrue(connect(manager, device, "bt", ds4=True))
        self.assertTrue(manager.write_colour((9, 8, 7)))
        self.assertEqual(device.writes[-1][8:11], bytes((9, 8, 7)))
        self.assertEqual(device.writes[-1][0], 0x11)
        self.assertTrue(check_crc32(OUTPUT_SEED, device.writes[-1]))

    def test_failed_write_drops_and_never_publishes_requested_rgb(self):
        sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
        connect(manager, device); device.failure = True
        self.assertFalse(manager.write_colour((200, 99, 2)))
        self.assertIsNone(sink.values["applied_rgb"])
        self.assertFalse(sink.values["connected"])
        self.assertTrue(device.closed)
        self.assertEqual(manager._last_rgb, (200, 99, 2))
        replacement = FakeDevice()
        self.assertTrue(connect(manager, replacement))
        self.assertEqual(sink.values["applied_rgb"], (200, 99, 2))
        self.assertEqual(replacement.writes[-1][45:48], bytes((200, 99, 2)))

    def test_adapter_preserves_bgr_success_and_engine_output_on_failure(self):
        app = app_classes(); backend = app["Backend"](); device = FakeDevice()
        connect(backend._manager, device)
        app["CFG"]["bgr_swap"] = True
        engine = app["Engine"](backend)
        self.assertTrue(engine._send((1, 2, 3)))
        self.assertEqual(engine.out, (3, 2, 1))
        self.assertEqual(device.writes[-1][45:48], bytes((3, 2, 1)))
        previous_time = engine._last_apply
        device.failure = True
        self.assertFalse(engine._send((40, 50, 60)))
        self.assertEqual(engine.out, (3, 2, 1))
        self.assertEqual(engine._last_apply, previous_time)
        self.assertIsNone(backend.snapshot()["applied_rgb"])

    def test_manual_compares_wire_rgb_and_keeps_two_second_heartbeat(self):
        for swapped in (False, True):
            app = app_classes(); app["CFG"]["bgr_swap"] = swapped
            backend = app["Backend"](); device = FakeDevice()
            connect(backend._manager, device)
            engine = app["Engine"](backend)
            now = [100.0]
            app["time"] = types.SimpleNamespace(time=lambda: now[0],
                sleep=lambda _: engine.stop_evt.set())
            self.assertTrue(engine._send(engine.color))
            count = len(device.writes)
            now[0] += 0.25
            engine.run()
            self.assertEqual(len(device.writes), count, "unchanged wire RGB must not resend")
            now[0] += 2.0
            engine.stop_evt.clear(); engine.run()
            self.assertEqual(len(device.writes), count + 1, "heartbeat must still refresh RGB")
            app["CFG"]["bgr_swap"] = not swapped
            now[0] += 0.25
            engine.stop_evt.clear(); engine.run()
            self.assertEqual(len(device.writes), count + 2, "changing BGR must send immediately")
            self.assertEqual(tuple(device.writes[-1][45:48]), backend.wire_rgb(engine.color))

    def test_connect_starts_monitor_and_snapshot_is_a_copy(self):
        backend = app_classes()["Backend"]()
        with patch.object(backend._manager, "start") as start:
            self.assertTrue(backend.connect()); start.assert_called_once()
        snap = backend.snapshot(); snap["connected"] = True
        self.assertFalse(backend.snapshot()["connected"])

    def test_right_stick_and_measured_sensor_frame_usb_and_bt(self):
        for transport in ("usb", "bt"):
            sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
            connect(manager, device, transport)
            size, body, report = (64, 1, 1) if transport == "usb" else (78, 2, 0x31)
            data = bytearray(size); data[0] = report
            data[body:body+4] = bytes((128, 128, 255, 0))
            struct.pack_into("<hhh", data, body+15, 0, -8, -2)
            struct.pack_into("<hhh", data, body+21, 8, 7881, 1245)
            struct.pack_into("<I", data, body+27, 3000000)
            data[body+52] = 0x17
            if transport == "bt": append_crc32(INPUT_SEED, data)
            def read(timeout_ms):
                manager._stop.set()
                return bytes(data)
            device.read = read
            manager._run()
            self.assertEqual(sink.values["right_stick"], (1.0, -1.0))
            self.assertEqual(sink.values["sensor_timestamp"], 3000000)
            self.assertAlmostEqual(sink.values["accel"][1], 0.962, places=3)
            self.assertEqual(sink.values["gyro"], (0.0, -0.5, -0.125))
            self.assertEqual(sink.values["battery"], 75)
            self.assertTrue(sink.values["charging"])

    def test_fifteen_silent_reads_force_disconnect(self):
        sink = Sink(); manager = DeviceManager(sink); device = FakeDevice()
        connect(manager, device)
        reads = []
        def read(timeout_ms): reads.append(timeout_ms); return None
        device.read = read
        with patch.object(manager._stop, "wait", side_effect=lambda _: manager._stop.set()):
            manager._run()
        self.assertEqual(reads, [200] * 15)
        self.assertFalse(sink.values["connected"])
        self.assertIsNone(sink.values["sensor_timestamp"])
        self.assertEqual(sink.values["right_stick"], (0.0, 0.0))


if __name__ == "__main__": unittest.main()

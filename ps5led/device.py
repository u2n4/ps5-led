"""Owns the controller handle, the reader thread, and reconnection.

hid_win is imported inside functions on purpose: it is Windows-only and the CI
runner is Linux.
"""

import threading
import time

from . import dualsense as ds
from . import dualshock4 as ds4

RESCAN_SECONDS = 2.0
READ_TIMEOUT_MS = 200


def choose_device(infos):
    """Prefer a DualSense, then a DualShock 4; ignore anything else."""
    for wanted in (ds.PRODUCT_IDS, ds4.PRODUCT_IDS):
        for info in infos:
            if info.product_id in wanted and info.transport in ("usb", "bt"):
                return info
    return None


class DeviceManager(object):
    def __init__(self, state):
        self._state = state
        self._lock = threading.Lock()
        self._device = None
        self._info = None
        self._is_ds5 = False
        self._scales = None
        self._seq = 0
        self._last_error = None
        self._last_rgb = None
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ps5led-reader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._close()

    def describe(self):
        with self._lock:
            info = self._info
            return {
                "connected": self._device is not None,
                "product": info.product if info else None,
                "product_id": info.product_id if info else None,
                "transport": info.transport if info else None,
                "input_length": info.input_length if info else None,
                "output_length": info.output_length if info else None,
                "gyro_scales": self._scales,
                "last_error": self._last_error,
            }

    # -- writing -----------------------------------------------------------
    def write_colour(self, rgb):
        with self._lock:
            device, info, is_ds5 = self._device, self._info, self._is_ds5
            # Record the caller's intent unconditionally -- success or not --
            # so a reconnect always resends the colour the engine most
            # recently asked for. If this were only set on success, a colour
            # that failed to reach a still-open device (write() raised, or no
            # device was connected yet) would leave last_rgb pointing at an
            # older colour; Engine already believes the newer one was
            # delivered (it only retries when write_colour raises, and it
            # never inspects our return value), so nothing would ever ask for
            # it again. The next successful connect must resend the true
            # current intent, not a stale one.
            self._last_rgb = tuple(rgb)
            if device is None:
                self._last_error = "no device connected"
                return False
            self._seq = (self._seq + 1) & 0x0F
            seq = self._seq
        try:
            if is_ds5:
                packet = ds.build_output(info.transport, info.output_length, rgb=rgb, seq=seq)
            else:
                packet = ds4.build_output(info.transport, rgb)
            device.write(packet)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._drop()
            return False
        with self._lock:
            self._last_error = None
        return True

    # -- internals ---------------------------------------------------------
    def _close(self):
        with self._lock:
            device, self._device, self._info = self._device, None, None
            self._scales = None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        self._state.update(connected=False, transport=None, product=None)

    def _drop(self):
        self._close()

    def _connect(self):
        from .hid_win import HidDevice, enumerate_devices

        info = choose_device(enumerate_devices(ds.VENDOR_ID))
        if info is None:
            return False
        device = HidDevice.open(info.path)
        is_ds5 = info.product_id in ds.PRODUCT_IDS
        scales = None
        if is_ds5:
            # This read yields the gyro scale AND switches a Bluetooth DualSense
            # out of its reduced 10-byte report into the full 0x31 report.
            raw = device.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
            scales = ds.parse_calibration(raw) if raw else None
            # One setup packet per connection, or RGB is ignored while the
            # controller finishes its power-on animation.
            device.write(ds.build_output(info.transport, info.output_length,
                                         lightbar_setup=True, seq=0))
        with self._lock:
            self._device, self._info, self._is_ds5, self._scales = device, info, is_ds5, scales
            self._last_error = None
            last_rgb = self._last_rgb
        self._state.update(connected=True, transport=info.transport,
                           product=info.product,
                           gyro_scale=(scales[0] if scales else ds.DEFAULT_GYRO_SCALE))
        if last_rgb is not None:
            self.write_colour(last_rgb)
        return True

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                device = self._device
            if device is None:
                try:
                    if not self._connect():
                        self._stop.wait(RESCAN_SECONDS)
                        continue
                except Exception as exc:
                    with self._lock:
                        self._last_error = str(exc)
                    self._stop.wait(RESCAN_SECONDS)
                    continue
                with self._lock:
                    device = self._device
                if device is None:
                    continue
            try:
                data = device.read(timeout_ms=READ_TIMEOUT_MS)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                self._drop()
                self._stop.wait(RESCAN_SECONDS)
                continue
            if not data:
                continue
            with self._lock:
                is_ds5, scales = self._is_ds5, self._scales
            if not is_ds5:
                continue
            sample = ds.parse_input(data)
            if sample is None:
                continue
            scale = scales[0] if scales else ds.DEFAULT_GYRO_SCALE
            self._state.update(
                battery=sample.battery_percent,
                charging=sample.charge_state in (1, 2),
                gyro=tuple(value * scale for value in sample.gyro_raw),
                accel=tuple(value / 8192.0 for value in sample.accel_raw),
                sensor_timestamp=sample.timestamp,
                buttons=sample.buttons,
                touch=sample.touch,
            )

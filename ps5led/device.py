"""Owns the controller handle, the reader thread, and reconnection.

hid_win is imported inside functions on purpose: it is Windows-only and the CI
runner is Linux.
"""

import threading

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
        # Separate from _last_error on purpose. _last_error is "whatever went
        # wrong most recently, from whichever thread spoke last" and is cleared
        # on a successful connect, so a real write failure is routinely buried
        # under the reader's downstream "device is closed" and then wiped two
        # seconds later by the reconnect. _last_write_error is written only
        # where a write is actually attempted (see _write_packet), so --doctor
        # can still name the reason the lightbar stopped responding.
        self._last_write_error = None
        self._last_rgb = None
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        """Start the reader thread; starting a running manager is a no-op.

        Unguarded, a second call would clear _stop, overwrite self._thread and
        orphan the first reader: stop() would only ever join the newest one and
        the old thread would keep reading and reconnecting forever.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ps5led-reader", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the reader and release the handle. A real barrier, not a hint.

        The join can time out while _connect is still inside a blocking step
        (CreateFileW, HidD_GetFeature, or a write that can burn a full second
        of timeout on a sleeping Bluetooth controller), so the _close() below
        can run before that connect has published anything. One _close() is
        still enough, because _connect re-checks _stop *inside* self._lock
        immediately before publishing, and self._lock orders the two:

          - if _connect's critical section runs first, the _close() below
            follows it, sees the published handle, and closes it;
          - if the _close() below runs first, _connect's check follows it and
            therefore also follows the _stop.set() above, so it sees the flag
            and closes the handle itself instead of publishing it.

        Either way the handle is closed exactly once and no live device is left
        unreachable behind a stopped manager.
        """
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
                "last_write_error": self._last_write_error,
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
                # Deliberately not recorded as a write error: at startup the
                # engine's first tick always lands here, and in a mode that
                # writes once (manual) nothing would ever overwrite it, so
                # --doctor would report a permanent write failure on a
                # controller whose lightbar is lit and correct.
                self._last_error = "no device connected"
                return False
            self._seq = (self._seq + 1) & 0x0F
            seq = self._seq
        try:
            self._write_packet(device, self._build_packet(info, is_ds5, rgb, seq))
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._drop()
            return False
        with self._lock:
            self._last_error = None
        return True

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _build_packet(info, is_ds5, rgb, seq):
        if is_ds5:
            return ds.build_output(info.transport, info.output_length, rgb=rgb, seq=seq)
        return ds4.build_output(info.transport, rgb)

    def _write_packet(self, device, packet):
        """The single choke point for every device.write() in this class.

        Routing all writes through here is what gives _last_write_error its
        provenance: it is set only by a write that failed and cleared only by a
        write that succeeded, so the reader's HidError and _connect's
        enumerate/open failures can never land in it, and a reconnect never
        blanks it without first proving the device accepts a write.
        """
        try:
            device.write(packet)
        except Exception as exc:
            with self._lock:
                self._last_write_error = str(exc)
            raise
        with self._lock:
            self._last_write_error = None

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
        # From here on the open handle is only reachable through this local,
        # and _close() cannot help because it reads self._device -- which is
        # still None. Anything that raises or bails below must close it here or
        # the Win32 file handle plus the instance's two event handles leak, and
        # the caller retries the leak every RESCAN_SECONDS. A paired-but-asleep
        # Bluetooth controller does exactly that: the setup write times out
        # after a second, every second scan, for as long as the app runs.
        published = False
        try:
            if self._stop.is_set():
                # Cheap early out so a stop that arrives during the open does
                # not still pay for a calibration read and a setup write that
                # can burn a second of timeout. Not the barrier -- that is the
                # lock-guarded check below -- just an economy.
                return False
            is_ds5 = info.product_id in ds.PRODUCT_IDS
            scales = None
            if is_ds5:
                # This read yields the gyro scale AND switches a Bluetooth
                # DualSense out of its reduced 10-byte report into the full
                # 0x31 report.
                raw = device.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
                scales = ds.parse_calibration(raw) if raw else None
                # One setup packet per connection, or RGB is ignored while the
                # controller finishes its power-on animation.
                self._write_packet(device, ds.build_output(
                    info.transport, info.output_length, lightbar_setup=True, seq=0))
            # Resend the engine's current colour BEFORE publishing self._device.
            # Two reasons, both fixed by the ordering alone:
            #   - HidDevice allows at most one thread inside write() at a time
            #     (its OVERLAPPED is per call, its events are per instance).
            #     Publishing first would let the engine thread enter write()
            #     while this resend is still in flight; the loser's
            #     GetOverlappedResult returns ERROR_IO_INCOMPLETE, cancels its
            #     own healthy write, raises, and tears down the connection that
            #     was just built.
            #   - A newer colour arriving in that same window would be
            #     overwritten by this older one.
            # While self._device is still None, write_colour returns early, so
            # this is provably the only writer.
            seq = 0
            with self._lock:
                last_rgb = self._last_rgb
                if last_rgb is not None:
                    self._seq = (self._seq + 1) & 0x0F
                    seq = self._seq
            if last_rgb is not None:
                self._write_packet(device, self._build_packet(info, is_ds5, last_rgb, seq))
            with self._lock:
                # Re-checked under the lock, not before it: see stop()'s
                # docstring for why this ordering is what makes stop() a
                # barrier rather than a hint.
                if self._stop.is_set():
                    return False
                self._device, self._info = device, info
                self._is_ds5, self._scales = is_ds5, scales
                self._last_error = None
                # Published in the same critical section as the handle, not
                # after it: _close() drops the handle under this lock and only
                # then announces connected=False, so an update left outside
                # here could land afterwards and tell AppState a stopped
                # manager still has a controller. AppState.update is an
                # in-memory merge, never device I/O, so the lock stays short.
                self._state.update(connected=True, transport=info.transport,
                                   product=info.product,
                                   gyro_scale=(scales[0] if scales
                                               else ds.DEFAULT_GYRO_SCALE))
                published = True
        finally:
            if not published:
                try:
                    device.close()
                except Exception:
                    pass
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
                    # Connected, then dropped again before we could read it.
                    # Every other retry path here backs off; without this one
                    # the loop would spin straight back into _connect() with no
                    # pause at all.
                    self._stop.wait(RESCAN_SECONDS)
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

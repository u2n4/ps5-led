"""Owns the controller handle, the reader thread, and reconnection.

hid_win is imported inside functions on purpose: it is Windows-only and the CI
runner is Linux.
"""

import threading

from . import dualsense as ds
from . import dualshock4 as ds4

RESCAN_SECONDS = 2.0
READ_TIMEOUT_MS = 200

# A connected controller is never quiet: it streams gyro, accel and touch
# continuously whether or not anyone touches it. The live USB run measured 2,533
# input reports in 10 s, about 253/s.
#
# So silence is a liveness signal, and it is the ONLY one on the path that
# actually failed on real hardware: unplugging the controller left ReadFile
# accepting a request that never completed, so every read returned None as a
# plain timeout, `if not data: continue` spun the loop forever on a dead handle,
# and _drop() was never reached — the lightbar stopped and only restarting the
# process brought it back. Windows never reported an error to notice.
#
# 15 consecutive 200 ms timeouts is 3 s of silence from a device that should
# have sent about 750 reports.
SILENT_READS_BEFORE_DROP = 15

# The colour a freshly opened controller is given when no caller has asked for
# one yet. It lives here, not in engine.py, because the device layer is the one
# that needs a colour with no caller present: _connect runs before any Engine
# exists, and --doctor never constructs an Engine at all. Engine imports this
# same constant as its own default on purpose -- if the two diverged, every
# connection would light the bar in one colour and the engine's first tick would
# immediately change it to another, a visible flash on every reconnect.
DEFAULT_RGB = (0, 170, 255)


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
        (CreateFileW, the calibration feature read, or a write that can burn a
        full second of timeout on a sleeping Bluetooth pad), so the _close() below
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
        """Put ``rgb`` on the lightbar. True if it reached the device.

        Never raises: every failure is reported by returning False. Callers must
        treat a falsy return as "not delivered" and ask again -- Engine does.
        Failure here is routine rather than exceptional (the engine's very first
        tick lands on a manager that has not connected yet, on every single
        run), which is why it is a return value and not an exception.
        """
        with self._lock:
            device, info, is_ds5 = self._device, self._info, self._is_ds5
            # Record the caller's intent unconditionally -- success or not --
            # so a reconnect always resends the colour most recently asked for.
            # If this were set only on success, a colour that failed to reach a
            # still-open device would leave _last_rgb pointing at an older one,
            # and the reconnect would faithfully restore the wrong colour. The
            # engine's retry does not make this redundant: the resend is what
            # covers the gap between the connection coming back and the engine's
            # next tick, and it is the only recovery path at all for a caller
            # that is not the engine.
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
            # Only this device, never "whatever is connected now": the lock was
            # released for the write above, and the reader can drop this handle
            # and finish a reconnect inside that window. An unconditional close
            # here would take down the healthy new connection on behalf of a
            # failure belonging to a handle that is already gone.
            self._drop(device)
            return False
        with self._lock:
            self._last_error = None
        return True

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _ds5_output_length(info):
        """The DualSense output-report length to BUILD at, never Windows' buffer size.

        Measured on real hardware, all three interfaces present at once:
            DualSense  USB : in=64  out=48
            DualSense  BT  : in=78  out=547
            DualShock4 BT  : in=547 out=547

        OutputReportByteLength is the largest output report the collection
        declares, not the size of report 0x31. Feeding 547 to build_output
        raised "Bluetooth reports are 78 bytes, got 547" inside _connect, so the
        connection never completed and the lightbar was never touched — the
        whole reason Bluetooth did nothing on real hardware.

        HidDevice.write() pads to OutputReportByteLength itself, which is what
        Windows requires of the buffer; the report the driver puts on the wire is
        sized by the descriptor entry for the report id in byte 0.
        """
        if info.transport == ds.TRANSPORT_BT:
            return ds.BT_OUTPUT_SIZE
        return info.output_length

    @staticmethod
    def _build_packet(info, is_ds5, rgb, seq):
        if is_ds5:
            return ds.build_output(info.transport,
                                   DeviceManager._ds5_output_length(info),
                                   rgb=rgb, seq=seq)
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

    def _close(self, only=None):
        """Release the connection. With ``only``, release it just if it is that one.

        The identity test lives inside the critical section rather than in the
        caller, because a caller that checked first and closed after would leave
        a window for the reader to reconnect between the two.
        """
        with self._lock:
            if only is not None and self._device is not only:
                return
            device, self._device, self._info = self._device, None, None
            self._scales = None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        self._state.update(connected=False, transport=None, product=None)

    def _drop(self, device):
        self._close(only=device)

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
            # None unless the calibration read is the thing that went wrong.
            # Carried all the way to the publish below instead of being
            # discarded: this read is what switches a Bluetooth DualSense out of
            # its reduced report, so its failure is the most diagnostic event on
            # the transport nobody has tested yet, and --doctor has to be able
            # to name it. The two failures are told apart because they mean
            # opposite things -- "refused" is the driver or another process
            # saying no, "implausible" is a report that arrived and did not
            # decode, which points at the layout, not the transport.
            calibration_error = None
            if is_ds5:
                # This read yields the gyro scale AND switches a Bluetooth
                # DualSense out of its reduced 10-byte report into the full
                # 0x31 report.
                raw = device.get_feature(ds.FEATURE_CALIBRATION, ds.CALIBRATION_SIZE)
                if raw is None:
                    calibration_error = (
                        "calibration feature report %#04x refused: %s"
                        % (ds.FEATURE_CALIBRATION, device.last_error))
                else:
                    scales = ds.parse_calibration(raw)
                    if scales is None:
                        calibration_error = (
                            "calibration feature report %#04x returned implausible "
                            "data (%d bytes): %s"
                            % (ds.FEATURE_CALIBRATION, len(raw), raw.hex()))
                # One setup packet per connection, or RGB is ignored while the
                # controller finishes its power-on animation.
                self._write_packet(device, ds.build_output(
                    info.transport, self._ds5_output_length(info),
                    lightbar_setup=True, seq=0))
            # Always follow the setup packet with a colour, and always before
            # publishing self._device.
            #
            # Unconditionally, because the setup packet above is
            # LIGHTBAR_SETUP_LIGHT_OUT: it takes the bar OUT of the boot
            # animation by turning it off, and nothing turns it back on. A
            # caller that never writes a colour -- --doctor is exactly that --
            # would otherwise connect, report success, and leave the lightbar
            # dark, which is the failure this whole branch exists to end. The
            # Linux driver does the same thing for the same reason:
            # dualsense_probe() calls dualsense_reset_leds() and then
            # dualsense_set_lightbar() on the very next line.
            #
            # Before publishing, for two more reasons fixed by the ordering
            # alone:
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
            with self._lock:
                # DEFAULT_RGB only until a caller has expressed an intent; from
                # then on the reconnect resend is that intent's sole recovery
                # path, so it has to win over the default.
                last_rgb = self._last_rgb if self._last_rgb is not None else DEFAULT_RGB
                self._seq = (self._seq + 1) & 0x0F
                seq = self._seq
            self._write_packet(device, self._build_packet(info, is_ds5, last_rgb, seq))
            with self._lock:
                # Re-checked under the lock, not before it: see stop()'s
                # docstring for why this ordering is what makes stop() a
                # barrier rather than a hint.
                if self._stop.is_set():
                    return False
                self._device, self._info = device, info
                self._is_ds5, self._scales = is_ds5, scales
                # Normally None, which clears whatever the failed attempts
                # before this one left behind. When the calibration read is the
                # one thing that did not work, this is the only place that
                # reason survives -- the connection succeeded, so nothing later
                # will fail and record it.
                self._last_error = calibration_error
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
        silent = 0  # consecutive reads that timed out; see SILENT_READS_BEFORE_DROP
        while not self._stop.is_set():
            with self._lock:
                device = self._device
            if device is None:
                # A fresh connection starts its silence budget over; a count
                # carried from the dead handle would drop a healthy one.
                silent = 0
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
                self._drop(device)
                self._stop.wait(RESCAN_SECONDS)
                continue
            if not data:
                # See SILENT_READS_BEFORE_DROP: a timeout is not proof of health.
                silent += 1
                if silent >= SILENT_READS_BEFORE_DROP:
                    with self._lock:
                        self._last_error = (
                            "no input report for %.1fs - treating the device as gone"
                            % (silent * READ_TIMEOUT_MS / 1000.0))
                    silent = 0
                    self._drop(device)
                    self._stop.wait(RESCAN_SECONDS)
                continue
            silent = 0
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

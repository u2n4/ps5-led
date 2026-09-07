"""close() against in-flight I/O, with no controller attached.

Every Win32 entry point the close path reaches — CreateEventW, ReadFile,
WaitForSingleObject, GetOverlappedResult, CancelIoEx, CloseHandle — is replaced
with a recorder, so these tests drive the synchronization inside HidDevice
without creating a single kernel object. The fakes reproduce what Windows
actually does to a blocked reader when its request is cancelled: the event is
signalled, and GetOverlappedResult then fails with ERROR_OPERATION_ABORTED.
"""

import ctypes
import platform
import threading
import time
import unittest
from unittest import mock

DEVICE_HANDLE = 0x0BAD0001
READ_EVENT = 0x0BAD0002
WRITE_EVENT = 0x0BAD0003
ERROR_OPERATION_ABORTED = 995


@unittest.skipUnless(platform.system() == "Windows", "Windows-only module")
class TestCloseSynchronization(unittest.TestCase):
    def setUp(self):
        from ps5led import hid_win

        self.hid_win = hid_win
        self.calls = []
        self._recorder = threading.Lock()
        # Set by the fake CancelIoEx, exactly as the kernel signals the
        # OVERLAPPED's event when it completes a cancelled request.
        self.io_signalled = threading.Event()
        events = [READ_EVENT, WRITE_EVENT]

        def record(*call):
            with self._recorder:
                self.calls.append(call)

        def fake_create_event(attributes, manual_reset, initial, name):
            return events.pop(0)

        def fake_close_handle(handle):
            record("CloseHandle", handle)
            return 1

        def fake_cancel_io_ex(handle, overlapped):
            record("CancelIoEx", handle, overlapped)
            self.io_signalled.set()
            return 1

        def fake_read_file(handle, buf, length, transferred, overlapped):
            record("ReadFile", handle, length)
            ctypes.set_last_error(hid_win.ERROR_IO_PENDING)
            return 0

        def fake_wait(handle, timeout_ms):
            record("WaitForSingleObject", handle, timeout_ms)
            if self.io_signalled.wait(timeout_ms / 1000.0):
                return hid_win.WAIT_OBJECT_0
            return hid_win.WAIT_TIMEOUT

        def fake_overlapped_result(handle, overlapped, transferred, wait):
            record("GetOverlappedResult", handle, bool(wait))
            ctypes.set_last_error(ERROR_OPERATION_ABORTED)
            return 0

        for name, fake in (("CreateEventW", fake_create_event),
                           ("CloseHandle", fake_close_handle),
                           ("CancelIoEx", fake_cancel_io_ex),
                           ("ReadFile", fake_read_file),
                           ("WaitForSingleObject", fake_wait),
                           ("GetOverlappedResult", fake_overlapped_result)):
            patcher = mock.patch.object(hid_win._kernel32, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.device = hid_win.HidDevice(DEVICE_HANDLE, hid_win.DeviceInfo(
            path="fake", vendor_id=0x054C, product_id=0x0CE6, product="fake",
            input_length=64, output_length=48, feature_length=64, transport="usb"))

    def snapshot(self):
        with self._recorder:
            return list(self.calls)

    def test_close_cancels_then_closes_the_handle_then_the_events(self):
        self.device.close()

        self.assertEqual(self.snapshot(), [
            ("CancelIoEx", DEVICE_HANDLE, None),
            ("CloseHandle", DEVICE_HANDLE),
            ("CloseHandle", READ_EVENT),
            ("CloseHandle", WRITE_EVENT),
        ])

    def test_close_is_idempotent(self):
        self.device.close()
        after_first = self.snapshot()

        self.device.close()

        self.assertEqual(self.snapshot(), after_first)

    def test_close_waits_for_a_reader_that_is_inside_read(self):
        reading = threading.Event()
        outcome = []

        def reader():
            reading.set()
            try:
                outcome.append(self.device.read(timeout_ms=30000))
            except self.hid_win.HidError as exc:
                outcome.append(exc)
            with self._recorder:
                self.calls.append(("read returned",))

        thread = threading.Thread(target=reader)
        thread.start()
        self.assertTrue(reading.wait(5))
        # Let the reader reach WaitForSingleObject, so close() meets a genuinely
        # blocked operation rather than one that has not started yet.
        deadline = time.time() + 5
        while time.time() < deadline:
            if any(call[0] == "WaitForSingleObject" for call in self.snapshot()):
                break
            time.sleep(0.005)
        self.assertIn("WaitForSingleObject", [call[0] for call in self.snapshot()])

        self.device.close()
        thread.join(10)
        self.assertFalse(thread.is_alive())

        calls = self.snapshot()
        # Nothing is closed until the reader has left read(): closing the event
        # under its WaitForSingleObject is undefined behaviour, and closing the
        # device handle frees a value the reader's frame still holds.
        self.assertLess(calls.index(("read returned",)),
                        calls.index(("CloseHandle", DEVICE_HANDLE)))
        self.assertLess(calls.index(("CancelIoEx", DEVICE_HANDLE, None)),
                        calls.index(("CloseHandle", DEVICE_HANDLE)))
        self.assertLess(calls.index(("CloseHandle", DEVICE_HANDLE)),
                        calls.index(("CloseHandle", READ_EVENT)))
        # The cancelled read reports the abort; it never returns a buffer the
        # kernel was still writing into.
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], self.hid_win.HidError)
        self.assertIn(str(ERROR_OPERATION_ABORTED), str(outcome[0]))

    def test_a_new_operation_is_refused_while_close_drains(self):
        holding = threading.Event()
        release = threading.Event()

        def operation():
            self.device._begin()
            holding.set()
            release.wait(10)
            self.device._end()

        thread = threading.Thread(target=operation)
        thread.start()
        self.assertTrue(holding.wait(5))
        closer = threading.Thread(target=self.device.close)
        closer.start()
        try:
            # CancelIoEx is issued after close() has taken the closing flag, so
            # seeing it means close() is now waiting for the drain.
            deadline = time.time() + 5
            while time.time() < deadline and not self.snapshot():
                time.sleep(0.005)
            self.assertEqual(self.snapshot(), [("CancelIoEx", DEVICE_HANDLE, None)])

            with self.assertRaises(self.hid_win.HidError):
                self.device.read(timeout_ms=10)
            with self.assertRaises(self.hid_win.HidError):
                self.device.write(b"\x02")
            with self.assertRaises(self.hid_win.HidError):
                self.device.get_feature(0x05, 41)
        finally:
            release.set()
            thread.join(10)
            closer.join(10)
        self.assertFalse(closer.is_alive())

    def test_read_after_close_raises(self):
        self.device.close()

        with self.assertRaises(self.hid_win.HidError):
            self.device.read(timeout_ms=10)

    def test_read_rejects_infinite_and_negative_timeouts(self):
        for bad in (-1, 0xFFFFFFFF, 0x100000000):
            with self.assertRaises(self.hid_win.HidError) as caught:
                self.device.read(timeout_ms=bad)
            self.assertIn("timeout_ms", str(caught.exception))
        # Rejected before any I/O is issued, so nothing is left in flight.
        self.assertEqual(self.snapshot(), [])


if __name__ == "__main__":
    unittest.main()

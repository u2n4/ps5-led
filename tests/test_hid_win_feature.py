"""get_feature() against a fake Win32, with no controller attached.

HidDevice.open always passes FILE_FLAG_OVERLAPPED. HidD_GetFeature issues a
synchronous DeviceIoControl with a NULL lpOverlapped internally, and Microsoft
documents that on an overlapped handle that call can report the operation
complete before it is -- at which point the driver is still holding a pointer
into a frame-local create_string_buffer that Python has already released. Same
defect class as the two Criticals fixed earlier in read() and close(): a kernel
writing into a buffer whose lifetime the code does not hold.

The fakes below reproduce exactly that timing. DeviceIoControl returns
ERROR_IO_PENDING and writes nothing; the payload appears only when
GetOverlappedResult completes. Code that reads the buffer before waiting sees
its own request back, not the report.
"""

import ctypes
import platform
import unittest
from unittest import mock

DEVICE_HANDLE = 0x0BAD0001
FIRST_EVENT = 0x0BAD0100
REPORT_ID = 0x05
REPORT_LENGTH = 41
ERROR_NOT_SUPPORTED = 50
# What the "driver" answers with, once the request completes.
PAYLOAD = bytes([REPORT_ID]) + bytes(range(1, 12))


@unittest.skipUnless(platform.system() == "Windows", "Windows-only module")
class TestGetFeatureIsOverlapped(unittest.TestCase):
    def setUp(self):
        from ps5led import hid_win

        self.hid_win = hid_win
        self.calls = []
        self.events = []
        self.buffers = []
        # Set by a test that wants the request to fail synchronously.
        self.fail_with = None

        def record(*call):
            self.calls.append(call)

        def fake_create_event(attributes, manual_reset, initial, name):
            handle = FIRST_EVENT + len(self.events)
            self.events.append(handle)
            return handle

        def fake_close_handle(handle):
            record("CloseHandle", handle)
            return 1

        def fake_device_io_control(handle, code, in_buf, in_len,
                                   out_buf, out_len, returned, overlapped):
            record("DeviceIoControl", handle, code, in_len, out_len,
                   out_buf.raw[0], overlapped._obj.hEvent)
            self.buffers.append(out_buf)
            if self.fail_with is not None:
                ctypes.set_last_error(self.fail_with)
                return 0
            ctypes.set_last_error(hid_win.ERROR_IO_PENDING)
            return 0

        def fake_overlapped_result(handle, overlapped, transferred, wait):
            record("GetOverlappedResult", handle, bool(wait))
            # The kernel writes the report here and nowhere earlier.
            self.buffers[-1][:len(PAYLOAD)] = PAYLOAD
            transferred._obj.value = len(PAYLOAD)
            return 1

        def forbidden(*args):
            raise AssertionError(
                "HidD_GetFeature must not be used on an overlapped handle")

        for library, name, fake in (
                (hid_win._kernel32, "CreateEventW", fake_create_event),
                (hid_win._kernel32, "CloseHandle", fake_close_handle),
                (hid_win._kernel32, "DeviceIoControl", fake_device_io_control),
                (hid_win._kernel32, "GetOverlappedResult", fake_overlapped_result),
                (hid_win._hid, "HidD_GetFeature", forbidden)):
            patcher = mock.patch.object(library, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.device = hid_win.HidDevice(DEVICE_HANDLE, hid_win.DeviceInfo(
            path="fake", vendor_id=0x054C, product_id=0x0CE6, product="fake",
            input_length=64, output_length=48, feature_length=64, transport="usb"))
        # The two per-instance events the constructor made are not this test's
        # subject; only what get_feature does on top of them is.
        self.calls = []

    def test_the_report_is_read_after_the_request_completes(self):
        data = self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        self.assertIsNotNone(data, "a completing request must return the report")
        self.assertEqual(len(data), REPORT_LENGTH)
        self.assertEqual(data[:len(PAYLOAD)], PAYLOAD,
                         "the buffer was read before the kernel filled it")

    def test_the_request_goes_through_an_overlapped_device_io_control(self):
        self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        issued = [call for call in self.calls if call[0] == "DeviceIoControl"]
        self.assertEqual(len(issued), 1)
        _, handle, code, in_len, out_len, first_byte, event = issued[0]
        self.assertEqual(handle, DEVICE_HANDLE)
        self.assertEqual(code, self.hid_win.IOCTL_HID_GET_FEATURE)
        self.assertEqual((in_len, out_len), (REPORT_LENGTH, REPORT_LENGTH))
        self.assertEqual(first_byte, REPORT_ID,
                         "the report id is passed in byte 0 of the buffer")
        self.assertIsNotNone(event,
                             "a NULL OVERLAPPED is the defect being fixed")

    def test_it_blocks_on_the_completion_before_returning(self):
        self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        waits = [call for call in self.calls if call[0] == "GetOverlappedResult"]
        self.assertEqual(len(waits), 1)
        self.assertTrue(waits[0][2],
                        "GetOverlappedResult must be called with bWait=True; "
                        "returning while the request is pending is the whole bug")

    def test_the_per_call_event_is_its_own_and_is_released(self):
        self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        # A third event, distinct from the instance's read and write events: a
        # concurrent read() or write() waiting on a shared one would wake on
        # this completion instead of its own.
        self.assertEqual(len(self.events), 3)
        feature_event = self.events[2]
        self.assertNotIn(feature_event, self.events[:2])
        issued = [call for call in self.calls if call[0] == "DeviceIoControl"][0]
        self.assertEqual(issued[6], feature_event)
        self.assertIn(("CloseHandle", feature_event), self.calls,
                      "the per-call event must not leak")

    def test_a_synchronous_failure_returns_none_and_names_the_error(self):
        self.fail_with = ERROR_NOT_SUPPORTED

        data = self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        self.assertIsNone(data)
        self.assertIn(str(ERROR_NOT_SUPPORTED), self.device.last_error)
        self.assertIn("IOCTL_HID_GET_FEATURE", self.device.last_error)
        self.assertNotIn("GetOverlappedResult",
                         [call[0] for call in self.calls],
                         "nothing is pending, so nothing may be waited on")
        self.assertIn(("CloseHandle", self.events[2]), self.calls,
                      "the event must be released on the failure path too")

    def test_the_device_stays_usable_after_a_failed_read(self):
        self.fail_with = ERROR_NOT_SUPPORTED
        self.assertIsNone(self.device.get_feature(REPORT_ID, REPORT_LENGTH))
        self.fail_with = None

        data = self.device.get_feature(REPORT_ID, REPORT_LENGTH)

        self.assertIsNotNone(data, "_end() must have released the operation")
        self.assertEqual(data[:len(PAYLOAD)], PAYLOAD)


if __name__ == "__main__":
    unittest.main()

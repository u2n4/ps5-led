"""enumerate_devices reports a controller interface it cannot describe (Windows only)."""
import ctypes
import os
import unittest
from unittest.mock import Mock, patch

PATH = r"\\?\HID#VID_054C&PID_0CE6#7&2A1F&0&0000#{4D1E55B2-F16F-11CF-88CB-001111000030}"


def _attributes(vendor_id):
    # Fills the HIDD_ATTRIBUTES that _describe passes by reference.
    def fill(handle, attrs_ref):
        attrs_ref._obj.VendorID = vendor_id
        attrs_ref._obj.ProductID = 0x0CE6
        return 1
    return fill


def _no_preparsed_data(handle, out_ref):
    ctypes.set_last_error(87)  # ERROR_INVALID_PARAMETER
    return 0


@unittest.skipUnless(os.name == "nt", "hid_win loads the Windows HID library")
class EnumerateReportsTests(unittest.TestCase):
    def enumerate_with(self, vendor_filter):
        from ps5led import hid_win
        hid = Mock()
        hid.HidD_GetAttributes.side_effect = _attributes(0x054C)
        hid.HidD_GetPreparsedData.side_effect = _no_preparsed_data
        kernel32 = Mock()
        kernel32.CreateFileW.return_value = 1
        with patch.object(hid_win, "_interface_paths", return_value=[PATH]), \
                patch.object(hid_win, "_hid", hid), \
                patch.object(hid_win, "_kernel32", kernel32):
            return hid_win.enumerate_devices(vendor_filter)

    def test_wanted_vendor_without_capabilities_is_reported(self):
        from ps5led.hid_win import HidError
        with self.assertRaises(HidError) as caught:
            self.enumerate_with(0x054C)
        self.assertIn(PATH, str(caught.exception))
        self.assertIn("HidD_GetPreparsedData", str(caught.exception))

    def test_other_vendor_is_not_reported(self):
        self.assertEqual(self.enumerate_with(0x1234), [])

    def test_unfiltered_enumeration_skips_quietly(self):
        self.assertEqual(self.enumerate_with(None), [])


if __name__ == "__main__":
    unittest.main()

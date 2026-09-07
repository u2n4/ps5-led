import platform
import unittest


class TestPlatformIsolation(unittest.TestCase):
    def test_protocol_modules_do_not_pull_in_windows_code(self):
        """crc/dualsense/dualshock4 must import anywhere — CI runs on Linux."""
        import ps5led.crc  # noqa: F401
        import ps5led.dualsense  # noqa: F401
        import ps5led.dualshock4  # noqa: F401

    @unittest.skipUnless(platform.system() == "Windows", "Windows-only module")
    def test_hid_win_imports_on_windows(self):
        from ps5led import hid_win

        self.assertTrue(hasattr(hid_win, "enumerate_devices"))
        self.assertTrue(hasattr(hid_win, "HidDevice"))


if __name__ == "__main__":
    unittest.main()

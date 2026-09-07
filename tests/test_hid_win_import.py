import os
import platform
import subprocess
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Imports the protocol modules into a fresh interpreter and reports whether the
# Windows transport was dragged in with them.
_ISOLATION_PROBE = (
    "import sys\n"
    "import ps5led.crc\n"
    "import ps5led.dualsense\n"
    "import ps5led.dualshock4\n"
    "sys.stdout.write('leaked' if 'ps5led.hid_win' in sys.modules else 'clean')\n"
)


class TestPlatformIsolation(unittest.TestCase):
    def test_protocol_modules_do_not_pull_in_windows_code(self):
        """crc/dualsense/dualshock4 must import anywhere — CI runs on Linux."""
        import ps5led.crc  # noqa: F401
        import ps5led.dualsense  # noqa: F401
        import ps5led.dualshock4  # noqa: F401

        # The sys.modules assertion has to run in a fresh interpreter. On
        # Windows, test_hid_win_imports_on_windows sorts ahead of this test and
        # imports ps5led.hid_win, so an in-process check would fail here no
        # matter what the protocol modules import — and on Linux it would pass
        # for the wrong reason, since hid_win cannot import there at all.
        env = dict(os.environ)
        inherited = env.get("PYTHONPATH")
        env["PYTHONPATH"] = _REPO_ROOT + ((os.pathsep + inherited) if inherited else "")
        probe = subprocess.run([sys.executable, "-c", _ISOLATION_PROBE],
                               cwd=_REPO_ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        self.assertEqual(probe.returncode, 0, probe.stderr.decode("utf-8", "replace"))
        self.assertEqual(probe.stdout.decode("ascii"), "clean",
                         "a protocol module imports ps5led.hid_win at module scope")

    @unittest.skipUnless(platform.system() == "Windows", "Windows-only module")
    def test_hid_win_imports_on_windows(self):
        from ps5led import hid_win

        self.assertTrue(hasattr(hid_win, "enumerate_devices"))
        self.assertTrue(hasattr(hid_win, "HidDevice"))


if __name__ == "__main__":
    unittest.main()

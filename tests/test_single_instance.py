"""Only one copy of the app may run at a time, from any path, any version.

The guard is a named Windows mutex, Global\\DualSenseLED_SingleInstance. Both
the current build and the v2.3.0 build a user may still have installed use the
same name, so a stale copy and a fresh one cannot drive the same lightbar
together either.

It is tested across two PROCESSES on purpose. A mutex is per process, so the
only way to prove a second copy is refused is to hold the mutex here and ask a
child interpreter whether it can take it. Calling the function twice in one
process would pass regardless -- a process re-opening its own mutex does not
get ERROR_ALREADY_EXISTS in the way that matters here.
"""
import ctypes
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = r"""
import sys
sys.path.insert(0, %r)
import dualled_pro
print("SECOND_COPY_ALLOWED" if dualled_pro._acquire_global_mutex() else "SECOND_COPY_REFUSED")
"""


def _ask_child():
    proc = subprocess.run([sys.executable, "-c", CHILD % REPO], cwd=REPO,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=60)
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-400:]


@unittest.skipUnless(os.name == "nt", "the guard is a Windows named mutex")
class TestSingleInstance(unittest.TestCase):
    def test_second_copy_is_refused_while_the_first_holds_the_mutex(self):
        import dualled_pro
        self.assertTrue(dualled_pro._acquire_global_mutex(), "nothing else should hold it yet")
        try:
            self.assertEqual(_ask_child(), "SECOND_COPY_REFUSED")
        finally:
            handle = dualled_pro._win_handles.pop("mutex", None)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)

    def test_a_copy_is_allowed_once_the_first_has_released_it(self):
        # The negative control: the same child, with nobody holding the mutex,
        # must be allowed -- otherwise the test above passes for a mutex that
        # is simply always taken (a leak from an earlier process, say).
        self.assertEqual(_ask_child(), "SECOND_COPY_ALLOWED")


if __name__ == "__main__":
    unittest.main()

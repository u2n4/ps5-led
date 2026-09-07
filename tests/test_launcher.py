import os
import platform
import tempfile
import unittest

from ps5led import launcher


class TestBrowserArgs(unittest.TestCase):
    def setUp(self):
        self.profile = os.path.join(tempfile.mkdtemp(), "browser")

    def test_app_mode_carries_the_url(self):
        args = launcher.browser_args("edge.exe", "http://127.0.0.1:1/?t=x", self.profile)
        self.assertTrue(any(a == "--app=http://127.0.0.1:1/?t=x" for a in args))

    def test_the_executable_is_first(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertEqual(args[0], "edge.exe")

    def test_a_private_profile_directory_is_always_passed(self):
        # A shared profile attaches to an already-running browser and exits
        # immediately, so the process would not be ours to wait on.
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in args))

    def test_first_run_prompts_are_suppressed(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile)
        self.assertIn("--no-first-run", args)
        self.assertIn("--no-default-browser-check", args)

    def test_fullscreen_is_requested_only_when_asked(self):
        plain = launcher.browser_args("edge.exe", "http://x", self.profile)
        full = launcher.browser_args("edge.exe", "http://x", self.profile, fullscreen=True)
        self.assertNotIn("--start-fullscreen", plain)
        self.assertIn("--start-fullscreen", full)

    def test_a_window_size_is_passed_when_not_fullscreen(self):
        args = launcher.browser_args("edge.exe", "http://x", self.profile, size=(900, 700))
        self.assertIn("--window-size=900,700", args)

    def test_no_argument_contains_a_shell_metacharacter(self):
        # The process is spawned with shell=False, but an argument that needs
        # quoting is a sign the url was built wrong.
        args = launcher.browser_args("edge.exe", "http://127.0.0.1:1/?t=abc", self.profile)
        for arg in args:
            self.assertNotIn("&&", arg)
            self.assertNotIn("|", arg)


class TestFindBrowser(unittest.TestCase):
    def test_candidates_are_absolute_paths(self):
        for path in launcher.BROWSERS:
            self.assertTrue(os.path.isabs(path), path)

    def test_edge_is_preferred_over_chrome(self):
        joined = " ".join(launcher.BROWSERS).lower()
        self.assertLess(joined.index("edge"), joined.index("chrome"))

    @unittest.skipUnless(platform.system() == "Windows", "Windows browser paths")
    def test_find_browser_returns_something_that_exists_or_none(self):
        found = launcher.find_browser()
        if found is not None:
            self.assertTrue(os.path.exists(found))


class TestProfileDir(unittest.TestCase):
    def test_default_profile_dir_is_under_the_config_dir(self):
        from ps5led.config import config_dir
        self.assertEqual(launcher.default_profile_dir().parent, config_dir())


if __name__ == "__main__":
    unittest.main()

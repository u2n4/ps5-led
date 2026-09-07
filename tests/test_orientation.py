"""The orientation filter, checked against a real accelerometer reading.

The filter is JavaScript, so this drives it through node rather than
reimplementing it -- a test of a reimplementation would pass while the
shipped code was wrong, which is close to what happened here: the original
verification used an invented at-rest vector of [0, 0, 1] and passed, while
the hardware reports gravity on a different axis entirely.

The sample below was read off the device over Bluetooth with the controller
flat on the desk, face up and stationary. It is the pose the model must
render level.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE = REPO / "tests" / "orientation_probe.mjs"
NODE = shutil.which("node")

# Measured with AXIS_ORDER = [0, 2, 1]. A DualSense leans back on its curved
# grips, so a level desk does not read zero -- about nine degrees is the desk.
EXPECTED_REST_ROLL = 8.98
# What the same reading produced before the axis order was corrected. Named so
# that a regression is recognised rather than puzzled over.
BROKEN_REST_ROLL = 81.02


@unittest.skipUnless(NODE, "node is not on PATH")
class TestOrientationAgainstRealHardware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # stderr is discarded on purpose: node warns about the module type of a
        # bare .js under a package.json it found elsewhere on the disk, which
        # says nothing about this code. stdout carries only the JSON.
        result = subprocess.run(
            [NODE, str(PROBE)], cwd=str(REPO),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if result.returncode != 0:
            raise AssertionError("probe failed: %s"
                                 % result.stderr.decode("utf-8", "replace"))
        cls.pose = json.loads(result.stdout.decode("utf-8"))

    def test_a_controller_lying_flat_renders_close_to_level(self):
        roll = self.pose["at_rest"]["roll"]
        self.assertAlmostEqual(roll, EXPECTED_REST_ROLL, delta=2.0)

    def test_a_controller_lying_flat_is_not_stood_on_its_edge(self):
        # The regression this file exists for: the filter read 81 degrees of
        # roll off a stationary controller, and the model hung at that angle.
        roll = self.pose["at_rest"]["roll"]
        self.assertLess(abs(roll - BROKEN_REST_ROLL), 200)   # sanity: same units
        self.assertGreater(abs(roll - BROKEN_REST_ROLL), 60,
                           "the axis order has regressed to the identity")

    def test_pitch_is_level_when_the_controller_is_not_tilted_sideways(self):
        self.assertAlmostEqual(self.pose["at_rest"]["pitch"], 0.0, delta=2.0)

    def test_the_quaternion_stays_on_the_unit_sphere(self):
        self.assertAlmostEqual(self.pose["at_rest_norm"], 1.0, places=9)

    def test_the_filter_still_responds_to_a_real_tilt(self):
        # Otherwise "level at rest" could be satisfied by a filter stuck at
        # identity, which would pass every assertion above.
        self.assertAlmostEqual(self.pose["on_its_side"]["roll"], -81.02, delta=5.0)

    def test_the_probe_is_reachable(self):
        self.assertTrue(PROBE.is_file(), "%s is missing" % PROBE)


class TestAxisOrderIsDeclared(unittest.TestCase):
    """Readable without node, so the constant cannot vanish unnoticed."""

    def test_axis_order_swaps_y_and_z(self):
        source = (REPO / "web" / "js" / "orientation.js").read_text(
            encoding="utf-8")
        self.assertIn("const AXIS_ORDER = [0, 2, 1];", source)

    def test_axis_sign_is_still_present(self):
        source = (REPO / "web" / "js" / "orientation.js").read_text(
            encoding="utf-8")
        self.assertIn("const AXIS_SIGN = ", source)


if __name__ == "__main__":
    unittest.main()

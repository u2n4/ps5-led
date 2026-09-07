"""No caller may pass Windows' OutputReportByteLength straight into build_output.

This exact mistake shipped twice. It was fixed in ps5led/device.py and missed in
tools/live_check.py, so Bluetooth still died in the field with

    ValueError: Bluetooth reports are 78 bytes, got 547

on the setup packet. The rule now lives in dualsense.output_length_for, and this
test is what keeps a third copy from appearing: it reads the tree, so it fails
for a file nobody thought to update.
"""

import pathlib
import re
import unittest

from ps5led import dualsense as ds

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCHED = sorted(
    p for p in list(ROOT.glob("ps5led/*.py")) + list(ROOT.glob("tools/*.py"))
    if p.name != "dualsense.py"
)

# `ds.build_output(transport, info.output_length` and friends: the second
# positional argument taken straight from a DeviceInfo.
RAW = re.compile(r"build_output\(\s*[^,]+,\s*[A-Za-z_][A-Za-z_0-9]*\.output_length\b")


class TestOutputLengthIsAlwaysDerived(unittest.TestCase):
    def test_the_helper_exists_and_is_the_rule(self):
        self.assertEqual(ds.output_length_for(ds.TRANSPORT_BT, 547), ds.BT_OUTPUT_SIZE)
        self.assertEqual(ds.output_length_for(ds.TRANSPORT_BT, 78), ds.BT_OUTPUT_SIZE)
        self.assertEqual(ds.output_length_for(ds.TRANSPORT_USB, 48), 48)
        self.assertEqual(ds.output_length_for(ds.TRANSPORT_USB, 63), 63)

    def test_we_are_actually_searching_files(self):
        # A regex test over an empty file list passes for the wrong reason.
        self.assertGreaterEqual(len(SEARCHED), 5, "found no sources to scan")
        self.assertTrue(any(p.name == "live_check.py" for p in SEARCHED),
                        "the file that shipped the bug is not being scanned")

    def test_no_source_passes_a_reported_length_straight_through(self):
        offenders = []
        for path in SEARCHED:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            for match in RAW.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append("%s:%d" % (path.relative_to(ROOT).as_posix(), line))
        self.assertEqual(
            offenders, [],
            "pass ds.output_length_for(transport, info.output_length) instead: " + ", ".join(offenders))

    def test_the_regex_would_catch_the_bug_it_guards(self):
        # Negative control: the pattern must match the shape that shipped.
        self.assertTrue(RAW.search("ds.build_output(info.transport, info.output_length, rgb=rgb)"))
        self.assertIsNone(RAW.search(
            "ds.build_output(info.transport, ds.output_length_for(info.transport, info.output_length))"))


if __name__ == "__main__":
    unittest.main()

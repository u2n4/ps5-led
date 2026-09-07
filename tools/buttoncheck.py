"""Live check: what the controller sends, and what the model would do with it.

Two jobs. It proves the real data path end to end -- device -> state ->
read_inputs -> the parts that move -- which synthetic samples cannot. And it
names which physical button owns which bit, which is the one thing about the
button decoding that was taken from the kernel source rather than measured on
this hardware.

Move the sticks, pull the triggers, press the buttons. Every change prints.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ps5led.device import DeviceManager

try:
    from controller_gl import read_inputs_of
except ImportError:
    read_inputs_of = None

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0


class State:
    """The same shape dualled_pro's Backend keeps."""

    def __init__(self):
        self.v = dict(connected=False, left_stick=(0.0, 0.0),
                      right_stick=(0.0, 0.0), triggers=(0.0, 0.0), buttons=0)

    def update(self, **kw):
        self.v.update(kw)

    def snapshot(self):
        return dict(self.v)


def decode(sample):
    """What ControllerGL would move, without needing a GL context."""
    if read_inputs_of is not None:
        return read_inputs_of(sample)
    from controller_gl import ControllerGL
    return ControllerGL.read_inputs(sample)


state = State()
manager = DeviceManager(state)
manager.start()
print("Move the sticks, pull L2/R2, press the buttons. %.0f seconds.\n" % SECONDS)

last = None
bits_seen = {}
deadline = time.time() + SECONDS
try:
    while time.time() < deadline:
        snap = state.snapshot()
        if snap.get("connected"):
            parts = decode(snap)
            buttons = snap.get("buttons") or 0
            for bit in range(20):
                if buttons & (1 << bit):
                    bits_seen.setdefault(bit, 0)
                    bits_seen[bit] += 1
            key = (tuple(sorted(parts)), round(buttons, 0))
            if key != last:
                last = key
                ls = [round(v, 2) for v in snap.get("left_stick") or ()]
                rs = [round(v, 2) for v in snap.get("right_stick") or ()]
                tr = [round(v, 2) for v in snap.get("triggers") or ()]
                print("buttons 0x%04X  L%s R%s T%s   -> moves: %s"
                      % (buttons, ls, rs, tr,
                         ", ".join(sorted(parts)) or "(nothing)"))
        time.sleep(0.08)
finally:
    manager.stop()

print()
if not bits_seen:
    print("No button bit was ever set. Either nothing was pressed, or the")
    print("controller never connected.")
else:
    print("bits that went high (bit: how many samples):")
    for bit in sorted(bits_seen):
        named = {4: "square", 5: "cross", 6: "circle", 7: "triangle",
                 8: "L1", 9: "R1", 10: "L2", 11: "R2", 12: "create",
                 13: "options", 14: "L3", 15: "R3", 16: "PS",
                 17: "touchpad", 18: "mic"}.get(bit, "?")
        print("   bit %-3d %-9s %d" % (bit, named, bits_seen[bit]))
    print()
    print("Check the names against what you actually pressed. A mismatch means")
    print("BUTTON_BITS in controller_gl.py needs that one bit changed.")

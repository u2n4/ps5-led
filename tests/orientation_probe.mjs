// Drive web/js/orientation.js with a real accelerometer reading and report
// the pose it settles on. Run by tests/test_orientation.py; prints one JSON
// object on stdout and nothing else.
//
// The sample is measured, not invented: Ali's DualSense over Bluetooth, flat
// on the desk, face up, stationary. That is the pose the model must render
// level, and the number this harness exists to pin.

import { createOrientation } from '../web/js/orientation.js';

// Measured: accel [0.001, 0.962, 0.152], gyro effectively zero.
const AT_REST_ACCEL = [0.001, 0.962, 0.152];
const AT_REST_GYRO = [0.0, -0.49, -0.12];

const DT = 1 / 250;          // the controller reports at about 250 Hz
const SETTLE_STEPS = 3000;   // 12 s of samples; ALPHA = 0.98 needs a while

function eulerDegrees([x, y, z, w]) {
  // Intrinsic Z-Y-X, matching how the filter builds `measured` from roll and
  // pitch, so a round trip through the quaternion returns what went in.
  const sinp = 2 * (w * y - z * x);
  const pitch = Math.abs(sinp) >= 1
    ? Math.sign(sinp) * Math.PI / 2
    : Math.asin(sinp);
  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  const deg = (r) => (r * 180) / Math.PI;
  return { roll: deg(roll), pitch: deg(pitch), yaw: deg(yaw) };
}

const o = createOrientation();
let q = [0, 0, 0, 1];
for (let i = 0; i < SETTLE_STEPS; i += 1) {
  q = o.update(AT_REST_GYRO, AT_REST_ACCEL, DT);
}

const norm = Math.hypot(q[0], q[1], q[2], q[3]);

// A second instance, to show the filter is not merely stuck at identity: a
// deliberate 90 degree roll must actually move it.
const tilted = createOrientation();
let t = [0, 0, 0, 1];
for (let i = 0; i < SETTLE_STEPS; i += 1) {
  t = tilted.update([0, 0, 0], [0.001, 0.152, -0.962], DT);
}

process.stdout.write(JSON.stringify({
  at_rest: eulerDegrees(q),
  at_rest_norm: norm,
  on_its_side: eulerDegrees(t),
}));

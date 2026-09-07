// Gyro + accel -> a quaternion the scene can slerp toward.
//
// Integration alone drifts; the accelerometer alone is noisy and blind to yaw.
// So pitch and roll are corrected against gravity with a complementary filter
// and yaw is left to integration plus an explicit recentre - nothing in the
// controller can observe absolute heading, so pretending otherwise would only
// hide the drift somewhere less obvious.

const DEG = Math.PI / 180;
const ALPHA = 0.98;          // trust the gyro this much per correction step
const STALE_MS = 250;        // no sample for this long -> ease back to front
const MAX_DT = 0.1;          // a longer gap is a stall, not a rotation

// Provisional. The kernel's axis order is known (gyro X = pitch, Y = yaw,
// Z = roll) but the sign of each axis - which way the model should turn for
// a positive reading - depends on how the GLB was authored, and nothing
// short of looking at the live model settles that. Set by observation:
// tilt nose-down and the model must tilt nose-down, roll right and the
// model must roll right; negate whichever component goes the wrong way.
const AXIS_SIGN = [1, 1, 1];

const multiply = (a, b) => [
  a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
  a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
  a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
  a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
];

const normalise = (q) => {
  const length = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
  return [q[0] / length, q[1] / length, q[2] / length, q[3] / length];
};

export function createOrientation() {
  let q = [0, 0, 0, 1];
  let lastSampleAt = 0;

  function update(gyro, accel, dt) {
    lastSampleAt = performance.now();
    if (!(dt > 0) || dt > MAX_DT) return q;

    const gx = gyro[0] * AXIS_SIGN[0] * DEG;
    const gy = gyro[1] * AXIS_SIGN[1] * DEG;
    const gz = gyro[2] * AXIS_SIGN[2] * DEG;
    const half = dt / 2;
    q = normalise(multiply(q, [gx * half, gy * half, gz * half, 1]));

    // Gravity correction, only when the accelerometer is reading close to 1g:
    // during a shake it is measuring the shake, not down.
    const magnitude = Math.hypot(accel[0], accel[1], accel[2]);
    if (magnitude > 0.85 && magnitude < 1.15) {
      const ax = (accel[0] * AXIS_SIGN[0]) / magnitude;
      const ay = (accel[1] * AXIS_SIGN[1]) / magnitude;
      const az = (accel[2] * AXIS_SIGN[2]) / magnitude;
      const pitch = Math.atan2(-ax, Math.hypot(ay, az));
      const roll = Math.atan2(ay, az);
      const cp = Math.cos(pitch / 2), sp = Math.sin(pitch / 2);
      const cr = Math.cos(roll / 2), sr = Math.sin(roll / 2);
      const measured = normalise([sr * cp, cr * sp, -sr * sp, cr * cp]);
      q = normalise(q.map((value, i) => value * ALPHA + measured[i] * (1 - ALPHA)));
    }
    return q;
  }

  return {
    update,
    recentre() { q = [0, 0, 0, 1]; },
    isStale(now = performance.now()) {
      return lastSampleAt === 0 || now - lastSampleAt > STALE_MS;
    },
    current() { return q; },
  };
}

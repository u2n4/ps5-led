import { boot, connect } from './bridge.js';
import { startParticles } from './particles.js';
import { createScene } from './scene.js';
import { createOrientation } from './orientation.js';

startParticles(document.getElementById('particles'));

const conn = document.getElementById('conn');
const batt = document.getElementById('batt');
const fallback = document.getElementById('scene-fallback');

let scene = null;
try {
  scene = createScene(document.getElementById('scene'));
} catch (error) {
  // WebGL can be unavailable; the lightbar does not depend on the picture.
  fallback.hidden = false;
  fallback.textContent = `3D view unavailable: ${error.message}`;
}

boot().then((payload) => {
  document.title = payload.i18n.en.app_title;
  scene?.setShell(payload.config.shell);
}).catch((error) => {
  conn.textContent = String(error);
  conn.className = 'pill bad';
});

const orientation = createOrientation();
let lastTimestamp = null;

connect({
  onState(state) {
    conn.textContent = state.connected
      ? (state.transport === 'bt' ? 'Bluetooth' : 'USB')
      : 'Disconnected';
    conn.className = `pill ${state.connected ? 'ok' : 'bad'}`;
    batt.textContent = state.battery == null ? '—' : `${state.battery}%`;
    if (state.rgb) scene?.setColour(state.rgb);
  },
  onSensor(sensor) {
    if (!sensor.gyro || !sensor.accel) return;
    // The controller's own clock, in units of 1/3 000 000 s. A browser frame
    // that arrives late must not stretch a rotation that never happened.
    let dt = 0;
    if (lastTimestamp !== null) {
      dt = ((sensor.sensor_timestamp - lastTimestamp) >>> 0) / 3000000;
    }
    lastTimestamp = sensor.sensor_timestamp;
    scene?.setOrientation(orientation.update(sensor.gyro, sensor.accel, dt));
  },
});

// No sample for a while (controller idle/disconnected) -> ease back to front.
setInterval(() => {
  if (orientation.isStale()) scene?.setOrientation([0, 0, 0, 1]);
}, 200);

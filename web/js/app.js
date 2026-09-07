import { boot, connect } from './bridge.js';
import { startParticles } from './particles.js';
import { createScene } from './scene.js';

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

connect({
  onState(state) {
    conn.textContent = state.connected
      ? (state.transport === 'bt' ? 'Bluetooth' : 'USB')
      : 'Disconnected';
    conn.className = `pill ${state.connected ? 'ok' : 'bad'}`;
    batt.textContent = state.battery == null ? '—' : `${state.battery}%`;
    if (state.rgb) scene?.setColour(state.rgb);
  },
});

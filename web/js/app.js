import { boot, connect } from './bridge.js';
import { startParticles } from './particles.js';

startParticles(document.getElementById('particles'));

const conn = document.getElementById('conn');
const batt = document.getElementById('batt');

boot()
  .then((payload) => { document.title = payload.i18n.en.app_title; })
  .catch((error) => { conn.textContent = String(error); conn.className = 'pill bad'; });

connect({
  onState(state) {
    conn.textContent = state.connected
      ? (state.transport === 'bt' ? 'Bluetooth' : 'USB')
      : 'Disconnected';
    conn.className = `pill ${state.connected ? 'ok' : 'bad'}`;
    batt.textContent = state.battery == null ? '—' : `${state.battery}%`;
  },
});

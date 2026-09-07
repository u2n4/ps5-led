// Renders the control panel from the boot payload and wires every control to
// a bridge command. boot.i18n/boot.config/boot.modes come straight from
// GET /api/boot (Task 4); every command name below is one Bridge.handle_command
// (ps5led/bridge.py) actually accepts -- an unknown cmd is rejected with a 400.

const hex = (rgb) => '#' + rgb.map((v) => v.toString(16).padStart(2, '0')).join('');
const fromHex = (value) => [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));

export function mountControls(root, { boot, send, onShell, onRecentre }) {
  const strings = boot.i18n[boot.config.language] ?? boot.i18n.en;
  const t = (key) => strings[key] ?? key;

  root.innerHTML = `
    <div class="row">
      <label data-i18n="mode">${t('mode')}</label>
      <div class="row" id="modes"></div>
    </div>
    <div class="row">
      <label data-i18n="colour">${t('colour')}</label>
      <input type="color" id="colour" value="${hex(boot.config.colour)}">
      <button id="off" data-i18n="close">${t('close')}</button>
      <button id="recentre" data-i18n="recentre">${t('recentre')}</button>
    </div>
    <div class="row">
      <label data-i18n="speed">${t('speed')}</label>
      <input type="range" id="speed" min="0.1" max="5" step="0.1" value="${boot.config.speed}">
    </div>
    <div class="row">
      <label data-i18n="brightness">${t('brightness')}</label>
      <input type="range" id="brightness" min="0.2" max="1" step="0.05" value="${boot.config.brightness}">
    </div>
    <div class="row">
      <label data-i18n="duty">${t('duty')}</label>
      <input type="range" id="duty" min="0.1" max="0.9" step="0.05" value="${boot.config.duty}">
    </div>
    <div class="row">
      <label data-i18n="shell">${t('shell')}</label>
      <div class="row" id="shells"></div>
      <label data-i18n="language">${t('language')}</label>
      <select id="language">
        <option value="ar">العربية</option>
        <option value="en">English</option>
      </select>
      <button id="about" data-i18n="about">${t('about')}</button>
    </div>
    <div class="row">
      <label data-i18n="profiles">${t('profiles')}</label>
      <input type="text" id="profile-name" aria-label="${t('profiles')}">
      <button id="profile-save" data-i18n="profile_save">${t('profile_save')}</button>
    </div>
    <div class="row" id="profile-list"></div>
    <p id="about-text" hidden class="fallback"></p>
  `;

  const modes = root.querySelector('#modes');
  for (const mode of boot.modes) {
    const button = document.createElement('button');
    button.textContent = t(`mode_${mode}`);
    button.dataset.i18n = `mode_${mode}`;
    button.setAttribute('aria-pressed', String(mode === boot.config.mode));
    button.addEventListener('click', async () => {
      const result = await send({ cmd: 'set_mode', mode });
      if (!result.ok) return;
      for (const other of modes.children) other.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
    });
    modes.append(button);
  }

  const shells = root.querySelector('#shells');
  for (const shell of ['white', 'black', 'red']) {
    const button = document.createElement('button');
    button.textContent = t(`shell_${shell}`);
    button.dataset.i18n = `shell_${shell}`;
    button.setAttribute('aria-pressed', String(shell === boot.config.shell));
    button.addEventListener('click', async () => {
      const result = await send({ cmd: 'set_shell', shell });
      if (!result.ok) return;
      for (const other of shells.children) other.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', 'true');
      onShell?.(shell);
    });
    shells.append(button);
  }

  root.querySelector('#colour').addEventListener('input', (event) => {
    send({ cmd: 'set_colour', colour: fromHex(event.target.value) });
  });
  root.querySelector('#speed').addEventListener('input', (event) => {
    send({ cmd: 'set_speed', speed: Number(event.target.value) });
  });
  root.querySelector('#brightness').addEventListener('input', (event) => {
    send({ cmd: 'set_brightness', brightness: Number(event.target.value) });
  });
  root.querySelector('#duty').addEventListener('input', (event) => {
    send({ cmd: 'set_duty', duty: Number(event.target.value) });
  });
  root.querySelector('#off').addEventListener('click', () => send({ cmd: 'off' }));
  root.querySelector('#recentre').addEventListener('click', () => onRecentre?.());

  // Each saved profile is a load button labelled with its own name -- the
  // same pattern as the mode/shell buttons above, which are labelled with
  // the thing they activate -- next to a delete button. profileItems keeps
  // the list correct after a save (no duplicate entry for a name that
  // already exists) or a delete (its element is dropped), with no reload.
  const profileList = root.querySelector('#profile-list');
  const profileItems = new Map();

  function addProfile(name) {
    if (profileItems.has(name)) return;
    const item = document.createElement('span');
    item.className = 'profile';
    const load = document.createElement('button');
    load.textContent = name;
    load.addEventListener('click', () => send({ cmd: 'profile_load', name }));
    const remove = document.createElement('button');
    remove.textContent = t('profile_delete');
    remove.dataset.i18n = 'profile_delete';
    remove.setAttribute('aria-label', `${t('profile_delete')} ${name}`);
    remove.addEventListener('click', async () => {
      const result = await send({ cmd: 'profile_delete', name });
      if (!result.ok) return;
      profileItems.delete(name);
      item.remove();
    });
    item.append(load, remove);
    profileList.append(item);
    profileItems.set(name, item);
  }

  for (const name of Object.keys(boot.config.profiles ?? {})) addProfile(name);

  const profileName = root.querySelector('#profile-name');
  root.querySelector('#profile-save').addEventListener('click', async () => {
    const name = profileName.value.trim();
    if (!name) return;
    const result = await send({ cmd: 'profile_save', name });
    if (!result.ok) return;
    addProfile(name);
    profileName.value = '';
  });

  const language = root.querySelector('#language');
  language.value = boot.config.language;
  language.addEventListener('change', (event) => {
    send({ cmd: 'set_language', language: event.target.value });
    location.reload();
  });

  const about = root.querySelector('#about-text');
  root.querySelector('#about').addEventListener('click', () => {
    about.hidden = !about.hidden;
    if (about.hidden) return;
    // CC BY 4.0 requires the credit wherever the work is shown -- see
    // ATTRIBUTION.md at the repo root, which this text quotes verbatim
    // (model name, author, licence).
    about.innerHTML = `PS5 LED ${boot.version} &middot; 3D model
      <a href="https://sketchfab.com/3d-models/ps5-controller-b7bb9c5102a04cb0b1966c6d02bad7d6"
         target="_blank" rel="noreferrer">PS5 Controller</a>
      by <a href="https://sketchfab.com/taohidanimation" target="_blank" rel="noreferrer">Taohid Animation</a>,
      licensed <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>
      &middot;
      <a href="vendor/three/LICENSE" target="_blank" rel="noreferrer">three.js</a> r185, MIT licence`;
  });
}

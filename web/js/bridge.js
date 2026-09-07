// The page's only link to the engine. Everything reconnects on its own: the
// window can outlive a bridge restart, and a dead stream must not need a reload.

const TOKEN = new URLSearchParams(location.search).get('t') ?? '';

export function token() { return TOKEN; }

export async function boot() {
  const response = await fetch(`/api/boot?t=${encodeURIComponent(TOKEN)}`);
  if (!response.ok) throw new Error(`boot failed: ${response.status}`);
  return response.json();
}

export async function send(payload) {
  const response = await fetch(`/api/cmd?t=${encodeURIComponent(TOKEN)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) return { ok: false, error: `http ${response.status}` };
  return response.json();
}

export function connect({ onState, onSensor, onOpen, onError }) {
  let source = null;
  let delay = 500;
  let closed = false;

  const open = () => {
    if (closed) return;
    source = new EventSource(`/api/stream?t=${encodeURIComponent(TOKEN)}`);
    source.addEventListener('open', () => { delay = 500; onOpen?.(); });
    source.addEventListener('state', (event) => onState?.(JSON.parse(event.data)));
    source.addEventListener('sensor', (event) => onSensor?.(JSON.parse(event.data)));
    source.addEventListener('error', () => {
      source.close();
      onError?.();
      if (closed) return;
      // Backoff, capped: a bridge that is gone for good must not spin the CPU.
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 10000);
    });
  };

  open();

  // The engine stops streaming sensor data while the page says it is hidden.
  const reportVisibility = () =>
    send({ cmd: 'visible', visible: document.visibilityState === 'visible' });
  document.addEventListener('visibilitychange', reportVisibility);
  reportVisibility();

  return {
    send,
    close() {
      closed = true;
      document.removeEventListener('visibilitychange', reportVisibility);
      source?.close();
    },
  };
}

// A drifting field that reacts to the cursor ONLY near the edges.
//
// Each particle carries edgeWeight = smoothstep(0.55, 0.85, d), where d is its
// distance from the centre normalised so the centre is 0 and a corner is 1 -
// 0 in the middle, 1 at the edges.
// Inside the central 60% the weight is 0 and the particle only drifts, so the
// area behind the panel stays calm while the border comes alive under the
// cursor. The ramp is smooth, so no boundary is visible.

const COUNT = 140;
const LINK_DISTANCE = 110;
const REPEL = 5200;

const smoothstep = (a, b, x) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

export function startParticles(canvas) {
  const context = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pointer = { x: -1e6, y: -1e6 };
  let width = 0, height = 0, particles = [], frame = 0, running = true;

  const resize = () => {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  };

  const edgeWeight = (x, y) => {
    // Normalised so the centre is 0 and a corner is 1.
    const dx = (x - width / 2) / (width / 2 || 1);
    const dy = (y - height / 2) / (height / 2 || 1);
    const d = Math.min(1, Math.hypot(dx, dy) / Math.SQRT2);
    return smoothstep(0.55, 0.85, d);
  };

  const seed = () => {
    particles = Array.from({ length: COUNT }, () => {
      const x = Math.random() * width;
      const y = Math.random() * height;
      return {
        x, y,
        vx: (Math.random() - 0.5) * (reduced ? 0.12 : 0.25),
        vy: (Math.random() - 0.5) * (reduced ? 0.12 : 0.25),
        r: Math.random() * 1.6 + 0.6,
      };
    });
  };

  const step = () => {
    if (!running) return;
    context.clearRect(0, 0, width, height);

    for (const p of particles) {
      const weight = edgeWeight(p.x, p.y);

      if (!reduced && weight > 0.01) {
        const dx = p.x - pointer.x;
        const dy = p.y - pointer.y;
        const squared = dx * dx + dy * dy + 40;
        const force = (REPEL * weight) / squared;
        const length = Math.hypot(dx, dy) || 1;
        p.vx += (dx / length) * force * 0.016;
        p.vy += (dy / length) * force * 0.016;
      }

      p.vx *= 0.97;
      p.vy *= 0.97;
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0) p.x += width;
      if (p.x > width) p.x -= width;
      if (p.y < 0) p.y += height;
      if (p.y > height) p.y -= height;

      context.beginPath();
      context.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      context.fillStyle = `rgba(140,170,220,${0.18 + weight * 0.35})`;
      context.fill();
    }

    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j];
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        if (distance > LINK_DISTANCE) continue;
        const weight = Math.max(edgeWeight(a.x, a.y), edgeWeight(b.x, b.y));
        context.beginPath();
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
        context.strokeStyle =
          `rgba(120,160,215,${(1 - distance / LINK_DISTANCE) * 0.16 * (0.3 + weight)})`;
        context.stroke();
      }
    }

    frame = requestAnimationFrame(step);
  };

  const onPointer = (event) => { pointer.x = event.clientX; pointer.y = event.clientY; };
  const onLeave = () => { pointer.x = -1e6; pointer.y = -1e6; };

  addEventListener('resize', () => { resize(); seed(); });
  addEventListener('pointermove', onPointer, { passive: true });
  addEventListener('pointerleave', onLeave);

  resize();
  seed();
  step();

  return {
    stop() {
      running = false;
      cancelAnimationFrame(frame);
      removeEventListener('pointermove', onPointer);
      removeEventListener('pointerleave', onLeave);
    },
  };
}

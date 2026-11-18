/* Marid: the orange genie of the assistant.
   He lives in the top bar, flies around the screen once a minute (the first time 5 seconds after the page opens), lands back
   in his place and greets the person. Rules that keep him friendly:
   - he never takes clicks while flying (pointer-events: none), so nothing is ever covered or blocked;
   - he does not fly while someone types, while a dialog is open, while the tab is hidden, or for anyone who asked for less
     motion; a person can send him to sleep from his speech bubble (remembered in this browser);
   - the minute is kept across pages: moving between pages does not make him fly again. */
(() => {
  'use strict';
  const root = document.getElementById('marid');
  const bubble = document.getElementById('marid-bubble');
  const dataEl = document.getElementById('marid-data');
  const layer = document.getElementById('marid-layer');
  if (!root || !bubble || !dataEl) return;

  const T = JSON.parse(dataEl.textContent);
  const OFF_KEY = 'wk-marid-off', LAST_KEY = 'wk-marid-last', GREETED_KEY = 'wk-marid-greeted';
  const FIRST_DELAY = 5000, EVERY = 60000, W = 64, H = 70, HOME_SCALE = 0.62;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const line = bubble.querySelector('.marid-line');
  const toggle = bubble.querySelector('.marid-switch');
  const openBar = bubble.querySelector('.marid-bar');
  const slot = document.querySelector('[data-marid-home]');
  const store = {
    get: (area, key) => { try { return area.getItem(key); } catch (e) { return null; } },
    set: (area, key, value) => { try { area.setItem(key, value); } catch (e) { /* private mode */ } },
  };

  let off = store.get(localStorage, OFF_KEY) === '1';
  let busy = false, lastLine = -1, bubbleTimer = 0, anim = null, sparkTimer = 0, track = [];

  const rnd = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const pose = (c, sx, sy, rot) => `translate(${c.x - W / 2}px, ${c.y - H / 2}px) rotate(${rot || 0}deg) scale(${sx}, ${sy === undefined ? sx : sy})`;

  /* where he settles: the slot in the command bar. On a phone the bar is hidden and he only visits the top of the screen. */
  const homePoint = () => {
    if (!slot || !slot.offsetParent) return null;
    const r = slot.getBoundingClientRect();
    if (r.width < 30) return null;                              // squeezed out by the buttons: he only visits
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 + 2 };
  };

  const setAsleep = () => root.classList.toggle('is-asleep', off);

  const rest = () => {
    const home = homePoint();
    setAsleep();
    if (!home) { root.dataset.state = 'hidden'; return; }
    root.style.transform = pose(home, HOME_SCALE);
    root.dataset.state = 'home';
  };

  /* ── the speech bubble ─────────────────────────────────────────────────────────────────────────────────── */
  const placeBubble = (point) => {
    const vw = window.innerWidth;
    bubble.style.left = '0px'; bubble.style.top = '0px';
    const b = bubble.getBoundingClientRect();
    bubble.style.left = clamp(point.x - b.width / 2, 8, vw - b.width - 8) + 'px';
    bubble.style.top = (point.y + 30) + 'px';
  };

  const say = (text, point, withSwitch, ms) => {
    window.clearTimeout(bubbleTimer);
    line.textContent = text;
    toggle.hidden = !withSwitch;
    openBar.hidden = !(withSwitch && window.innerWidth <= 700);      // on a phone there is no bar to click: he offers it
    toggle.textContent = off ? T.wake : T.stop;
    bubble.classList.remove('is-in');                          // measured at its real size, not mid-animation
    bubble.hidden = false;
    placeBubble(point);
    void bubble.offsetWidth; bubble.classList.add('is-in');
    if (ms) bubbleTimer = window.setTimeout(hideBubble, ms);
  };
  const hideBubble = () => { window.clearTimeout(bubbleTimer); bubble.hidden = true; };

  const nextLine = () => {
    let i;
    do { i = Math.floor(Math.random() * T.lines.length); } while (T.lines.length > 1 && i === lastLine);
    lastLine = i;
    return T.lines[i];
  };
  const greeting = () => (T.name ? T.greeting.replace('%(name)s', T.name) : nextLine());

  /* ── the flight ───────────────────────────────────────────────────────────────────────────────────────── */
  const spline = (p0, p1, p2, p3, t) => {
    const t2 = t * t, t3 = t2 * t;
    const f = (a, b, c, d) => 0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
    return { x: f(p0.x, p1.x, p2.x, p3.x), y: f(p0.y, p1.y, p2.y, p3.y) };
  };

  const waypoints = (start, end) => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const pts = [start];
    const stops = 4 + Math.floor(Math.random() * 2);
    for (let i = 0; i < stops; i++) pts.push({ x: rnd(70, vw - 70), y: rnd(100, vh - 90) });
    const edge = Math.random() < 0.5 ? 26 : vw - 26;            // he bumps into the side of the screen and bounces back
    pts.splice(2, 0, { x: edge, y: rnd(140, vh - 140) });
    pts.push({ x: clamp(end.x + rnd(-60, 60), 60, vw - 60), y: end.y + 150 });
    pts.push(end);
    return pts;
  };

  const frames = (pts) => {
    const N = 170, out = [], centers = [];
    const segs = pts.length - 1;
    let prev = null;
    for (let i = 0; i < N; i++) {
      const u = i / (N - 1);
      const e = 0.5 - 0.5 * Math.cos(Math.PI * u);              // slow take-off and landing
      const s = e * segs, k = Math.min(segs - 1, Math.floor(s));
      const c = spline(pts[Math.max(0, k - 1)], pts[k], pts[k + 1], pts[Math.min(segs, k + 2)], s - k);
      c.y += Math.sin(u * 40) * 7;                                // a happy bob
      if (u > 0.40 && u < 0.52) {                                 // a loop-the-loop
        const a = ((u - 0.40) / 0.12) * Math.PI * 2;
        c.x += 46 * (Math.cos(a) - 1); c.y += 46 * Math.sin(a);
      }
      let rot = prev ? clamp((c.x - prev.x) * 2.2, -24, 24) : 0;  // leans into the direction he flies
      if (u > 0.86 && u < 0.95) rot += ((u - 0.86) / 0.09) * 720; // a dizzy spin before landing
      const size = HOME_SCALE + (1.5 - HOME_SCALE) * Math.min(smooth(0, 0.07, u), 1 - smooth(0.93, 1, u));
      const jelly = 0.08 * Math.sin(u * 56);
      out.push({ transform: pose(c, size * (1 + jelly), size * (1 - jelly), rot), offset: u });
      centers.push(c);
      prev = c;
    }
    return { out, centers };
  };

  const spark = (c) => {
    const el = document.createElement('span');
    el.className = 'md-spark';
    el.textContent = Math.random() < 0.5 ? '✦' : '✧';
    el.style.left = (c.x + rnd(-10, 10)) + 'px';
    el.style.top = (c.y + rnd(14, 26)) + 'px';
    el.addEventListener('animationend', () => el.remove());
    (layer || document.body).appendChild(el);
  };

  const finish = (landing, visitor) => {
    window.clearInterval(sparkTimer);
    if (anim) { anim.cancel(); anim = null; }
    root.classList.remove('is-flying');
    if (visitor) {
      root.style.transform = pose(landing, 1.3);
      root.dataset.state = 'fly';
    } else {
      root.style.transform = pose(landing, HOME_SCALE);
      root.dataset.state = 'home';
      root.animate([{ transform: pose(landing, HOME_SCALE * 1.18, HOME_SCALE * 0.78) },
                    { transform: pose(landing, HOME_SCALE * 0.92, HOME_SCALE * 1.12), offset: 0.55 },
                    { transform: pose(landing, HOME_SCALE) }], { duration: 520, easing: 'ease-out' });
    }
    root.classList.add('is-waving');
    window.setTimeout(() => root.classList.remove('is-waving'), 3000);
    const first = store.get(sessionStorage, GREETED_KEY) !== '1';
    store.set(sessionStorage, GREETED_KEY, '1');
    say(first ? greeting() : nextLine(), landing, false, 5200);
    if (visitor) window.setTimeout(() => { root.dataset.state = 'hidden'; busy = false; }, 5600);
    else busy = false;
  };

  const fly = () => {
    if (busy) return;
    const home = homePoint();
    const vw = window.innerWidth;
    const visitor = !home;
    const start = home || { x: vw + 40, y: rnd(160, 320) };
    const end = home || { x: vw / 2, y: 86 };
    busy = true;
    hideBubble();
    store.set(localStorage, LAST_KEY, String(Date.now()));
    const { out, centers } = frames(waypoints(start, end));
    root.dataset.state = 'fly';
    root.classList.add('is-flying');
    const duration = rnd(9500, 11500);
    anim = root.animate(out, { duration, easing: 'linear', fill: 'forwards' });
    track = centers;
    sparkTimer = window.setInterval(() => {
      if (!anim || document.hidden) return;
      const i = clamp(Math.floor((anim.currentTime / duration) * (track.length - 1)), 0, track.length - 1);
      spark(track[i]);
    }, 110);
    anim.onfinish = () => finish(end, visitor);
    anim.oncancel = () => { window.clearInterval(sparkTimer); busy = false; };
  };

  /* may he fly now? */
  const canFly = () => {
    if (off || reduce.matches || busy || document.hidden) return false;
    const a = document.activeElement;
    if (a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable)) return false;
    return !document.querySelector('dialog[open], .modal.show');
  };

  let retries = 0;
  const attempt = () => {
    if (canFly()) { retries = 0; fly(); return; }
    if (off || reduce.matches) return;
    if (retries++ < 6) window.setTimeout(attempt, 8000);       // try again shortly, then give up until the next minute
    else retries = 0;
  };

  /* ── clicking him ─────────────────────────────────────────────────────────────────────────────────────── */
  root.addEventListener('click', () => {
    if (busy || root.dataset.state !== 'home') return;
    const home = homePoint();
    if (!home) return;
    if (!bubble.hidden) { hideBubble(); return; }
    say(off ? T.asleep : nextLine(), home, true, 9000);
    if (!off && !reduce.matches) { root.classList.add('is-waving'); window.setTimeout(() => root.classList.remove('is-waving'), 3000); }
  });
  openBar.addEventListener('click', () => {
    hideBubble();
    const trigger = document.querySelector('[data-marid-open]');
    if (trigger) trigger.click();
  });
  toggle.addEventListener('click', () => {
    off = !off;
    store.set(localStorage, OFF_KEY, off ? '1' : '0');
    hideBubble();
    rest();
    if (!off) window.setTimeout(attempt, 1200);
  });
  document.addEventListener('click', (ev) => {
    if (!bubble.hidden && !bubble.contains(ev.target) && !root.contains(ev.target)) hideBubble();
  });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') hideBubble(); });
  window.addEventListener('resize', () => { if (!busy) { rest(); hideBubble(); } });

  /* ── the minute ───────────────────────────────────────────────────────────────────────────────────────── */
  rest();
  if (root.dataset.state === 'hidden' && !slot) return;
  const last = Number(store.get(localStorage, LAST_KEY)) || 0;
  const wait = last ? clamp(EVERY - (Date.now() - last), FIRST_DELAY, EVERY) : FIRST_DELAY;
  window.setTimeout(() => { attempt(); window.setInterval(attempt, EVERY); }, wait);
})();

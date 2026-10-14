// Shared helpers. All dynamic text goes through textContent (never innerHTML) so
// device names and captions cannot inject markup.
// Native append()/replaceChildren() print the text "null" for null children;
// make them skip null/undefined/false so conditional UI pieces can be written inline.
for (const name of ['append', 'prepend', 'replaceChildren']) {
  const orig = Element.prototype[name];
  Element.prototype[name] = function (...kids) { return orig.apply(this, kids.flat().filter((k) => k != null && k !== false)); };
}
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'value') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: { 'X-Requested-With': 'crewline' }, credentials: 'same-origin' };
  if (opts.body !== undefined) { o.method = opts.method || 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  if (opts.pin) o.headers['X-Viewer-Pin'] = opts.pin;
  let r;
  try { r = await fetch(path, o); } catch (e) { return { ok: false, status: 0, data: { error: 'cannot reach the appliance' } }; }
  let data = null;
  try { data = await r.json(); } catch (e) { data = {}; }
  return { ok: r.ok, status: r.status, data };
}

// Server-sent events with automatic reconnect; onStatus(true/false) reports the link.
function sse(url, onEvent, onStatus) {
  let es, delay = 500, stopped = false;
  const open = () => {
    if (stopped) return;
    es = new EventSource(url);
    es.onopen = () => { delay = 500; onStatus && onStatus(true); };
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { /* ignore malformed */ } };
    es.onerror = () => { onStatus && onStatus(false); es.close(); setTimeout(open, delay); delay = Math.min(delay * 2, 8000); };
  };
  open();
  return () => { stopped = true; es && es.close(); };
}

function ago(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return s + ' s ago';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  return Math.floor(s / 3600) + ' h ago';
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function groupClass(groups, id) { const i = groups.findIndex((g) => g.id === id); return 'g' + (i < 0 ? 0 : i % 6); }
function groupName(groups, id) { const g = groups.find((x) => x.id === id); return g ? g.name : id; }

// A short beep for browser alerts (user opts in; needs a prior gesture).
let _ac;
function beep(freq = 880, ms = 160) {
  try {
    _ac = _ac || new (window.AudioContext || window.webkitAudioContext)();
    const o = _ac.createOscillator(), g = _ac.createGain();
    o.frequency.value = freq; g.gain.value = 0.15; o.connect(g); g.connect(_ac.destination);
    o.start(); o.stop(_ac.currentTime + ms / 1000);
  } catch (e) { /* no audio available */ }
}

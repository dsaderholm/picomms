'use strict';
let S = null, pin = sessionStorage.getItem('pin') || '';
let engineOk = true, linkOk = true;
const caps = new Map();          // key -> caption event
let capFilter = '', capMentions = false, lastAlertIds = new Set();
const opt = { sound: false };

async function load() {
  const r = await api('/api/public/state', { pin });
  if (r.status === 401 && r.data.pin) return askPin();
  if (r.status === 503) { engineOk = false; render(); return; }
  engineOk = true; S = r.data; render();
}
function askPin() {
  const d = $('#pin'); d.showModal();
  d.addEventListener('close', () => { pin = $('#pin-in').value.trim(); sessionStorage.setItem('pin', pin); load(); loadCaps(); }, { once: true });
}
async function loadCaps() {
  const r = await api('/api/public/captions', { pin });
  if (r.ok) for (const c of r.data) caps.set(c.endpoint + ':' + c.seg, c);
  renderCaps();
}

function stateText(e) {
  if (!e.enabled) return 'Disabled by an administrator';
  if (!e.connected) return 'Not connected';
  if (!e.audio_up) return 'Connected — no voice link yet';
  return 'Online';
}
function render() {
  if (!S) return;
  $('#sim').classList.toggle('hidden', !S.simulated);
  $('#off').classList.toggle('hidden', engineOk && linkOk);
  const sm = $('#c-show');
  sm.textContent = S.show_mode ? 'Show mode: configuration locked' : 'Show mode off';
  sm.className = 'chip ' + (S.show_mode ? 'ok' : 'warn');
  const cp = $('#c-cap');
  const c = S.captions || {};
  cp.textContent = !c.enabled ? 'Captions not configured' : c.connected ? 'Captions live' : 'Captions unavailable';
  cp.className = 'chip ' + (!c.enabled ? '' : c.connected ? 'ok' : 'warn');
  renderAlerts(); renderCrew(); renderFilter();
}
function renderAlerts() {
  const box = $('#alerts'); box.replaceChildren();
  const ids = new Set();
  for (const a of S.attention) {
    ids.add(a.id);
    const who = (S.endpoints.find((e) => e.id === a.source) || {}).name || a.source;
    const tgt = (S.endpoints.find((e) => e.id === a.target) || {}).name || 'Sound';
    box.append(h('div', { class: 'alert', role: 'alert' },
      h('div', { class: 'who' }, `CALLING ${tgt.toUpperCase()} — ${who}`, h('small', {}, `${ago(a.created)} · via ${a.via}`)),
      h('button', { onclick: () => ack(a.id) }, 'Acknowledge')));
  }
  if ([...ids].some((i) => !lastAlertIds.has(i))) {
    if (opt.sound) { beep(880, 140); setTimeout(() => beep(1175, 220), 200); }
    if (navigator.vibrate && navigator.userActivation && navigator.userActivation.hasBeenActive) navigator.vibrate([200, 100, 200]);
  }
  lastAlertIds = ids;
  document.title = (ids.size ? '(!) ' : '') + 'Crewline Crew Dashboard';
}
async function ack(id) { await api('/api/public/attention/ack', { body: { id } }); load(); }

function renderCrew() {
  const crew = $('#crew'); crew.replaceChildren();
  for (const e of S.endpoints) {
    const online = e.enabled && e.connected && e.audio_up;
    const card = h('div', { class: 'card' + (e.speaking ? ' speaking' : '') + (online ? '' : ' off'), dataset: { id: e.id } },
      h('div', { class: 'name' }, h('span', { class: 'dot ' + (online ? 'ok' : e.connected ? 'warn' : 'bad') }), e.name),
      h('div', { class: 'state' }, stateText(e)),
      h('div', {}, ...e.talk.map((g) => h('span', { class: 'gchip ' + groupClass(S.groups, g), title: 'talking to' }, '🎤 ' + groupName(S.groups, g))),
        ...e.listen.filter((g) => !e.talk.includes(g)).map((g) => h('span', { class: 'gchip ' + groupClass(S.groups, g), style: 'opacity:.55', title: 'listening to' }, '🎧 ' + groupName(S.groups, g)))),
      h('div', { class: 'tags' },
        e.allcall && h('span', { class: 'tag all' }, 'ALL-CALL'),
        e.forced_mute ? h('span', { class: 'tag bad' }, 'MUTED BY ADMIN') : e.muted && h('span', { class: 'tag mute' }, 'MUTED'),
        online && e.transmitting && !e.muted && h('span', { class: 'tag tx' }, e.talk_mode === 'open' ? 'MIC OPEN' : 'TALKING'),
        online && !e.transmitting && !e.muted && h('span', { class: 'tag' }, e.talk_mode === 'ptt' ? 'PUSH-TO-TALK' : e.talk_mode === 'latched' ? 'TAP TO TALK' : 'MIC OFF')),
      h('div', { class: 'meter' }, h('i', { style: `width:${levelPct(e.level_db)}%` })));
    crew.append(card);
  }
  $('#crew-note').textContent = 'Speaking indicators come straight from each microphone and do not depend on captions.';
}
function levelPct(db) { return Math.max(0, Math.min(100, ((db + 70) / 55) * 100)); }
function renderFilter() {
  const sel = $('#cap-filter'); const cur = sel.value;
  if (sel.options.length === S.groups.length + 1) return;
  sel.replaceChildren(h('option', { value: '' }, 'All groups'), ...S.groups.map((g) => h('option', { value: g.id }, g.name)));
  sel.value = cur;
}

function renderCaps() {
  const box = $('#caps');
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const list = [...caps.values()].sort((a, b) => a.t - b.t).slice(-80);
  box.replaceChildren();
  for (const c of list) {
    if (capFilter && !String(c.group || '').split(',').includes(capFilter)) continue;
    if (capMentions && !c.mention) continue;
    const gid = String(c.group || '').split(',')[0];
    const gname = (S ? S.groups : []).filter((g) => String(c.group || '').split(',').includes(g.id)).map((g) => g.name).join(', ');
    box.append(h('div', { class: 'cap' + (c.final ? '' : ' interim') + (c.mention ? ' mention' : ''), style: `border-left-color:var(--${S ? groupClass(S.groups, gid).replace('g', 'g') : 'g0'})` },
      h('div', { class: 'who ' + (S ? groupClass(S.groups, gid) : 'g0') }, c.name || c.endpoint, gname ? ` → ${gname}` : '', h('span', { class: 't' }, new Date(c.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }))),
      h('div', { class: 'txt' }, c.text)));
  }
  if (atBottom) box.scrollTop = box.scrollHeight; else $('#cap-latest').classList.remove('hidden');
  if (!list.length) box.append(h('p', { class: 'muted' }, S && S.captions && S.captions.enabled ? 'Waiting for speech…' : 'Captions are not configured. Audio is unaffected.'));
}

function onEvent(ev) {
  switch (ev.type) {
    case 'speaking': {
      if (!S) return;
      const e = S.endpoints.find((x) => x.id === ev.endpoint);
      if (e) { e.speaking = ev.speaking; if (ev.transmitting !== undefined) e.transmitting = ev.transmitting; renderCrew(); }
      break;
    }
    case 'caption': caps.set(ev.endpoint + ':' + ev.seg, ev); renderCaps(); break;
    case 'engine': engineOk = ev.ok; render(); if (ev.ok) load(); break;
    default: loadSoon();
  }
}
const loadSoon = debounce(load, 150);

$('#cap-filter').addEventListener('change', (e) => { capFilter = e.target.value; renderCaps(); });
$('#cap-mentions').addEventListener('change', (e) => { capMentions = e.target.checked; renderCaps(); });
let size = parseFloat(localStorage.getItem('capsize') || '1.1');
const applySize = () => { $('#caps').style.setProperty('--cap-size', size + 'rem'); localStorage.setItem('capsize', size); };
$('#cap-bigger').onclick = () => { size = Math.min(2.6, size + .15); applySize(); };
$('#cap-smaller').onclick = () => { size = Math.max(.8, size - .15); applySize(); };
$('#cap-latest').onclick = () => { const b = $('#caps'); b.scrollTop = b.scrollHeight; $('#cap-latest').classList.add('hidden'); };
$('#caps').addEventListener('scroll', () => { const b = $('#caps'); if (b.scrollHeight - b.scrollTop - b.clientHeight < 60) $('#cap-latest').classList.add('hidden'); });
$('#opt-sound').addEventListener('change', (e) => { opt.sound = e.target.checked; if (opt.sound) beep(660, 80); });
let wake = null;
if (!navigator.wakeLock) {           // only exists on HTTPS / localhost pages
  $('#opt-awake').parentElement.classList.add('hidden');   // needs HTTPS; see docs/06-operations.md
}
$('#opt-awake').addEventListener('change', async (e) => {
  try { if (e.target.checked && navigator.wakeLock) wake = await navigator.wakeLock.request('screen'); else if (wake) { await wake.release(); wake = null; } }
  catch (err) { e.target.checked = false; }
});
applySize();
setInterval(() => { if (S && S.attention.length) renderAlerts(); }, 5000);   // refresh "x s ago"
load().then(loadCaps);
sse('/api/public/events' + (pin ? '?pin=' + encodeURIComponent(pin) : ''), onEvent, (ok) => { linkOk = ok; render(); });

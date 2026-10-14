'use strict';
const token = location.pathname.split('/').pop();
const base = `/api/r/${encodeURIComponent(token)}`;
let S = null, busy = false, linkOk = true, engineOk = true, sentTimer = null;
const caps = new Map();

async function load() {
  const r = await api(base + '/state');
  if (r.status === 404) { document.body.replaceChildren(h('main', { class: 'wrap' }, h('h1', {}, 'This link is no longer valid'), h('p', {}, 'Ask the crew lead for a new one.'))); return; }
  if (r.status === 503) { engineOk = false; render(); return; }
  engineOk = true; S = r.data; render();
}
async function loadCaps() { const r = await api(base + '/captions'); if (r.ok) for (const c of r.data) caps.set(c.endpoint + ':' + c.seg, c); renderCaps(); }

async function act(action) {
  const r = await api(base + '/do', { body: { action } });
  if (!r.data.ok && r.data.reason) flash(r.data.reason);
  else if (!r.ok && r.data.error) flash(r.data.error);
  load();
  return r;
}
function flash(msg) { const el = $('#status'); el.append(h('span', { class: 'chip bad' }, msg)); setTimeout(load, 2500); }

function render() {
  if (!S) return;
  const me = S.me;
  $('#sim').classList.toggle('hidden', !S.simulated);
  $('#off').classList.toggle('hidden', engineOk && linkOk);
  $('#me-name').textContent = me.name;
  const c = $('#c-conn');
  const up = me.enabled && me.connected && me.audio_up;
  c.textContent = !me.enabled ? 'disabled' : up ? 'headset online' : me.connected ? 'headset: no voice link' : 'headset not connected';
  c.className = 'chip ' + (up ? 'ok' : me.connected ? 'warn' : 'bad');

  const gname = (id) => (S.groups.find((g) => g.id === id) || {}).name || id;
  $('#status').replaceChildren(
    me.forced_mute ? h('span', { class: 'chip bad' }, 'Muted by an administrator')
      : me.muted ? h('span', { class: 'chip warn' }, 'You are MUTED') : null,
    me.allcall ? h('span', { class: 'chip bad' }, 'ALL-CALL ON') : null,
    h('span', { class: 'chip' }, me.transmitting ? 'Others can hear you' : 'Others cannot hear you right now'),
    h('span', { class: 'chip info' }, 'Talking to: ' + (me.talk.map(gname).join(', ') || 'nobody')));

  const talk = $('#talk');
  talk.className = 'big talk' + (me.transmitting && !me.muted ? ' live' : '');
  if (me.talk_mode === 'ptt') talk.textContent = 'HOLD TO TALK';
  else if (me.talk_mode === 'latched') talk.textContent = me.latched_on ? 'TALKING — tap to stop' : 'TAP TO TALK';
  else talk.textContent = me.muted ? 'MIC OPEN (muted)' : 'MIC OPEN';
  talk.disabled = me.talk_mode === 'open';          // open mic needs no talk button; use MUTE
  const mute = $('#mute');
  mute.className = 'big mute' + (me.muted ? ' on' : '');
  mute.textContent = me.muted ? 'UNMUTE' : 'MUTE';
  mute.disabled = me.forced_mute;

  const tg = $('#talkgroups'); tg.replaceChildren();
  for (const g of S.groups.filter((g) => me.talk_allowed.includes(g.id)))
    tg.append(h('button', { class: 'gbtn' + (me.talk.includes(g.id) ? ' sel' : ''), disabled: !me.can_select, onclick: () => act('select:' + g.id) }, g.name));
  const lg = $('#listengroups'); lg.replaceChildren();
  for (const g of S.groups.filter((g) => me.listen_allowed.includes(g.id)))
    lg.append(h('button', { class: 'gbtn' + (me.listen.includes(g.id) ? ' lis' : ''), disabled: !me.can_select, onclick: () => act('listen:' + g.id) }, g.name));
  if (!me.can_select) $('#groups-panel h2').textContent = 'Groups (set by your crew lead)';
  $('#allcall-row').classList.toggle('hidden', !me.can_allcall);
  const ac = $('#allcall'); ac.className = 'big all' + (me.allcall ? ' on' : ''); ac.textContent = me.allcall ? 'END ALL-CALL' : 'ALL-CALL (everyone hears you)';

  const mine = S.attention.find((a) => a.source === me.id);
  $('#alerts').replaceChildren(...S.attention.filter((a) => a.source !== me.id).map((a) =>
    h('div', { class: 'alert' }, `Calling Sound: ${(S.endpoints.find((e) => e.id === a.source) || {}).name || a.source}`)));
  const call = $('#call');
  call.classList.toggle('sent', !!mine);
  call.textContent = mine ? '✓ Sound has been alerted — tap again only if urgent' : 'CALL SOUND';

  renderCheat();
}

function renderCheat() {
  const c = S.cheatsheet, tb = $('#cheat-table tbody');
  $('#cheat-note').textContent = c.note;
  tb.replaceChildren();
  for (const r of c.mapped)
    tb.append(h('tr', {}, h('td', {}, r.button), h('td', {}, r.does), h('td', { class: r.verified ? 'tick' : 'muted small' }, r.verified ? '✓ confirmed' : 'not yet confirmed')));
  if (!c.mapped.length) tb.append(h('tr', {}, h('td', { colspan: 3, class: 'muted' }, 'No headset buttons are set up for you. Use the buttons on this page.')));
  $('#cheat-extra').replaceChildren(
    ...c.local_only.map((t) => h('p', { class: 'small' }, '🔇 ' + t)),
    ...(c.unmapped_seen.length ? [h('p', { class: 'small muted' }, 'Other buttons the system has seen from your headset (no action assigned): ' + c.unmapped_seen.map((u) => u.button).join(', '))] : []));
  const dial = $('#dial');
  if (S.me.dial_codes && S.me.dial_codes.length) {
    dial.classList.remove('hidden');
    $('#dial tbody').replaceChildren(...S.me.dial_codes.map((d) => h('tr', {}, h('td', {}, h('b', {}, (S.me.dial_prefix || '') + d.digit)), h('td', {}, d.does))));
  }
}

function renderCaps() {
  const box = $('#caps'); box.replaceChildren();
  const list = [...caps.values()].sort((a, b) => a.t - b.t).slice(-6);
  for (const c of list) box.append(h('div', { class: 'cap' + (c.mention ? ' mention' : '') }, h('div', { class: 'who' }, c.name || c.endpoint), h('div', {}, c.text)));
  if (!list.length) box.append(h('p', { class: 'muted small' }, 'No captions yet.'));
}

// ---- controls ----------------------------------------------------------------------
const talk = $('#talk');
let pttHeld = false;
const pttDown = (e) => { if (!S || S.me.talk_mode !== 'ptt') return; e.preventDefault(); if (pttHeld) return; pttHeld = true; talk.setPointerCapture && e.pointerId != null && talk.setPointerCapture(e.pointerId); act('ptt:down'); };
const pttUp = (e) => { if (!pttHeld) return; pttHeld = false; act('ptt:up'); };
talk.addEventListener('pointerdown', pttDown);
talk.addEventListener('pointerup', pttUp);
talk.addEventListener('pointercancel', pttUp);
talk.addEventListener('contextmenu', (e) => e.preventDefault());
talk.addEventListener('click', () => { if (S && S.me.talk_mode === 'latched') act('talk:toggle'); });
$('#mute').addEventListener('click', () => act('mute:toggle'));
$('#call').addEventListener('click', async () => {
  const r = await act('attention');
  if (r.data && r.data.ok && navigator.vibrate) navigator.vibrate(60);   // allowed: user just tapped
});
$('#allcall').addEventListener('click', () => {
  if (S.me.allcall || confirm('Everyone will hear you. Start an all-call?')) act('allcall:toggle');
});
// If the page is hidden or loses focus while holding push-to-talk, release it.
document.addEventListener('visibilitychange', () => { if (document.hidden && pttHeld) pttUp(); });
window.addEventListener('blur', () => { if (pttHeld) pttUp(); });

const loadSoon = debounce(load, 120);
sse(base + '/events', (ev) => {
  if (ev.type === 'caption') { caps.set(ev.endpoint + ':' + ev.seg, ev); renderCaps(); }
  else if (ev.type === 'engine') { engineOk = ev.ok; render(); if (ev.ok) load(); }
  else if (ev.type !== 'speaking') loadSoon();
}, (ok) => { linkOk = ok; render(); });
load().then(loadCaps);

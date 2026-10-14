'use strict';
let S = null, tab = sessionStorage.getItem('admintab') || 'status', engineOk = true;
const TABS = [['status', 'Status'], ['devices', 'Devices & pairing'], ['endpoints', 'Endpoints'], ['groups', 'Groups'],
  ['controls', 'Dial codes & controls'], ['captions', 'Captions'], ['diag', 'Diagnostics'], ['backup', 'Backup & restore']];
const ACTIONS = (groups) => [
  ['mute:toggle', 'Mute / unmute'], ['talk:toggle', 'Latched talk on/off'], ['ptt', 'Push-to-talk (hold)'],
  ['attention', 'Call Sound'], ['allcall:toggle', 'All-call on/off'], ['status', 'Play status beep'],
  ...groups.map((g) => ['select:' + g.id, 'Talk to ' + g.name]), ...groups.map((g) => ['listen:' + g.id, 'Listen to ' + g.name + ' on/off'])];
const EVENTS = [['vol_up', 'Volume up'], ['vol_down', 'Volume down'], ['call_button', 'Call / multi-function button'], ['redial', 'Double press (redial)'],
  ['voice_assist', 'Voice-assistant button'], ['play_pause', 'Play/pause key'], ['next', 'Next track'], ['prev', 'Previous track'], ['hangup', 'End call'], ['answer', 'Answer']];

// ---- plumbing ---------------------------------------------------------------------
async function admin(path, body, method) {
  const r = await api('/api/admin' + path, body === undefined ? { method: method || 'GET' } : { body, method: method || 'POST' });
  if (r.status === 401) { showLogin(); }
  if (r.status === 503) { engineOk = false; chrome(); }
  return r;
}
function toast(msg, bad) {
  const t = h('div', { class: 'chip ' + (bad ? 'bad' : 'ok'), style: 'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:50;font-size:1rem;padding:8px 16px;max-width:90vw;white-space:normal' }, msg);
  document.body.append(t); setTimeout(() => t.remove(), bad ? 6000 : 2500);
}
async function change(path, body, okmsg) {
  const r = await admin(path, body);
  if (r.data && r.data.ok === false || !r.ok) toast((r.data && (r.data.error || r.data.message)) || 'failed', true);
  else if (okmsg) toast(okmsg);
  await refresh();
  return r;
}
function dlg(title, ...body) {
  const d = $('#dlg'); $('#dlg-body').replaceChildren(h('h2', {}, title), ...body);
  if (!d.open) d.showModal(); return d;
}
const closeDlg = () => $('#dlg').close();
const locked = () => S && S.show_mode;
const lockNote = () => locked() ? h('div', { class: 'lock' }, '🔒 Show mode is on: configuration is locked. Talk, mute and group-selection controls still work for everyone. Turn show mode off (top bar) to change settings.') : null;

// ---- login --------------------------------------------------------------------------
function showLogin() { $('#login-view').classList.remove('hidden'); $('#app').classList.add('hidden'); $('#logout').classList.add('hidden'); }
$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await api('/api/login', { body: { password: $('#pw').value } });
  if (r.ok) { $('#pw').value = ''; $('#login-err').textContent = ''; start(); } else $('#login-err').textContent = r.data.error || 'login failed';
});
$('#logout').addEventListener('click', async () => { await api('/api/logout', { body: {} }); showLogin(); });

// ---- chrome ----------------------------------------------------------------------------
function chrome() {
  $('#sim').classList.toggle('hidden', !(S && S.simulated));
  $('#off').classList.toggle('hidden', engineOk);
  const c = $('#c-show');
  if (!S) return;
  c.textContent = S.show_mode ? '🔒 Show mode ON' : 'Show mode off'; c.className = 'chip ' + (S.show_mode ? 'ok' : 'warn');
  $('#show-toggle').textContent = S.show_mode ? 'Unlock configuration' : 'Lock configuration (show mode)';
}
$('#show-toggle').addEventListener('click', async () => {
  if (S.show_mode) { if (!confirm('Unlock configuration? Pairing and routing changes become possible.')) return; }
  await change('/config/show_mode', { on: !S.show_mode }, S.show_mode ? 'Configuration unlocked' : 'Show mode on: configuration locked');
});

function renderTabs() {
  $('#tabs').replaceChildren(...TABS.map(([id, label]) => h('button', { role: 'tab', 'aria-selected': id === tab ? 'true' : 'false', onclick: () => { tab = id; sessionStorage.setItem('admintab', id); render(); } }, label)));
}

// ---- state refresh -----------------------------------------------------------------------
async function refresh() {
  const r = await admin('/state');
  if (r.status === 503) { engineOk = false; chrome(); return; }
  if (!r.ok) return;
  engineOk = true; S = r.data; chrome(); render();
}
async function start() {
  const me = await api('/api/me');
  if (!me.data.admin) return showLogin();
  $('#login-view').classList.add('hidden'); $('#app').classList.remove('hidden'); $('#logout').classList.remove('hidden');
  await refresh();
  sse('/api/public/events', (ev) => { if (['state', 'config', 'attention', 'attention_ack', 'engine'].includes(ev.type)) refreshSoon(); }, () => {});
}
const refreshSoon = debounce(() => { if (!dlgOpen()) refresh(); }, 250);
const dlgOpen = () => $('#dlg').open;
setInterval(() => { if (S && ['status', 'devices', 'diag'].includes(tab) && !dlgOpen() && !document.hidden) refresh(); }, 4000);

function render() {
  renderTabs();
  const v = $('#view'); v.replaceChildren();
  if (!S) return;
  ({ status: vStatus, devices: vDevices, endpoints: vEndpoints, groups: vGroups, controls: vControls,
     captions: vCaptions, diag: vDiag, backup: vBackup })[tab](v);
}

// ---- Status ---------------------------------------------------------------------------------
async function vStatus(v) {
  v.append(h('div', { class: 'panel' }, h('div', { class: 'row', style: 'justify-content:space-between' }, h('h2', { style: 'margin:0' }, 'Pre-show readiness'), h('button', { onclick: render }, 'Run checks again')), h('div', { id: 'ready', class: 'muted' }, 'Checking…')));
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Endpoints'), epTable()));
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Bluetooth adapters'), adapterTable()));
  const r = await admin('/readiness');
  const box = $('#ready'); if (!box) return;
  box.replaceChildren(...r.data.map((c) => h('div', { class: 'check ' + c.level }, h('b', {}, ({ ok: '✓ ', warn: '! ', fail: '✗ ', info: 'i ' })[c.level] + c.name), h('span', {}, c.msg))));
  const worst = r.data.some((c) => c.level === 'fail') ? 'NOT READY — fix the red items' : r.data.some((c) => c.level === 'warn') ? 'Ready with warnings' : 'Ready';
  box.prepend(h('p', { style: 'font-weight:800;font-size:1.1rem' }, worst));
}
function epTable() {
  const rows = S.endpoints.map((e) => h('tr', {},
    h('td', {}, h('b', {}, e.name), h('div', { class: 'muted small mono' }, e.address || 'no device')),
    h('td', {}, h('span', { class: 'chip ' + (e.connected ? 'ok' : 'bad') }, e.connected ? 'connected' : 'not connected'), ' ',
      h('span', { class: 'chip ' + (e.audio_up ? 'ok' : e.connected ? 'bad' : '') }, e.audio_up ? 'two-way audio' : 'no voice session')),
    h('td', {}, e.talk.join(', ') || '—', h('div', { class: 'muted small' }, 'hears: ' + (e.listen.join(', ') || '—'))),
    h('td', {}, e.forced_mute ? 'muted by admin' : e.muted ? 'muted' : e.transmitting ? 'transmitting' : 'idle', e.allcall ? ' · ALL-CALL' : ''),
    h('td', { class: 'small' }, (e.codec || '—'), h('div', { class: 'muted' }, 'adapter ' + (e.adapter ? e.adapter.slice(-5) : 'unknown'))),
    h('td', { class: 'small' }, 'battery: ' + (e.battery == null ? 'unknown' : e.battery + '%'), h('div', {}, 'headset mute: unknown'), h('div', {}, 'signal: ' + (e.rssi == null ? 'unknown' : e.rssi + ' dBm')))));
  return h('div', { style: 'overflow-x:auto' }, h('table', {}, h('thead', {}, h('tr', {}, ...['Endpoint', 'Link', 'Talks to', 'Now', 'Codec / adapter', 'Reported by headset'].map((t) => h('th', {}, t)))), h('tbody', {}, rows)));
}
function adapterTable() {
  if (!S.adapters.length) return h('p', { class: 'muted' }, 'No Bluetooth adapters found.');
  return h('table', {}, h('thead', {}, h('tr', {}, ...['Adapter', 'Powered', 'Voice sessions now', 'Pairable'].map((t) => h('th', {}, t)))),
    h('tbody', {}, S.adapters.map((a) => h('tr', {}, h('td', { class: 'mono' }, a.address), h('td', {}, a.powered ? 'yes' : 'NO'), h('td', {}, String(a.hfp_connected)), h('td', {}, a.pairable ? 'open' : 'closed')))));
}

// ---- Devices & pairing ---------------------------------------------------------------------
function vDevices(v) {
  const open = S.pairing_open_s > 0;
  v.append(h('div', { class: 'panel' }, lockNote(), h('h2', {}, 'Pairing window'),
    h('p', { class: 'muted small' }, 'Headsets can only be paired while the window is open. It closes by itself. Put the headset in pairing mode (usually hold the power button until the light flashes), then press Pair next to it below.'),
    h('div', { class: 'row' },
      h('select', { id: 'pair-adapter', 'aria-label': 'Adapter' }, h('option', { value: '' }, 'Any adapter'), ...S.adapters.map((a) => h('option', { value: a.address }, a.address))),
      h('select', { id: 'pair-secs' }, ...[60, 120, 300].map((s) => h('option', { value: s }, s / 60 + ' min'))),
      open ? h('button', { onclick: () => change('/bt/close_pairing', {}, 'Pairing window closed') }, `Close now (${S.pairing_open_s}s left)`)
        : h('button', { class: 'primary', disabled: locked(), onclick: () => change('/bt/open_pairing', { adapter: $('#pair-adapter').value || null, seconds: +$('#pair-secs').value }, 'Pairing window open') }, 'Open pairing window'))));
  const found = S.unassigned_devices;
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Nearby / unassigned devices'),
    found.length ? h('table', {}, h('thead', {}, h('tr', {}, ...['Device', 'Profile', 'Signal', 'Status', ''].map((t) => h('th', {}, t)))), h('tbody', {}, found.map((d) =>
      h('tr', {}, h('td', {}, h('b', {}, d.name || '(no name)'), h('div', { class: 'mono muted' }, d.address)),
        h('td', {}, d.supports_hfp ? 'Hands-free headset' : d.audio_like ? 'Audio device (no microphone profile seen)' : 'Other'),
        h('td', {}, d.rssi == null ? 'unknown' : d.rssi + ' dBm'), h('td', {}, d.paired ? 'paired' : 'not paired'),
        h('td', {}, h('button', { class: 'small primary', disabled: locked() || (!d.paired && !open), onclick: () => pairDialog(d) }, d.paired ? 'Assign…' : 'Pair as…')))))) : h('p', { class: 'muted' }, open ? 'Searching… nothing found yet.' : 'Open the pairing window to search.')));
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Assigned headsets'), h('div', { style: 'overflow-x:auto' }, h('table', {}, h('thead', {}, h('tr', {}, ...['Endpoint', 'Device', 'State', 'Actions'].map((t) => h('th', {}, t)))),
    h('tbody', {}, S.endpoints.filter((e) => e.address).map((e) => h('tr', {}, h('td', {}, h('b', {}, e.name)), h('td', { class: 'mono' }, e.address),
      h('td', {}, e.connected ? 'connected' : 'not connected'),
      h('td', { class: 'row' }, h('button', { class: 'small', onclick: () => change('/bt/connect', { address: e.address }, 'Reconnect requested') }, 'Reconnect'),
        h('button', { class: 'small', disabled: locked(), onclick: () => change('/bt/disconnect', { address: e.address }, 'Disconnected') }, 'Disconnect'),
        h('button', { class: 'small danger', disabled: locked(), onclick: () => confirm(`Forget ${e.name}? It will need to be paired again.`) && change('/bt/forget', { address: e.address }, 'Forgotten') }, 'Forget')))))))));
}
function pairDialog(d) {
  const existing = S.endpoints.filter((e) => !e.address);
  const nameIn = h('input', { id: 'pn', placeholder: 'e.g. Alex (Stage left)', value: d.name || '', style: 'width:100%' });
  const sel = h('select', { id: 'pe' }, h('option', { value: '' }, '— create a new endpoint —'), ...existing.map((e) => h('option', { value: e.id }, e.name)));
  dlg(d.paired ? 'Assign device' : 'Pair device', h('p', { class: 'mono' }, d.address),
    h('label', {}, 'Name of the person or role'), nameIn,
    existing.length ? h('div', { style: 'margin-top:10px' }, h('label', {}, 'Or give this device to an existing endpoint'), sel) : null,
    h('div', { class: 'row', style: 'margin-top:14px' },
      h('button', { class: 'primary', onclick: async () => {
        const body = { address: d.address }; if (sel.value) body.endpoint = sel.value; else body.new_name = nameIn.value.trim();
        if (!body.endpoint && !body.new_name) return toast('Enter a name', true);
        closeDlg(); toast('Pairing… this can take up to 30 seconds'); const r = await change('/bt/pair', body);
        toast(r.data.message || 'done', !r.data.ok);
      } }, d.paired ? 'Assign' : 'Pair'), h('button', { onclick: closeDlg }, 'Cancel')));
}

// ---- Endpoints ---------------------------------------------------------------------------------
function vEndpoints(v) {
  v.append(h('div', { class: 'panel' }, lockNote(), h('div', { class: 'row', style: 'justify-content:space-between' }, h('h2', { style: 'margin:0' }, 'Endpoints'),
    h('button', { disabled: locked(), onclick: () => editEndpoint(null) }, 'Add endpoint without a device')),
    h('p', { class: 'muted small' }, 'An endpoint is a person or role. "Home" groups are what it starts with after a restart; "allowed" is the most it can ever choose for itself.'),
    h('div', { style: 'overflow-x:auto' }, h('table', {}, h('thead', {}, h('tr', {}, ...['Name', 'Talks (home)', 'Hears (home)', 'Mode', 'Perms', ''].map((t) => h('th', {}, t)))),
      h('tbody', {}, S.endpoints.map((e) => h('tr', {}, h('td', {}, h('b', {}, e.name), h('div', { class: 'muted small' }, e.kind + (e.address ? '' : ' · no device'))),
        h('td', {}, e.home_talk.join(', ') || '—'), h('td', {}, e.home_listen.join(', ') || '—'),
        h('td', {}, { open: 'open mic', latched: 'latched talk', ptt: 'push-to-talk' }[e.talk_mode], e.forced_mute ? ' · FORCED MUTE' : '', !e.enabled ? ' · DISABLED' : ''),
        h('td', { class: 'small' }, e.can_allcall ? 'all-call · ' : '', e.can_select ? 'may switch groups' : 'fixed groups'),
        h('td', {}, h('button', { class: 'small', onclick: () => editEndpoint(e) }, 'Edit'), ' ', h('button', { class: 'small', onclick: () => remoteDialog(e) }, 'Remote link'), ' ',
          h('button', { class: 'small', onclick: () => buttonsDialog(e) }, 'Buttons')))))))));
}
function checks(name, options, selected) {
  return h('div', { class: 'checks', dataset: { name } }, ...options.map((o) => h('label', {}, h('input', { type: 'checkbox', value: o.id, checked: selected.includes(o.id) }), o.name)));
}
const picked = (name) => $$(`.checks[data-name="${name}"] input:checked`).map((i) => i.value);
function editEndpoint(e) {
  const isNew = !e;
  e = e || { id: '', name: '', kind: 'headset', address: null, enabled: true, home_listen: [], home_talk: [], listen_allowed: [], talk_allowed: [], can_allcall: false, can_select: true, select_scope: 'talk', talk_mode: 'open', forced_mute: false, tone_control: false, captions: true };
  const G = S.groups;
  const f = (label, el, hint) => h('div', {}, h('label', {}, label), el, hint ? h('div', { class: 'muted small' }, hint) : null);
  const name = h('input', { id: 'e-name', value: e.name, style: 'width:100%' });
  const mode = h('select', { id: 'e-mode' }, ...[['open', 'Open mic (always on unless muted)'], ['latched', 'Latched talk (tap to talk, tap to stop)'], ['ptt', 'Push-to-talk (hold)']].map(([v, t]) => h('option', { value: v, selected: e.talk_mode === v }, t)));
  const scope = h('select', { id: 'e-scope' }, h('option', { value: 'talk', selected: e.select_scope === 'talk' }, 'Choosing a group changes who they talk to'), h('option', { value: 'both', selected: e.select_scope === 'both' }, 'Choosing a group changes talking and listening'));
  const cb = (id, label, val) => h('label', { class: 'row', style: 'color:var(--ink);font-size:.95rem' }, h('input', { type: 'checkbox', id, checked: val }), label);
  dlg(isNew ? 'Add endpoint' : 'Edit ' + e.name, h('div', { class: 'fgrid' },
    f('Name', name), f('Kind', h('select', { id: 'e-kind' }, ...[['headset', 'Bluetooth headset'], ['rotary', 'Rotary / desk phone via Cell2Jack'], ['other', 'Other']].map(([v, t]) => h('option', { value: v, selected: e.kind === v }, t)))),
    f('Talk mode', mode, 'Whisperers: prefer latched or push-to-talk over open mic.'), f('Group selection', scope),
    f('Starts out talking to', checks('home_talk', G, e.home_talk)), f('Starts out listening to', checks('home_listen', G, e.home_listen)),
    f('May talk to (ceiling)', checks('talk_allowed', G, e.talk_allowed)), f('May listen to (ceiling)', checks('listen_allowed', G, e.listen_allowed))),
    h('div', { class: 'row', style: 'margin-top:12px;gap:18px' }, cb('e-allcall', 'May make all-calls', e.can_allcall), cb('e-select', 'May change their own groups', e.can_select),
      cb('e-tone', 'Carries dial-code tones (rotary phone)', e.tone_control), cb('e-cap', 'Send to captions', e.captions), cb('e-enabled', 'Enabled', e.enabled), cb('e-forced', 'Muted by administrator', e.forced_mute)),
    h('p', { class: 'muted small' }, '"Muted by administrator" stops this person being heard but never stops them hearing. There is deliberately no switch that silences someone\'s earpiece.'),
    h('div', { class: 'row', style: 'margin-top:14px' },
      h('button', { class: 'primary', disabled: locked(), onclick: async () => {
        const body = { id: isNew ? (name.value.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 20) || 'ep') : e.id, name: name.value.trim(), kind: $('#e-kind').value, address: e.address,
          enabled: $('#e-enabled').checked, listen: picked('home_listen'), talk: picked('home_talk'), listen_allowed: picked('listen_allowed'), talk_allowed: picked('talk_allowed'),
          can_allcall: $('#e-allcall').checked, can_select: $('#e-select').checked, select_scope: scope.value, talk_mode: mode.value, forced_mute: $('#e-forced').checked,
          tone_control: $('#e-tone').checked, captions: $('#e-cap').checked, buttons: e.buttons || {} };
        // home selection must sit inside the ceiling; widen the ceiling automatically so the form cannot contradict itself
        body.listen_allowed = [...new Set([...body.listen_allowed, ...body.listen])]; body.talk_allowed = [...new Set([...body.talk_allowed, ...body.talk])];
        const r = await change('/config/endpoint', body, 'Saved'); if (r.ok && r.data.ok !== false) closeDlg();
      } }, 'Save'), h('button', { onclick: closeDlg }, 'Cancel'),
      !isNew && h('button', { class: 'danger', disabled: locked(), style: 'margin-left:auto', onclick: async () => { if (confirm(`Delete ${e.name}?`)) { await change('/config/endpoint_delete', { id: e.id }, 'Deleted'); closeDlg(); } } }, 'Delete')));
}
async function remoteDialog(e) {
  const url = `${location.origin}/r/${e.remote_token}`;
  const qr = h('img', { class: 'qr', alt: 'QR code for the remote link', src: `/api/admin/qr/${e.remote_token}.svg` });
  qr.onerror = () => qr.replaceWith(h('p', { class: 'muted small' }, 'QR code not available (install the optional "segno" package). Copy the link instead.'));
  dlg(`Pocket remote for ${e.name}`, h('p', { class: 'small' }, 'This private link opens a phone/Chromebook page that controls ONLY this endpoint (talk, mute, groups, Call Sound). Anyone with the link can use it; rotate it if it leaks.'),
    h('input', { class: 'mono', readonly: true, value: url, style: 'width:100%', onclick: (ev) => ev.target.select() }), qr,
    h('div', { class: 'row', style: 'margin-top:12px' }, h('button', { onclick: () => { navigator.clipboard && navigator.clipboard.writeText(url); toast('Copied'); } }, 'Copy link'),
      h('a', { class: 'btn', href: url, target: '_blank', rel: 'noopener', style: 'text-decoration:none' }, 'Open'),
      h('button', { class: 'danger', onclick: async () => { if (confirm('Old link stops working. Continue?')) { await admin('/remote/rotate', { endpoint: e.id }); await refresh(); closeDlg(); remoteDialog(S.endpoints.find((x) => x.id === e.id)); } } }, 'Make a new link'),
      h('button', { onclick: closeDlg }, 'Close')));
}
async function buttonsDialog(e) {
  const r = await admin('/buttons/' + e.id);
  const info = r.data;
  const mapping = Object.assign({}, info.mappings || {});
  const seen = (info.observed || []).filter((o) => !o.event.startsWith('raw:'));
  const raw = (info.observed || []).filter((o) => o.event.startsWith('raw:'));
  const acts = ACTIONS(S.groups);
  const rows = EVENTS.map(([ev, label]) => {
    const o = seen.find((s) => s.event === ev);
    const mk = (suffix) => h('select', { dataset: { ev: ev + suffix }, disabled: !o || locked() }, h('option', { value: '' }, o ? '— native / nothing —' : 'not seen yet'), ...(o ? acts : []).map(([v, t]) => h('option', { value: v, selected: mapping[ev + suffix] === v }, t)));
    return h('tr', {}, h('td', {}, label, h('div', { class: 'small ' + (o ? 'yes' : 'muted') }, o ? `seen ${o.count}× via ${o.source}` : 'not seen from this unit')), h('td', {}, mk('')), h('td', {}, ['play_pause', 'next', 'prev', 'vol_up', 'vol_down', 'mute_key'].includes(ev) ? mk(':long') : null));
  });
  dlg(`Headset buttons — ${e.name}`,
    h('p', { class: 'small' }, 'Only buttons that have actually been seen from this headset can be assigned. Press "Learn", then press every button on the headset (also hold and double-press). Assignments are suspended while learning. A headset\'s own mute button usually works inside the headset and cannot be seen here.'),
    info.profile_hint ? h('div', { class: 'check info' }, h('span', {}, info.profile_hint.title + ' — ' + (info.profile_hint.known_local || []).join(' '))) : null,
    h('div', { class: 'row' }, h('button', { class: 'primary', disabled: !e.address, onclick: async () => { await admin('/buttons/learn', { endpoint: e.id, seconds: 30 }); toast('Learning for 30 s — press the headset buttons now'); setTimeout(() => { closeDlg(); buttonsDialog(e); }, 31000); } }, 'Learn buttons (30 s)'),
      h('button', { onclick: () => { closeDlg(); buttonsDialog(e); } }, 'Refresh'), info.learning_left_s > 0 ? h('span', { class: 'chip warn' }, `learning… ${Math.round(info.learning_left_s)}s`) : null),
    raw.length ? h('p', { class: 'small muted' }, 'Unrecognised signals seen: ' + raw.map((o) => `${o.event.slice(4)} (${o.count}×)`).join(', ')) : null,
    h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Button signal'), h('th', {}, 'Press'), h('th', {}, 'Hold (keys only)'))), h('tbody', {}, rows)),
    h('div', { class: 'row', style: 'margin-top:12px' }, h('button', { class: 'primary', disabled: locked(), onclick: async () => {
      const m = {}; $$('#dlg-body select[data-ev]').forEach((s) => { if (s.value) m[s.dataset.ev] = s.value; });
      const ep = S.endpoints.find((x) => x.id === e.id);
      const body = { id: ep.id, name: ep.name, kind: ep.kind, address: ep.address, enabled: ep.enabled, listen: ep.home_listen, talk: ep.home_talk, listen_allowed: ep.listen_allowed, talk_allowed: ep.talk_allowed, can_allcall: ep.can_allcall, can_select: ep.can_select, select_scope: ep.select_scope, talk_mode: ep.talk_mode, forced_mute: ep.forced_mute, tone_control: ep.tone_control, captions: ep.captions, buttons: m };
      const r2 = await change('/config/endpoint', body, 'Button mapping saved'); if (r2.ok && r2.data.ok !== false) closeDlg();
    } }, 'Save mapping'), h('button', { onclick: closeDlg }, 'Close')));
}

// ---- Groups ---------------------------------------------------------------------------------------
function vGroups(v) {
  v.append(h('div', { class: 'panel' }, lockNote(), h('div', { class: 'row', style: 'justify-content:space-between' }, h('h2', { style: 'margin:0' }, 'Groups'), h('button', { disabled: locked(), onclick: () => editGroup(null) }, 'Add group')),
    h('p', { class: 'muted small' }, 'The beep count is what a person hears in their own ear when they switch to that group.'),
    h('table', {}, h('thead', {}, h('tr', {}, ...['Name', 'Id', 'Beeps', ''].map((t) => h('th', {}, t)))), h('tbody', {}, S.groups.map((g) => h('tr', {}, h('td', {}, h('span', { class: 'gchip ' + groupClass(S.groups, g.id) }, g.name)), h('td', { class: 'mono' }, g.id), h('td', {}, String(g.cue_beeps)),
      h('td', {}, h('button', { class: 'small', disabled: locked(), onclick: () => editGroup(g) }, 'Edit'), ' ', h('button', { class: 'small danger', disabled: locked(), onclick: async () => { if (confirm(`Delete group ${g.name}? Endpoints lose it.`)) await change('/config/group_delete', { id: g.id }, 'Deleted'); } }, 'Delete'))))))));
}
function editGroup(g) {
  const name = h('input', { value: g ? g.name : '' }), beeps = h('input', { type: 'number', min: 1, max: 5, value: g ? g.cue_beeps : S.groups.length + 1 });
  dlg(g ? 'Edit group' : 'Add group', h('label', {}, 'Name'), name, h('label', { style: 'margin-top:10px' }, 'Beeps'), beeps,
    h('div', { class: 'row', style: 'margin-top:14px' }, h('button', { class: 'primary', onclick: async () => {
      const id = g ? g.id : name.value.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 20);
      const r = await change('/config/group', { id, name: name.value.trim(), cue_beeps: +beeps.value }, 'Saved'); if (r.ok && r.data.ok !== false) closeDlg();
    } }, 'Save'), h('button', { onclick: closeDlg }, 'Cancel')));
}

// ---- Dial codes & controls -------------------------------------------------------------------------
function vControls(v) {
  const d = S.dtmf, acts = ACTIONS(S.groups);
  const digits = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '*', '#'];
  v.append(h('div', { class: 'panel' }, lockNote(), h('h2', {}, 'Dial codes (tone commands)'),
    h('p', { class: 'muted small' }, 'These are PROPOSALS until confirmed on the real rotary phone. The Cell2Jack may use # and * for its own functions (the manual could not be checked): avoid them unless tested. While a command tone is present your microphone is held closed so the tone is not broadcast.'),
    h('div', { style: 'overflow-x:auto' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Dial'), h('th', {}, 'Does'))), h('tbody', {}, digits.map((dg) => h('tr', {}, h('td', {}, h('b', {}, dg)),
      h('td', {}, h('select', { id: 'dt-' + (dg === '*' ? 'star' : dg === '#' ? 'hash' : dg), disabled: locked() }, h('option', { value: '' }, '— nothing —'), ...acts.filter(([a]) => a !== 'ptt').map(([a, t]) => h('option', { value: a, selected: d.commands[dg] === a }, t))))))))),
    h('div', { class: 'fgrid', style: 'margin-top:12px' },
      h('div', {}, h('label', {}, 'Required prefix key (blank = single-digit commands)'), h('input', { id: 'dt-prefix', value: d.prefix, maxlength: 1, disabled: locked(), style: 'width:5em' }), h('div', { class: 'muted small' }, 'A prefix such as * makes accidental speech triggers practically impossible, at the cost of one extra key.')),
      h('div', {}, h('label', {}, 'All-call auto-ends after (seconds, 0 = never)'), h('input', { id: 'dt-ac', type: 'number', min: 0, value: d.allcall_timeout_s, disabled: locked() })),
      h('div', {}, h('label', {}, 'Minimum tone length (ms)'), h('input', { id: 'dt-min', type: 'number', min: 20, max: 200, value: d.min_tone_ms, disabled: locked() })),
      h('div', {}, h('label', {}, 'Keep mic closed after a tone (ms)'), h('input', { id: 'dt-hold', type: 'number', min: 0, max: 1000, value: d.gate_hold_ms, disabled: locked() }))),
    h('div', { class: 'row', style: 'margin-top:12px' }, h('button', { class: 'primary', disabled: locked(), onclick: async () => {
      const commands = {}; digits.forEach((dg) => { const s = $('#dt-' + (dg === '*' ? 'star' : dg === '#' ? 'hash' : dg)); if (s.value) commands[dg] = s.value; });
      await change('/config/dtmf', { commands, prefix: $('#dt-prefix').value.trim(), allcall_timeout_s: +$('#dt-ac').value, min_tone_ms: +$('#dt-min').value, gate_hold_ms: +$('#dt-hold').value }, 'Saved');
    } }, 'Save dial codes'))));
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Locking, muting and lockouts — what they mean'),
    h('ul', { class: 'small' }, h('li', {}, h('b', {}, 'Show mode (lock)'), ' freezes configuration: pairing, names, groups, permissions, button maps. Everyone can still talk, mute and change groups within their permissions.'),
      h('li', {}, h('b', {}, 'Mute'), ' stops an endpoint being heard. Self-service (headset page / dial code / button) or enforced by an administrator.'),
      h('li', {}, h('b', {}, 'Lockout'), ' of hearing does not exist on purpose. The most an administrator can do is mute someone\'s transmission or disable the endpoint (shown on the dashboard).')),
    h('p', { class: 'small' }, 'Audible cues are played into the affected person\'s earpiece only. Test them:'),
    h('div', { class: 'row' }, ...S.endpoints.filter((e) => e.address).map((e) => h('button', { class: 'small', onclick: () => admin('/test/cue/' + e.id, {}) }, 'Beep ' + e.name)))));
}

// ---- Captions ------------------------------------------------------------------------------------------------
function vCaptions(v) {
  const c = S.captions;
  v.append(h('div', { class: 'panel' }, lockNote(), h('h2', {}, 'Caption service'),
    h('p', { class: 'muted small' }, 'Speech recognition runs on a separate computer (or the same box if you accept the load). If it is down, slow or unplugged, intercom audio is not affected.'),
    h('dl', { class: 'kv' }, h('dt', {}, 'Status'), h('dd', {}, h('span', { class: 'chip ' + (!c.enabled ? '' : c.connected ? 'ok' : 'warn') }, !c.enabled ? 'not configured' : c.connected ? 'connected' : 'unreachable')),
      h('dt', {}, 'Engine'), h('dd', {}, c.engine || '—'), h('dt', {}, 'Last result time'), h('dd', {}, c.last_result_ms == null ? 'unknown' : c.last_result_ms + ' ms'),
      h('dt', {}, 'Audio dropped'), h('dd', {}, (c.dropped_kb || 0) + ' KB (while server was away or slow)'), h('dt', {}, 'Last error'), h('dd', {}, c.last_error || '—')),
    h('div', { class: 'fgrid', style: 'margin-top:12px' },
      h('div', {}, h('label', {}, 'Caption server (host:port)'), h('input', { id: 'cap-server', value: c.server_cfg == null ? '' : c.server_cfg, placeholder: '192.168.1.50:7070', disabled: locked(), style: 'width:100%' })),
      h('div', {}, h('label', {}, 'Highlight words (comma separated)'), h('input', { id: 'cap-terms', value: (c.highlight_terms || []).join(', '), disabled: locked(), style: 'width:100%' }), h('div', { class: 'muted small' }, 'Supplementary only. "Call Sound" never depends on the recogniser hearing a name.'))),
    h('div', { class: 'check ' + (c.retain_transcripts ? 'warn' : 'info'), style: 'margin-top:12px' }, h('span', {}, h('label', { class: 'row', style: 'color:var(--ink)' }, h('input', { id: 'cap-retain', type: 'checkbox', checked: c.retain_transcripts, disabled: locked() }), 'Keep transcripts on this appliance (OFF by default)'), h('div', { class: 'small' }, 'Turning this on stores what people say as text files. Check your school\'s policy and tell the crew. Audio is never stored (not implemented).'))),
    h('div', { class: 'row', style: 'margin-top:12px' }, h('button', { class: 'primary', disabled: locked(), onclick: () => change('/config/captions', { server: $('#cap-server').value.trim(), highlight_terms: $('#cap-terms').value.split(',').map((s) => s.trim()).filter(Boolean), retain_transcripts: $('#cap-retain').checked }, 'Saved') }, 'Save'))));
}

// ---- Diagnostics ---------------------------------------------------------------------------------------------------
async function vDiag(v) {
  const opts = S.endpoints.map((e) => h('option', { value: e.id }, e.name));
  const matrix = (() => {
    const links = new Set(S.links.map((l) => l.join('>'))); const by = (a) => S.endpoints.find((e) => e.address === a);
    const ids = S.endpoints;
    return h('table', { class: 'matrix' }, h('thead', {}, h('tr', {}, h('th', {}, 'speaker → hears'), ...ids.map((e) => h('th', {}, e.name)))),
      h('tbody', {}, ids.map((a) => h('tr', {}, h('td', {}, a.name), ...ids.map((b) => h('td', { class: a.id === b.id ? '' : (links.has(a.address + '>' + b.address) ? 'yes' : 'no') }, a.id === b.id ? '' : links.has(a.address + '>' + b.address) ? '●' : '·'))))));
  })();
  const out = h('div', { id: 'why-out' }), out2 = h('div', { id: 'dx-out' });
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Who can hear whom (right now)'), h('div', { style: 'overflow-x:auto' }, matrix), h('p', { class: 'muted small' }, 'Matrix shows live audio links. It is based on the engine\'s view of PipeWire.')));
  v.append(h('div', { class: 'panel' }, h('h2', {}, '"Why can\'t A hear B?"'), h('div', { class: 'row' }, h('select', { id: 'why-dst' }, ...opts), h('span', {}, 'can\'t hear'), h('select', { id: 'why-src' }, ...opts.map((o) => o.cloneNode(true))),
    h('button', { onclick: async () => { const r = await admin(`/why?src=${$('#why-src').value}&dst=${$('#why-dst').value}`); out.textContent = r.data.why || 'no answer'; } }, 'Explain')), h('p', { class: 'check info' }, out)));
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Check one headset'), h('div', { class: 'row' }, h('select', { id: 'dx-ep' }, ...opts.map((o) => o.cloneNode(true))),
    h('button', { onclick: async () => { const r = await admin('/diagnose/' + $('#dx-ep').value); out2.replaceChildren(...r.data.map((f) => h('div', { class: 'check ' + (f.level === 'fail' ? 'fail' : f.level) }, h('span', {}, f.msg)))); } }, 'Diagnose'),
    h('button', { onclick: async () => { out2.replaceChildren(h('p', {}, 'Speak into the headset for 4 seconds…')); const r = await admin('/test/mic/' + $('#dx-ep').value, { seconds: 4 }); out2.replaceChildren(h('div', { class: 'check ' + (r.data.ok ? 'ok' : 'fail') }, h('span', {}, r.data.ok ? `Microphone works: peak ${r.data.peak_dbfs} dBFS` : (r.data.error || `No usable microphone signal (peak ${r.data.peak_dbfs} dBFS). Check the headset mute and boom position.`)))); } }, 'Microphone test'),
    h('button', { onclick: () => admin('/test/cue/' + $('#dx-ep').value, {}) }, 'Earpiece test (beep)')), out2));
  const lg = await admin('/log');
  v.append(h('div', { class: 'panel' }, h('h2', {}, 'Engine log (latest)'), h('div', { class: 'loglines' }, ...(lg.data || []).slice(-80).reverse().map((l) => h('div', { class: l.level }, new Date(l.t * 1000).toLocaleTimeString() + '  ' + l.msg)))));
}

// ---- Backup -------------------------------------------------------------------------------------------------------------
function vBackup(v) {
  v.append(h('div', { class: 'panel' }, lockNote(), h('h2', {}, 'Back up and restore settings'),
    h('p', { class: 'small' }, 'The backup is one JSON file: groups, endpoints (including Bluetooth addresses), permissions, dial codes and caption settings. It does not contain pairing keys: after restoring onto a NEW box, headsets must be paired again. See docs/06-operations.md for the full-disk backup that keeps pairings.'),
    h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '/api/admin/config/export', style: 'text-decoration:none' }, 'Download backup'),
      h('input', { type: 'file', id: 'restore-file', accept: '.json,application/json', disabled: locked() }),
      h('button', { disabled: locked(), onclick: async () => { const f = $('#restore-file').files[0]; if (!f) return toast('Choose a file first', true); if (!confirm('Replace ALL current settings with this file?')) return; await change('/config/restore', { json: await f.text() }, 'Restored'); } }, 'Restore from file')),
    h('p', { class: 'small muted' }, 'The appliance also keeps its last 20 automatic versions in /var/lib/crewline/backups/.')));
}

start();

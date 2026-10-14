import { html, useState, useEffect, useMemo, api, groupName } from '/static/js/lib/core.js';
import { ask, Icon, Button, Pill, Led, GroupTag, Panel, Callout, Empty, Dialog, Field, Check, Switch, Qr, CopyButton, Segmented, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead, TALK_MODES, modeLabel, endpointBody } from '/static/js/admin/parts.js';

// Mirror of crewline/mentions.py expand_term(): shows people what the recogniser will listen for.
const LETTER = { a: 'ay', b: 'bee', c: 'see', d: 'dee', e: 'ee', f: 'eff', g: 'gee', h: 'aitch', i: 'eye', j: 'jay', k: 'kay', l: 'el', m: 'em', n: 'en', o: 'oh', p: 'pee', q: 'cue', r: 'are', s: 'ess', t: 'tee', u: 'you', v: 'vee', w: 'double you', x: 'ex', y: 'why', z: 'zee' };
export function expandTerm(term) {
  const base = term.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  if (!base) return [];
  const v = new Set([base]); const compact = base.replace(/ /g, '');
  if (/^[a-z]{2,4}$/.test(compact) && (term.trim() === term.trim().toUpperCase() || base.includes(' ') || term.includes('.'))) {
    const L = compact.split(''); v.add(compact); v.add(L.join(' ')); v.add(L.map((c) => LETTER[c]).join(' '));
    if (L.length === 2) { v.add(`${LETTER[L[0]]} ${L[1]}`); v.add(`${L[0]} ${LETTER[L[1]]}`); }
  }
  return [...v];
}

function TermInput({ terms, onChange }) {
  const [text, setText] = useState('');
  const add = () => { const t = text.trim(); if (t && !terms.includes(t) && terms.length < 8) onChange([...terms, t]); setText(''); };
  return html`<div class="stack-sm">
    <div class="cluster">${terms.map((t) => html`<span key=${t} class="pill mention">${t}<button type="button" class="btn quiet icon sm" style="min-height:20px;width:20px;margin-right:-6px" aria-label=${'Remove ' + t} onClick=${() => onChange(terms.filter((x) => x !== t))}><${Icon} name="x" /></button></span>`)}</div>
    <div class="cluster" style="flex-wrap:nowrap"><input id="term-in" class="input" placeholder="Add a name or word, then press Enter" value=${text} data-testid="term-input"
      onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); } }} />
      <${Button} onClick=${add} disabled=${!text.trim()}>Add<//></div>
    ${terms.length ? html`<div class="hint xs faint">Also heard as: ${[...new Set(terms.flatMap(expandTerm))].filter((v) => !terms.map((t) => t.toLowerCase()).includes(v)).join(', ') || 'exactly as written'}</div>` : null}</div>`;
}

function GroupMatrix({ groups, f, set }) {
  const toggle = (key, id, on) => {
    const cur = new Set(f[key]); on ? cur.add(id) : cur.delete(id);
    const next = { ...f, [key]: [...cur] };
    // keep the rules consistent: what you start with must be allowed
    if (key === 'talk' && on) next.talk_allowed = [...new Set([...f.talk_allowed, id])];
    if (key === 'listen' && on) next.listen_allowed = [...new Set([...f.listen_allowed, id])];
    if (key === 'talk_allowed' && !on) next.talk = f.talk.filter((x) => x !== id);
    if (key === 'listen_allowed' && !on) next.listen = f.listen.filter((x) => x !== id);
    set(next);
  };
  const cell = (key, g, label) => html`<td><input type="checkbox" aria-label=${`${label}: ${g.name}`} checked=${f[key].includes(g.id)} onChange=${(e) => toggle(key, g.id, e.target.checked)} style="width:20px;height:20px;accent-color:var(--accent)" /></td>`;
  return html`<div class="table-wrap"><table class="table" style="text-align:center"><thead><tr><th>Group</th><th>Starts out talking</th><th>Starts out hearing</th><th>May talk to</th><th>May hear</th></tr></thead>
    <tbody>${groups.map((g) => html`<tr key=${g.id}><td style="text-align:left"><${GroupTag} groups=${groups} id=${g.id} /></td>${cell('talk', g, 'Starts out talking to')}${cell('listen', g, 'Starts out hearing')}${cell('talk_allowed', g, 'May talk to')}${cell('listen_allowed', g, 'May hear')}</tr>`)}</tbody></table></div>`;
}

const BUTTON_EVENTS = [['vol_up', 'Volume up'], ['vol_down', 'Volume down'], ['call_button', 'Call / multi-function button'], ['redial', 'Double press (redial)'], ['voice_assist', 'Voice-assistant button'], ['play_pause', 'Play/pause key'], ['next', 'Next track'], ['prev', 'Previous track'], ['hangup', 'End call'], ['answer', 'Answer']];
const HOLD_OK = ['play_pause', 'next', 'prev', 'vol_up', 'vol_down', 'mute_key'];

function ButtonsDialog({ person, onClose }) {
  const { S, get, call, locked } = useAdmin();
  const [info, setInfo] = useState(null);
  const [map, setMap] = useState({});
  const load = async () => { const r = await get('/buttons/' + person.id); if (r.ok) { setInfo(r.data); } };
  useEffect(() => { load(); setMap({ ...(person.buttons || {}) }); }, [person.id]);
  useEffect(() => { if (!info || info.learning_left_s <= 0) return; const t = setInterval(load, 1500); return () => clearInterval(t); }, [info && info.learning_left_s > 0]);
  const seen = (info ? info.observed : []).filter((o) => !o.event.startsWith('raw:'));
  const raw = (info ? info.observed : []).filter((o) => o.event.startsWith('raw:'));
  const acts = [['mute:toggle', 'Mute / unmute'], ['talk:toggle', 'Latched talk on/off'], ['ptt', 'Push-to-talk (hold)'], ['attention', 'Call Sound'], ['allcall:toggle', 'All-call on/off'], ...S.endpoints.filter((x) => x.id !== person.id).map((x) => ['private:' + x.id, 'Private line to ' + x.name]), ['private:off', 'End private line'], ['status', 'Play status beep'],
    ...S.groups.map((g) => ['select:' + g.id, 'Talk to ' + g.name]), ...S.groups.map((g) => ['listen:' + g.id, 'Hear ' + g.name + ' on/off'])];
  const sel = (key, enabled) => html`<select class="select" aria-label=${key} disabled=${!enabled || locked} value=${map[key] || ''} onChange=${(e) => setMap({ ...map, [key]: e.target.value })}>
    <option value="">${enabled ? 'Leave as it is' : 'Not seen yet'}</option>${enabled ? acts.map(([v, t]) => html`<option value=${v}>${t}</option>`) : null}</select>`;
  const save = async () => { const m = {}; for (const [k, v] of Object.entries(map)) if (v) m[k] = v; const r = await call('/config/endpoint', endpointBody(person, { buttons: m }), 'Button assignments saved'); if (r.ok && r.data.ok !== false) onClose(); };
  return html`<${Dialog} open=${true} onClose=${onClose} title=${'Headset buttons: ' + person.name} width=${680}
    footer=${html`<${Button} onClick=${onClose}>Close<//><${Button} variant="primary" onClick=${save} disabled=${locked}>Save assignments<//>`}>
    <div class="stack">
      <p class="muted">Only buttons that have really been seen from this headset can be assigned. Press <b>Learn</b>, then press every button on the headset (also hold and double-press). Assignments pause while learning. A headset's own mute button works inside the headset and usually cannot be seen here.</p>
      ${info && info.profile_hint ? html`<${Callout} icon="info"><b>${info.profile_hint.title}.</b> ${(info.profile_hint.known_local || []).join(' ')}<//>` : null}
      <div class="cluster"><${Button} variant="primary" icon="play" disabled=${!person.address} onClick=${async () => { await api('/api/admin/buttons/learn', { body: { endpoint: person.id, seconds: 30 } }); toast('Learning for 30 seconds. Press the headset buttons now.'); load(); }}>Learn buttons (30 s)<//>
        <${Button} icon="refresh-cw" onClick=${load}>Refresh<//>${info && info.learning_left_s > 0 ? html`<${Pill} kind="warn">Learning… ${Math.round(info.learning_left_s)} s<//>` : null}</div>
      ${raw.length ? html`<p class="small faint">Signals seen but not recognised: ${raw.map((o) => `${o.event.slice(4)} (${o.count}×)`).join(', ')}</p>` : null}
      <div class="table-wrap"><table class="table"><thead><tr><th>Button</th><th>Press</th><th>Hold</th></tr></thead><tbody>
        ${BUTTON_EVENTS.map(([ev, label]) => { const o = seen.find((x) => x.event === ev); return html`<tr key=${ev}><td><b>${label}</b><div class="xs ${o ? '' : 'faint'}" style=${o ? 'color:var(--live)' : ''}>${o ? `seen ${o.count}× via ${o.source}` : 'not seen from this headset'}</div></td><td>${sel(ev, !!o)}</td><td>${HOLD_OK.includes(ev) ? sel(ev + ':long', !!o) : null}</td></tr>`; })}
      </tbody></table></div></div><//>`;
}

function RemoteLink({ person }) {
  const { refresh } = useAdmin();
  if (!person.remote_token) return null;
  const url = `${location.origin}/r/${person.remote_token}`;
  return html`<fieldset class="fgroup stack"><legend>Phone remote</legend>
    <p class="muted small">A private link that opens a page on a phone or Chromebook to talk, mute, switch groups and call Sound for this person only. Anyone with the link can use it.</p>
    <div class="cluster" style="align-items:flex-start;gap:var(--sp-4)"><${Qr} src=${`/api/admin/qr/${person.remote_token}.svg`} alt=${'QR code for ' + person.name + "'s remote"} />
      <div class="stack-sm grow" style="min-width:200px"><input class="input mono" readonly value=${url} onClick=${(e) => e.target.select()} aria-label="Remote link" />
        <div class="cluster"><${CopyButton} text=${url} label="Copy link" /><a class="btn sm" href=${url} target="_blank" rel="noopener">Open<//>
          <${Button} size="sm" variant="danger" onClick=${async () => { if (await ask({ title: 'Make a new link?', body: 'The old link stops working immediately.', confirm: 'Make new link', danger: true })) { await api('/api/admin/remote/rotate', { body: { endpoint: person.id } }); toast('New link created'); refresh(); } }}>New link<//></div></div></div></fieldset>`;
}

const KINDS = [['headset', 'Bluetooth headset'], ['rotary', 'Rotary or desk phone (Cell2Jack)'], ['other', 'Other']];

function PersonEditor({ person, onClose }) {
  const { S, call, locked } = useAdmin();
  const isNew = !person.id;
  const [f, setF] = useState(() => ({
    name: person.name || '', kind: person.kind || 'headset', enabled: person.enabled ?? true, talk_mode: person.talk_mode || 'open', select_scope: person.select_scope || 'talk',
    can_select: person.can_select ?? true, can_allcall: !!person.can_allcall, can_private: !!person.can_private, forced_mute: !!person.forced_mute, captions: person.captions ?? true, tone_control: !!person.tone_control,
    mention_terms: person.mention_terms || [], mention_cue: person.mention_cue ?? true,
    talk: person.home_talk || [], listen: person.home_listen || [], talk_allowed: person.talk_allowed || [], listen_allowed: person.listen_allowed || [],
  }));
  const [buttons, setButtons] = useState(false);
  const up = (k, v) => setF({ ...f, [k]: v });
  const save = async () => {
    const id = isNew ? (f.name.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 20) || 'person') : person.id;
    const body = { id, address: person.address || null, buttons: person.buttons || {}, ...f, name: f.name.trim() };
    const r = await call('/config/endpoint', body, 'Saved');
    if (r.ok && r.data.ok !== false) onClose();
  };
  return html`<${Dialog} open=${true} sheet onClose=${onClose} title=${isNew ? 'Add a person' : person.name} testid="person-editor"
    footer=${html`${!isNew && html`<${Button} variant="danger" disabled=${locked} style="margin-right:auto" onClick=${async () => { if (await ask({ title: `Delete ${person.name}?`, body: 'Their settings are removed. A paired headset stays paired but is no longer used.', confirm: 'Delete', danger: true })) { await call('/config/endpoint_delete', { id: person.id }, 'Deleted'); onClose(); } }}>Delete<//>`}
      <${Button} onClick=${onClose}>Cancel<//><${Button} variant="primary" onClick=${save} disabled=${locked || !f.name.trim()} data-testid="person-save">Save<//>`}>
    <div class="stack-lg">
      ${locked && html`<${Callout} kind="warn" icon="lock">Show mode is on: this is read-only.<//>`}
      <fieldset class="fgroup form-grid" disabled=${locked}><legend>Who</legend>
        <${Field} id="p-name" label="Name"><input id="p-name" class="input" value=${f.name} onInput=${(e) => up('name', e.target.value)} data-testid="person-name" /><//>
        <${Field} id="p-kind" label="Device type"><select id="p-kind" class="select" value=${f.kind} onChange=${(e) => up('kind', e.target.value)}>${KINDS.map(([v, t]) => html`<option value=${v}>${t}</option>`)}</select><//>
        <div class="stack-sm" style="grid-column:1/-1"><${Check} checked=${f.enabled} onChange=${(v) => up('enabled', v)}>Enabled<//>
          <${Check} checked=${f.tone_control} onChange=${(v) => up('tone_control', v)}>Understands dial codes (rotary phone)<//>
          <${Check} checked=${f.captions} onChange=${(v) => up('captions', v)}>Include this microphone in captions<//></div></fieldset>

      <fieldset class="fgroup stack" disabled=${locked}><legend>Groups</legend><${GroupMatrix} groups=${S.groups} f=${f} set=${setF} />
        <div class="form-grid"><${Check} checked=${f.can_select} onChange=${(v) => up('can_select', v)}>Can switch groups themselves<//>
          <${Check} checked=${f.can_allcall} onChange=${(v) => up('can_allcall', v)}>Can make all-calls<//>
          <${Check} checked=${f.can_private} onChange=${(v) => up('can_private', v)}>Can open private one-to-one lines<//>
          <${Field} id="p-scope" label="Choosing a group changes"><select id="p-scope" class="select" value=${f.select_scope} onChange=${(e) => up('select_scope', e.target.value)}><option value="talk">Who they talk to</option><option value="both">Who they talk to and hear</option></select><//></div></fieldset>

      <fieldset class="fgroup stack" disabled=${locked}><legend>Talking</legend>
        <${Field} id="p-mode" label="How the microphone works" hint="Quiet talkers: latched or push-to-talk is better than open mic. It never cuts off whispers."><select id="p-mode" class="select" value=${f.talk_mode} onChange=${(e) => up('talk_mode', e.target.value)} data-testid="person-mode">${TALK_MODES.map(([v, t]) => html`<option value=${v}>${t}</option>`)}</select><//>
        <${Check} checked=${f.forced_mute} onChange=${(v) => up('forced_mute', v)}>Muted by an administrator (they can still hear everything)<//></fieldset>

      <fieldset class="fgroup stack" disabled=${locked}><legend>Name alerts</legend>
        <p class="muted small">When captions pick up one of these words, this person's dashboards flash and, if they are on a headset or rotary phone, they hear two soft pings. Captions can be wrong, so this never replaces the <b>Call Sound</b> button.</p>
        <${TermInput} terms=${f.mention_terms} onChange=${(v) => up('mention_terms', v)} />
        <${Check} checked=${f.mention_cue} onChange=${(v) => up('mention_cue', v)}>Play a soft ping in their headset or phone<//></fieldset>

      ${!isNew && html`<${RemoteLink} person=${person} />
        <fieldset class="fgroup stack"><legend>Headset buttons</legend>
          <p class="muted small">${Object.keys(person.buttons || {}).length ? `${Object.keys(person.buttons).length} assigned.` : 'None assigned.'} Buttons are shortcuts; everything they do is also on the phone remote.</p>
          <div><${Button} icon="headset" onClick=${() => setButtons(true)} disabled=${!person.address}>Learn and assign buttons<//></div></fieldset>`}
    </div>
    ${buttons && html`<${ButtonsDialog} person=${person} onClose=${() => setButtons(false)} />`}<//>`;
}

export function People() {
  const { S, locked } = useAdmin();
  const [edit, setEdit] = useState(null);
  return html`<div class="stack-lg">
    <${PageHead} title="People" actions=${html`<${Button} variant="primary" icon="plus" disabled=${locked} onClick=${() => setEdit({})} data-testid="add-person">Add a person<//>`}>Everyone on the intercom: their name, groups, how their microphone works, and their personal phone remote.<//>
    <${LockNote} />
    <${Panel} flush id="people">${S.endpoints.length ? html`<ul class="rowlist">${S.endpoints.map((e) => html`<li key=${e.id} class="person-row" data-testid=${'person-' + e.id}>
      <${Led} kind=${e.audio_up ? 'live' : e.connected ? 'warn' : 'bad'} on=${e.audio_up} />
      <div class="grow"><b>${e.name}</b><div class="xs faint">${e.kind === 'rotary' ? 'Rotary phone' : 'Headset'} · ${modeLabel(e.talk_mode)}${e.address ? '' : ' · no device paired'}${!e.enabled ? ' · disabled' : ''}${e.forced_mute ? ' · muted by admin' : ''}</div></div>
      <div class="cluster" style="gap:4px">${e.home_talk.map((g) => html`<${GroupTag} key=${g} groups=${S.groups} id=${g} mode="talk" />`)}</div>
      <div class="cluster">${e.can_allcall ? html`<${Pill} icon="megaphone">All-call<//>` : null}${e.can_private ? html`<${Pill} icon="lock">Private<//>` : null}${(e.mention_terms || []).length ? html`<${Pill} kind="mention" icon="at-sign">${e.mention_terms.join(', ')}<//>` : null}</div>
      <${Button} size="sm" onClick=${() => setEdit(e)} data-testid=${'edit-' + e.id}>${locked ? 'View' : 'Edit'}<//></li>`)}</ul>`
      : html`<div style="padding:var(--sp-5)"><${Empty} icon="users" title="Nobody yet">Pair a headset on the Devices page, or add a person here.<//></div>`}<//>
    ${edit && html`<${PersonEditor} person=${edit} onClose=${() => setEdit(null)} />`}</div>`;
}

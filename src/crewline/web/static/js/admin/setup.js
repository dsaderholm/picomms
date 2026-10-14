import { html, useState, useEffect, useStored, api } from '/static/js/lib/core.js';
import { Icon, Button, Pill, Led, Panel, Callout, Field, Qr, CopyButton, GroupTag, Empty, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead, useReadiness, CheckList, endpointBody } from '/static/js/admin/parts.js';
import { PairingPanel, PairDialog } from '/static/js/admin/devices.js';
import { HotspotForm, useNetwork } from '/static/js/admin/network.js';

const STEPS = [
  ['welcome', 'Check the box', 'activity'],
  ['site', 'Name this site', 'pencil'],
  ['network', 'Phones and Wi-Fi', 'wifi'],
  ['pair', 'Pair a headset', 'headset'],
  ['rotary', 'Rotary phone', 'phone'],
  ['people', 'Groups and people', 'users'],
  ['share', 'Share links', 'qr-code'],
  ['finish', 'Final check', 'rocket'],
];

function Welcome() {
  const { S } = useAdmin();
  const rows = [
    ['Intercom controller', S.pipewire_ok, 'The audio system is running.', 'The audio system is not reachable. Check the service on the box.'],
    ['Bluetooth adapter', S.adapters.length > 0, `${S.adapters.length} adapter${S.adapters.length === 1 ? '' : 's'} found.`, 'No adapter found. Plug in a USB Bluetooth adapter (use the powered USB 2.0 hub).'],
    ['Network cable or Wi-Fi', !!(S.network && S.network.available) || true, 'You are connected, since you can see this page.', ''],
  ];
  return html`<div class="stack"><p>This takes about ten minutes. You will pair a headset, test it, and open the dashboard on a phone. Nothing you do here affects a show in progress: show mode locks settings.</p>
    <ul class="stack-sm" style="list-style:none;padding:0;margin:0">${rows.map(([n, ok, yes, no]) => html`<li class="cluster"><${Icon} name=${ok ? 'circle-check' : 'circle-alert'} class=${ok ? 'ok' : 'fail'} style=${'color:var(--' + (ok ? 'live' : 'alert') + ')'} /><b>${n}</b><span class="muted">${ok ? yes : no}</span></li>`)}</ul>
    <p class="muted small">Have ready: headsets charged and switched off, and the rotary phone with its Cell2Jack if you use one.</p></div>`;
}

function Site() {
  const { S, call, locked } = useAdmin();
  const [name, setName] = useState(S.site_name || '');
  return html`<div class="stack"><${LockNote} /><${Field} id="su-site" label="What should the dashboard call this crew?" hint="For example: ICS Tech Crew"><input id="su-site" class="input" value=${name} onInput=${(e) => setName(e.target.value)} maxlength="60" disabled=${locked} /><//>
    <div><${Button} variant="primary" onClick=${() => call('/config/site_name', { name }, 'Saved')} disabled=${locked || name === (S.site_name || '')}>Save name<//></div>
    <${Callout} kind="info" icon="shield-check">Change the admin password on the <a href="#/settings">Settings</a> page before you share this box with anyone.<//></div>`;
}

function NetworkStep() {
  const { S } = useAdmin();
  const [info, reload] = useNetwork();
  const [mode, setMode] = useState(S.network && S.network.ap_active ? 'hotspot' : 'venue');
  const url = location.origin + '/';
  return html`<div class="stack"><p>Phones and Chromebooks open the dashboard in a browser. They need to be on the same network as this box.</p>
    <div class="grid-auto">
      <button type="button" class=${'choice' + (mode === 'venue' ? ' on' : '')} aria-pressed=${mode === 'venue'} onClick=${() => setMode('venue')}><${Icon} name="router" class="lg" /><b>Use the venue network</b><span class="muted small">This box is on a cable. Phones join the school Wi-Fi.</span></button>
      <button type="button" class=${'choice' + (mode === 'hotspot' ? ' on' : '')} aria-pressed=${mode === 'hotspot'} onClick=${() => setMode('hotspot')} data-testid="choice-hotspot"><${Icon} name="wifi" class="lg" /><b>Make the box its own Wi-Fi</b><span class="muted small">For venues with no usable Wi-Fi. Internet can pass through.</span></button></div>
    ${mode === 'venue' && html`<div class="cluster" style="align-items:flex-start;gap:var(--sp-5)"><${Qr} src="/api/public/qr/dashboard.svg" alt="QR code for the dashboard" /><div class="stack-sm"><p>Open this address on a phone that is on the same network:</p><p class="mono"><b>${url}</b></p><${CopyButton} text=${url} /></div></div>`}
    ${mode === 'hotspot' && (info ? html`<${HotspotForm} info=${info} reload=${reload} />` : html`<div class="skeleton" style="height:160px"></div>`)}</div>`;
}

function PairStep() {
  const { S, call } = useAdmin();
  const [pick, setPick] = useState(null);
  const people = S.endpoints.filter((e) => e.address);
  return html`<div class="stack"><p>Pair one headset first and make sure it works. You can add the rest later.</p>
    <${PairingPanel} onPick=${setPick} />
    ${people.length ? html`<div class="stack"><h3>Paired</h3><ul class="rowlist panel flush">${people.map((e) => html`<li key=${e.id} class="person-row"><${Led} kind=${e.audio_up ? 'live' : e.connected ? 'warn' : 'bad'} on=${e.audio_up} /><div class="grow"><b>${e.name}</b>
      <div class="xs faint">${e.audio_up ? 'Two-way audio is working' : e.connected ? 'Connected, but no voice link yet' : 'Not connected'}</div></div>
      <${Button} size="sm" icon="volume-2" onClick=${() => call('/test/cue/' + e.id, {}, 'Beep sent. Did you hear it in the headset?')}>Beep<//>
      <${Button} size="sm" icon="mic" onClick=${async () => { toast('Speak into the headset for 4 seconds…'); const r = await api('/api/admin/test/mic/' + e.id, { body: { seconds: 4 } }); toast(r.data.ok ? 'Microphone works.' : (r.data.error || 'No microphone signal. Check the headset mute and boom.'), r.data.ok ? 'ok' : 'bad'); }}>Test mic<//></li>`)}</ul></div>` : null}
    <${PairDialog} device=${pick} onClose=${() => setPick(null)} /></div>`;
}

function RotaryStep() {
  const { S, call, locked } = useAdmin();
  const [pick, setPick] = useState(null);
  const [which, setWhich] = useState('');
  const rotary = S.endpoints.find((e) => e.kind === 'rotary' && e.address);
  const candidates = S.endpoints.filter((e) => e.address && e.kind !== 'rotary');
  return html`<div class="stack"><p>If you talk through a rotary or desk phone with a Cell2Jack, pair the Cell2Jack here. Skip this step if you only use headsets.</p>
    <${Callout} kind="info" icon="phone">Put the Cell2Jack in pairing mode (its manual says to pick up the phone and press <span class="kbd">#</span><span class="kbd">*</span><span class="kbd">#</span>; check your model's manual), then open the pairing window below.<//>
    ${rotary ? html`<${Callout} kind="live" icon="circle-check"><b>${rotary.name}</b> is set up as the rotary phone and understands dial codes. Review the keys on the <a href="#/dial">Dial codes</a> page.<//>`
      : html`<${PairingPanel} onPick=${setPick} />
        ${candidates.length ? html`<div class="stack"><h3>Which paired device is the rotary phone?</h3>
          <div class="cluster"><select class="select" aria-label="Paired device" value=${which} onChange=${(e) => setWhich(e.target.value)} style="max-width:320px"><option value="">Choose…</option>${candidates.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select>
            <${Button} variant="primary" disabled=${!which || locked} onClick=${() => { const e = S.endpoints.find((x) => x.id === which); call('/config/endpoint', endpointBody(e, { kind: 'rotary', tone_control: true, can_allcall: true, talk_allowed: S.groups.map((g) => g.id), listen_allowed: S.groups.map((g) => g.id) }), 'Set up as the rotary phone'); }}>Set up as the rotary phone<//></div></div>` : null}`}
    <${PairDialog} device=${pick} onClose=${() => setPick(null)} /></div>`;
}

function PeopleStep() {
  const { S } = useAdmin();
  return html`<div class="stack"><p>Groups are channels. Everyone starts in the groups below and can switch within what you allow.</p>
    <div class="cluster">${S.groups.map((g) => html`<${GroupTag} key=${g.id} groups=${S.groups} id=${g.id} />`)}<a href="#/groups">Edit groups</a></div>
    ${S.endpoints.length ? html`<ul class="rowlist panel flush">${S.endpoints.map((e) => html`<li key=${e.id} class="person-row"><b class="grow">${e.name}</b>
      <div class="cluster" style="gap:4px">${e.home_talk.length ? e.home_talk.map((g) => html`<${GroupTag} key=${g} groups=${S.groups} id=${g} mode="talk" />`) : html`<${Pill} kind="warn">no group yet<//>`}</div></li>`)}</ul>
      <p class="muted small">Change who talks where, who can make all-calls and what to listen for in captions on the <a href="#/people">People</a> page.</p>` : html`<${Empty} icon="users" title="Nobody yet">Pair a headset first.<//>`}</div>`;
}

function ShareStep() {
  const { S } = useAdmin();
  const withLinks = S.endpoints.filter((e) => e.remote_token);
  return html`<div class="stack"><p>Each person gets a private link for their phone: talk, mute, switch groups and call Sound. Send it, or let them scan the code.</p>
    ${withLinks.length ? html`<div class="grid-auto">${withLinks.map((e) => html`<div key=${e.id} class="panel stack-sm" style="background:var(--s2)"><b>${e.name}</b><${Qr} src=${`/api/admin/qr/${e.remote_token}.svg`} alt=${'QR for ' + e.name} />
      <div class="cluster"><${CopyButton} text=${location.origin + '/r/' + e.remote_token} label="Copy link" /></div></div>`)}</div>
      <div><a class="btn" href="#/print"><${Icon} name="printer" />Print cards</a></div>` : html`<${Empty} icon="qr-code" title="No links yet">Links appear after you add people.<//>`}</div>`;
}

function Finish() {
  const { S, call, locked } = useAdmin();
  const { list, run, busy, worst } = useReadiness();
  return html`<div class="stack"><p>One last look. Fix anything red; yellow is worth reading.</p>
    ${list ? html`<${CheckList} list=${list} />` : html`<div class="skeleton" style="height:120px"></div>`}
    <div class="cluster"><${Button} icon="refresh-cw" onClick=${run} disabled=${busy}>Check again<//>
      ${!locked && html`<${Button} variant="primary" icon="lock" disabled=${worst === 'fail'} onClick=${() => call('/config/show_mode', { on: true }, 'Show mode on. You are live.')}>Go live: lock settings<//>`}</div>
    <p class="muted small">Show mode stops accidental pairing or routing changes. People can still talk, mute and call Sound.</p></div>`;
}

const BODIES = { welcome: Welcome, site: Site, network: NetworkStep, pair: PairStep, rotary: RotaryStep, people: PeopleStep, share: ShareStep, finish: Finish };

export function Setup() {
  const { S } = useAdmin();
  const [i, setI] = useStored('setup.step', 0);
  const idx = Math.min(Math.max(+i || 0, 0), STEPS.length - 1);
  const done = {
    welcome: S.adapters.length > 0, site: !!S.site_name, network: !!(S.network && S.network.ap_active),
    pair: S.endpoints.some((e) => e.address), rotary: S.endpoints.some((e) => e.kind === 'rotary' && e.address),
    people: S.endpoints.length > 0 && S.endpoints.every((e) => e.home_talk.length), share: false, finish: S.show_mode,
  };
  const [id, title, icon] = STEPS[idx];
  const Body = BODIES[id];
  return html`<div class="stack-lg">
    <${PageHead} title="Setup assistant">Get from a fresh box to a working intercom. Skip any step and come back later.<//>
    <nav class="step-rail" aria-label="Setup steps">${STEPS.map(([sid, st], n) => html`<button key=${sid} type="button" class=${'step-dot' + (n === idx ? ' current' : '') + (done[sid] ? ' done' : '')} aria-current=${n === idx ? 'step' : undefined} onClick=${() => setI(n)}><b>${done[sid] && n !== idx ? html`<${Icon} name="check" />` : n + 1}</b>${st}</button>`)}</nav>
    <${Panel} id=${'step-' + id} eyebrow=${`Step ${idx + 1} of ${STEPS.length}`} title=${title}><${Body} />
      <div class="cluster" style="margin-top:var(--sp-5);justify-content:space-between"><${Button} icon="arrow-left" onClick=${() => setI(idx - 1)} disabled=${idx === 0}>Back<//>
        <div class="cluster">${idx < STEPS.length - 1 ? html`<${Button} variant="primary" data-testid="setup-next" onClick=${() => setI(idx + 1)}>${done[id] ? 'Next' : 'Skip for now'}<//>` : html`<a class="btn primary" href="#/overview">Done</a>`}</div></div><//></div>`;
}

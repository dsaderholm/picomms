import { html, useState, useMemo, useEffect } from '/static/js/lib/core.js';
import { ask, Icon, Button, Pill, Led, Panel, Callout, Empty, Dialog, Field, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

export function PairDialog({ device, onClose }) {
  const { S, call } = useAdmin();
  const free = S.endpoints.filter((e) => !e.address);
  const [name, setName] = useState(device ? (device.name || '') : '');
  const [existing, setExisting] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (device) { setName(device.name || ''); setExisting(''); setBusy(false); } }, [device]);
  if (!device) return null;
  const submit = async () => {
    const body = { address: device.address };
    if (existing) body.endpoint = existing; else body.new_name = name.trim();
    if (!body.endpoint && !body.new_name) { toast('Give this headset a name first.', 'bad'); return; }
    setBusy(true);
    const r = await call('/bt/pair', body);
    setBusy(false);
    if (r.data && r.data.ok) { toast(`${existing ? 'Assigned' : name.trim()} is paired.`); onClose(); }
    else if (r.data && r.data.message) toast(r.data.message, 'bad');
  };
  return html`<${Dialog} open=${!!device} onClose=${onClose} title=${device.paired ? 'Assign this headset' : 'Pair this headset'} width=${520} testid="pair-dialog"
    footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} variant="primary" onClick=${submit} disabled=${busy} data-testid="pair-confirm">${busy ? 'Pairing… up to 30 s' : device.paired ? 'Assign' : 'Pair'}<//>`}>
    <div class="stack"><p class="mono muted">${device.address}</p>
      <${Field} id="pair-name" label="Who or what is this? (shown on the dashboard)" hint="For example: Alex (stage left), Follow spot, Sound booth"><input id="pair-name" class="input" value=${name} onInput=${(e) => setName(e.target.value)} disabled=${!!existing} data-testid="pair-name" /><//>
      ${free.length ? html`<${Field} id="pair-existing" label="Or give it to a person you already added"><select id="pair-existing" class="select" value=${existing} onChange=${(e) => setExisting(e.target.value)}><option value="">Create a new person</option>${free.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//>` : null}</div><//>`;
}

export function PairingPanel({ onPick }) {
  const { S, call, locked } = useAdmin();
  const open = S.pairing_open_s > 0;
  const [adapter, setAdapter] = useState('');
  const [secs, setSecs] = useState(120);
  const found = S.unassigned_devices || [];
  const sorted = [...found].sort((a, b) => (b.supports_hfp - a.supports_hfp) || ((b.rssi ?? -999) - (a.rssi ?? -999)));
  return html`<${Panel} id="pairing" eyebrow="Add a headset" title="Pair a headset" actions=${open ? html`<${Pill} kind="live" icon="bluetooth"><span class="num">${S.pairing_open_s}s</span> left<//>` : null}>
    <div class="stack">
      <ol class="steps muted">
        <li>Open the pairing window. It closes by itself.</li>
        <li>Put the headset in pairing mode (usually hold the power button until the light flashes).</li>
        <li>Choose it in the list, give it a name, and press <b>Pair</b>.</li></ol>
      <div class="cluster">
        ${!open && html`<${Field} id="pair-adapter" label="Adapter"><select id="pair-adapter" class="select" value=${adapter} onChange=${(e) => setAdapter(e.target.value)}><option value="">Any adapter</option>${S.adapters.map((a) => html`<option value=${a.address}>${a.address}</option>`)}</select><//>
          <${Field} id="pair-secs" label="Open for"><select id="pair-secs" class="select" value=${secs} onChange=${(e) => setSecs(+e.target.value)}>${[60, 120, 300].map((s) => html`<option value=${s}>${s / 60} min</option>`)}</select><//>`}
        ${open ? html`<${Button} onClick=${() => call('/bt/close_pairing', {}, 'Pairing window closed')}>Close the window now<//>`
          : html`<${Button} variant="primary" icon="bluetooth" disabled=${locked || !S.adapters.length} data-testid="open-pairing" onClick=${() => call('/bt/open_pairing', { adapter: adapter || null, seconds: secs }, 'Pairing window open')}>Open pairing window<//>`}
      </div>
      ${!S.adapters.length && html`<${Callout} kind="bad" icon="bluetooth-off">No Bluetooth adapter was found. Plug in a USB Bluetooth adapter.<//>`}
      <div role="status">
        ${open && !sorted.length && html`<div class="cluster muted"><${Led} kind="live" on pulse /> Searching for headsets…</div>`}
        ${sorted.length ? html`<ul class="rowlist panel flush" style="margin-top:var(--sp-3)">${sorted.map((d) => html`<li key=${d.address} class="person-row">
          <${Icon} name=${d.supports_hfp ? 'headset' : 'bluetooth'} class="lg" /><div class="grow"><b>${d.name || 'Unnamed device'}</b>
            <div class="xs faint mono">${d.address} · signal ${d.rssi == null ? 'unknown' : d.rssi + ' dBm'}</div></div>
          ${d.supports_hfp ? html`<${Pill} kind="live">Works as a headset<//>` : html`<${Pill} kind="warn">No microphone profile seen<//>`}
          <${Button} variant="primary" size="sm" disabled=${locked || (!d.paired && !open)} data-testid=${'pair-' + d.address} onClick=${() => onPick(d)}>${d.paired ? 'Assign' : 'Pair'}<//></li>`)}</ul>` : null}
        ${!open && !sorted.length && html`<p class="faint small">Nothing nearby yet. Open the pairing window to search.</p>`}
      </div></div><//>`;
}

export function Devices() {
  const { S, call, locked } = useAdmin();
  const [pick, setPick] = useState(null);
  const assigned = S.endpoints.filter((e) => e.address);
  return html`<div class="stack-lg">
    <${PageHead} title="Devices">Bluetooth adapters and the headsets paired to them.<//>
    <${LockNote} />
    <${Panel} id="adapters" eyebrow="Hardware" title="Bluetooth adapters">
      ${S.adapters.length ? html`<div class="grid-auto">${S.adapters.map((a) => html`<div key=${a.address} class="panel" style="background:var(--s2)" data-testid="adapter">
        <div class="spread"><b class="mono">${a.address}</b><${Pill} kind=${a.powered ? 'live' : 'bad'}>${a.powered ? 'On' : 'Off'}<//></div>
        <div class="stack-sm" style="margin-top:8px"><div class="small muted">Voice sessions now</div><div class="stat num">${a.hfp_connected}</div>
          <div class="xs faint">Capacity per adapter has not been measured yet. See the validation plan.</div></div></div>`)}</div>`
        : html`<${Empty} icon="bluetooth-off" title="No adapters found">Plug a USB Bluetooth adapter into the powered hub, then reload this page.<//>`}
    <//>
    <${PairingPanel} onPick=${setPick} />
    <${Panel} flush id="paired" eyebrow="Connected to this box" title="Paired headsets">
      ${assigned.length ? html`<ul class="rowlist">${assigned.map((e) => html`<li key=${e.id} class="person-row">
        <${Led} kind=${e.audio_up ? 'live' : e.connected ? 'warn' : 'bad'} on=${e.audio_up} />
        <div class="grow"><b>${e.name}</b><div class="xs faint mono">${e.address}${e.adapter ? ' · adapter …' + e.adapter.slice(-5) : ''}${e.codec ? ' · ' + e.codec : ''}</div></div>
        <span class="small muted">${e.audio_up ? 'Two-way audio' : e.connected ? 'Connected, no voice link' : 'Not connected'}</span>
        <div class="cluster"><${Button} size="sm" icon="refresh-cw" onClick=${() => call('/bt/connect', { address: e.address }, 'Reconnect requested')}>Reconnect<//>
          <${Button} size="sm" disabled=${locked} onClick=${() => call('/bt/disconnect', { address: e.address }, 'Disconnected')}>Disconnect<//>
          <${Button} size="sm" variant="danger" disabled=${locked} onClick=${async () => { if (await ask({ title: `Forget ${e.name}?`, body: 'The headset will need to be paired again.', confirm: 'Forget', danger: true })) call('/bt/forget', { address: e.address }, 'Forgotten'); }}>Forget<//></div></li>`)}</ul>`
        : html`<div style="padding:var(--sp-5)"><${Empty} icon="headset" title="No headsets paired">Use the pairing window above.<//></div>`}<//>
    <${PairDialog} device=${pick} onClose=${() => setPick(null)} /></div>`;
}

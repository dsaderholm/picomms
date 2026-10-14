import { html, useState, useEffect, useCallback, api } from '/static/js/lib/core.js';
import { ask, Icon, Button, Pill, Led, Panel, Callout, Field, Switch, Segmented, Qr, CopyButton, Empty, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

const CH5 = [36, 40, 44, 48, 149, 153, 157, 161, 165];
const CH24 = [1, 6, 11];

export function useNetwork() {
  const { get } = useAdmin();
  const [info, setInfo] = useState(null);
  const load = useCallback(async () => { const r = await get('/network'); if (r.ok) setInfo(r.data); }, [get]);
  useEffect(() => { load(); const t = setInterval(() => { if (!document.hidden) load(); }, 6000); return () => clearInterval(t); }, [load]);
  return [info, load];
}

export function HotspotForm({ info, reload, compact }) {
  const { call, locked } = useAdmin();
  const st = info.status || {};
  const n = info.settings;
  const [f, setF] = useState({ ap_ssid: n.ap_ssid, ap_password: n.ap_password, ap_band: n.ap_band, ap_channel: n.ap_channel, ap_interface: n.ap_interface, passthrough: n.passthrough });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setF({ ap_ssid: n.ap_ssid, ap_password: n.ap_password, ap_band: n.ap_band, ap_channel: n.ap_channel, ap_interface: n.ap_interface, passthrough: n.passthrough }); }, [JSON.stringify(n)]);
  const ifaces = (st.interfaces || []).filter((d) => d.kind === 'wifi');
  const capable = ifaces.filter((d) => d.ap_capable);
  const running = !!(st.ap && st.ap.active);
  const up = (k, v) => setF({ ...f, [k]: v });
  const suggest = async () => { const r = await api('/api/admin/network/suggest', { body: {} }); if (r.ok) setF({ ...f, ap_ssid: r.data.ssid, ap_password: r.data.password }); setShow(true); };
  const channels = f.ap_band === '5ghz' ? CH5 : CH24;
  const start = async () => {
    setBusy(true);
    const s = await call('/network/settings', { ...f, ap_enabled: true });
    if (s.ok && s.data.ok !== false) { const r = await call('/network/ap/start', {}, 'Hotspot started'); }
    setBusy(false); reload();
  };
  return html`<div class="stack">
    <div class="cluster"><${Pill} kind=${running ? 'live' : ''} icon="wifi">${running ? 'Hotspot running' : 'Hotspot off'}<//>
      ${running && html`<span class="muted small">${st.ap.clients == null ? '' : st.ap.clients + ' connected · '}${n.ap_band === '5ghz' ? '5 GHz' : '2.4 GHz'}, channel ${n.ap_channel}</span>`}</div>
    ${!st.available && html`<${Callout} kind="bad" icon="wifi-off">Network control is not available on this box: ${st.reason || 'NetworkManager is not installed'}. The intercom still works over a normal network cable.<//>`}
    ${st.available && !capable.length && html`<${Callout} kind="warn" icon="triangle-alert">No Wi-Fi adapter on this box can run a hotspot. Plug in a USB Wi-Fi adapter that supports access-point mode, or use a small travel router instead. See the hardware guide.<//>`}
    <div class="form-grid">
      <${Field} id="ap-ssid" label="Network name"><input id="ap-ssid" class="input" value=${f.ap_ssid} onInput=${(e) => up('ap_ssid', e.target.value)} disabled=${locked} maxlength="32" data-testid="ap-ssid" /><//>
      <${Field} id="ap-pw" label="Password" hint="At least 8 characters."><div class="cluster" style="flex-wrap:nowrap"><input id="ap-pw" class="input mono" type=${show ? 'text' : 'password'} value=${f.ap_password} onInput=${(e) => up('ap_password', e.target.value)} disabled=${locked} data-testid="ap-password" autocomplete="off" />
        <${Button} iconOnly icon=${show ? 'eye' : 'eye'} label=${show ? 'Hide password' : 'Show password'} onClick=${() => setShow(!show)} /></div><//></div>
    <div class="cluster"><${Button} size="sm" icon="sparkles" onClick=${suggest} disabled=${locked}>Suggest a name and password<//></div>
    <div class="form-grid">
      <div class="field"><span class="label">Band</span><${Segmented} label="Band" value=${f.ap_band} onChange=${(v) => setF({ ...f, ap_band: v, ap_channel: v === '5ghz' ? 36 : 6 })} options=${[['5ghz', '5 GHz'], ['2.4ghz', '2.4 GHz']]} />
        <div class="hint">${f.ap_band === '5ghz' ? 'Recommended. Keeps Wi-Fi out of the way of the Bluetooth headsets.' : ''}</div></div>
      <${Field} id="ap-ch" label="Channel"><select id="ap-ch" class="select" value=${f.ap_channel} onChange=${(e) => up('ap_channel', +e.target.value)} disabled=${locked}>${channels.map((c) => html`<option value=${c}>${c}</option>`)}</select><//>
      <${Field} id="ap-if" label="Wi-Fi adapter for the hotspot"><select id="ap-if" class="select" value=${f.ap_interface} onChange=${(e) => up('ap_interface', e.target.value)} disabled=${locked}><option value="">Choose automatically</option>${ifaces.map((d) => html`<option value=${d.name}>${d.name}${d.ap_capable ? '' : ' (cannot host)'}${d.supports_5ghz ? ' · 5 GHz' : ''}</option>`)}</select><//></div>
    ${f.ap_band === '2.4ghz' && html`<${Callout} kind="warn" icon="triangle-alert">A 2.4 GHz hotspot shares airspace with Bluetooth. Expect shorter headset range and more dropouts. Use 5 GHz unless a phone cannot join it.<//>`}
    <${Switch} checked=${f.passthrough} onChange=${(v) => up('passthrough', v)} disabled=${locked}>Let devices on the hotspot use the internet through this box<//>
    <div class="cluster">${running ? html`<${Button} onClick=${async () => { await call('/network/ap/stop', {}, 'Hotspot stopped'); reload(); }} disabled=${locked}>Stop hotspot<//>` : null}
      <${Button} variant="primary" icon="wifi" onClick=${async () => { if (running && !(await ask({ title: 'Restart the hotspot?', body: 'Phones on it will disconnect for a few seconds.', confirm: 'Restart' }))) return; start(); }} disabled=${locked || busy || !st.available || !f.ap_ssid || f.ap_password.length < 8} data-testid="ap-start">${busy ? 'Starting…' : running ? 'Apply and restart' : 'Start hotspot'}<//></div></div>`;
}

function Uplink({ info, reload }) {
  const { call, locked, get } = useAdmin();
  const st = info.status || {};
  const ifaces = st.interfaces || [];
  const apIface = st.ap && st.ap.interface;
  const wifi = ifaces.filter((d) => d.kind === 'wifi' && d.name !== apIface);
  const [iface, setIface] = useState('');
  const [nets, setNets] = useState(null);
  const [pick, setPick] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const scan = async () => { setBusy(true); const r = await get('/network/scan?iface=' + encodeURIComponent(iface || wifi[0].name)); setBusy(false); if (r.ok) setNets(r.data); };
  const net = st.internet || {};
  return html`<div class="stack">
    <div class="cluster"><${Pill} kind=${net.ok ? 'live' : 'warn'} icon="globe">${net.ok ? `Internet reachable${net.ms ? ' · ' + net.ms + ' ms' : ''}` : 'No internet right now'}<//>
      ${st.uplink_interface && html`<span class="muted small">via ${st.uplink_interface}</span>`}</div>
    <p class="muted small">The intercom itself never needs the internet. Internet is only for things like updates, and for phones on the hotspot if you allow it.</p>
    ${st.available && wifi.length ? html`<div class="stack"><h3>Connect this box to the venue's Wi-Fi</h3>
      <p class="muted small">Prefer a network cable when you can. If you use Wi-Fi, a 2.4 GHz connection can reduce Bluetooth range; pick a 5 GHz network if there is one.</p>
      <div class="cluster"><${Field} id="up-if" label="Adapter"><select id="up-if" class="select" value=${iface || wifi[0].name} onChange=${(e) => setIface(e.target.value)}>${wifi.map((d) => html`<option value=${d.name}>${d.name}</option>`)}</select><//>
        <div style="align-self:flex-end"><${Button} icon="search" onClick=${scan} disabled=${busy || locked}>${busy ? 'Scanning…' : 'Scan for networks'}<//></div></div>
      ${nets && (nets.length ? html`<ul class="rowlist panel flush">${nets.map((n) => html`<li key=${n.ssid} class="person-row"><${Icon} name="wifi" class="lg" /><div class="grow"><b>${n.ssid}</b><div class="xs faint">${n.band === '5ghz' ? '5 GHz' : '2.4 GHz'} · channel ${n.channel} · signal ${n.signal}%${n.secured ? '' : ' · open'}</div></div>
        <${Button} size="sm" disabled=${locked} onClick=${() => { setPick(n.ssid); setPw(''); }}>Connect<//></li>`)}</ul>` : html`<p class="faint small">No networks found.</p>`)}
      ${pick && html`<form class="cluster" onSubmit=${async (e) => { e.preventDefault(); setBusy(true); await call('/network/join', { iface: iface || wifi[0].name, ssid: pick, password: pw }, 'Connected to ' + pick); setBusy(false); setPick(''); reload(); }}>
        <${Field} id="up-pw" label=${`Password for ${pick}`}><input id="up-pw" class="input" type="password" value=${pw} onInput=${(e) => setPw(e.target.value)} autofocus /><//>
        <div style="align-self:flex-end" class="cluster"><${Button} variant="primary" type="submit" disabled=${busy}>Connect<//><${Button} onClick=${() => setPick('')}>Cancel<//></div></form>`}</div>` : null}</div>`;
}

export function NetworkPage() {
  const { S, locked } = useAdmin();
  const [info, reload] = useNetwork();
  if (!info) return html`<div class="skeleton" style="height:240px"></div>`;
  const st = info.status || {};
  const n = info.settings;
  const running = !!(st.ap && st.ap.active);
  const ifaces = st.interfaces || [];
  return html`<div class="stack-lg">
    <${PageHead} title="Network">Make the box its own Wi-Fi network when the venue has none, and choose how it reaches the internet.<//>
    <${LockNote} />
    <${Callout} kind="info" icon="info"><b>Why 5 GHz?</b> Bluetooth headsets and 2.4 GHz Wi-Fi share the same radio band. Putting the hotspot on 5 GHz, on its own adapter placed away from the Bluetooth adapters, protects headset range. If you can, use a network cable for internet.<//>
    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));align-items:start">
      <${Panel} id="hotspot" eyebrow="This box as a Wi-Fi network" title="Hotspot"><${HotspotForm} info=${info} reload=${reload} /><//>
      <div class="stack">
        <${Panel} id="join" eyebrow="For phones and Chromebooks" title="Join the hotspot">
          ${running && info.wifi_qr ? html`<div class="cluster" style="align-items:flex-start;gap:var(--sp-5)"><${Qr} src=${'/api/admin/qr.svg?data=' + encodeURIComponent(info.wifi_qr)} alt="QR code to join the Wi-Fi network" />
            <div class="stack-sm"><p>Scan to join <b>${n.ap_ssid}</b>, then open the dashboard:</p><p class="mono"><b>http://10.42.0.1:8080/</b></p><p class="faint small">Also reachable as http://crewline.lan:8080/ on the hotspot.</p><${CopyButton} text="http://10.42.0.1:8080/" /><a href="#/print">Print a join sheet</a></div></div>`
            : html`<${Empty} icon="qr-code" title="Start the hotspot first">A join code appears here once the hotspot is running.<//>`}<//>
        <${Panel} id="internet" eyebrow="Reaching the internet" title="Internet"><${Uplink} info=${info} reload=${reload} /><//></div></div>
    <${Panel} flush id="ifaces" title="Network adapters">
      <div class="table-wrap"><table class="table"><thead><tr><th>Name</th><th>Type</th><th>State</th><th>Address</th><th>Notes</th></tr></thead><tbody>
        ${ifaces.map((d) => html`<tr key=${d.name}><td class="mono">${d.name}</td><td>${d.kind === 'wifi' ? 'Wi-Fi' : d.kind === 'ethernet' ? 'Cable' : 'Other'}</td><td>${d.state}</td><td class="mono">${d.ipv4 || '—'}</td>
          <td class="small muted">${d.kind === 'wifi' ? [d.ap_capable ? 'can host a hotspot' : 'cannot host a hotspot', d.supports_5ghz ? '5 GHz' : '2.4 GHz only', d.freq_mhz ? d.freq_mhz + ' MHz' : ''].filter(Boolean).join(' · ') : ''}${d.name === st.uplink_interface ? ' · internet route' : ''}</td></tr>`)}
        ${!ifaces.length && html`<tr><td colspan="5" class="muted">No adapters reported.</td></tr>`}</tbody></table></div><//></div>`;
}

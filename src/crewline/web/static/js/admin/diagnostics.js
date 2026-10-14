import { html, useState, useEffect, api, ago, useNow } from '/static/js/lib/core.js';
import { Icon, Button, Pill, Panel, Callout, Field, Empty, toast } from '/static/js/lib/ui.js';
import { useAdmin } from '/static/js/admin/data.js';
import { PageHead, LEVEL_ICON } from '/static/js/admin/parts.js';

export function Diagnostics() {
  const { S, get, call } = useAdmin();
  const eps = S.endpoints;
  const [who, setWho] = useState(eps[0] ? eps[0].id : '');
  const [src, setSrc] = useState(eps[0] ? eps[0].id : '');
  const [dst, setDst] = useState(eps[1] ? eps[1].id : (eps[0] ? eps[0].id : ''));
  const [dx, setDx] = useState(null);
  const [why, setWhy] = useState('');
  const [mic, setMic] = useState(null);
  const [log, setLog] = useState([]);
  const now = useNow(5000);
  useEffect(() => { get('/log').then((r) => r.ok && setLog(r.data)); const t = setInterval(() => get('/log').then((r) => r.ok && setLog(r.data)), 5000); return () => clearInterval(t); }, [get]);
  const links = new Set((S.links || []).map((l) => l.join('>')));
  const hears = (a, b) => links.has(a.address + '>' + b.address);

  return html`<div class="stack-lg">
    <${PageHead} title="Diagnostics">Find out why someone cannot hear someone, or why a headset is not working.<//>

    <${Panel} flush id="matrix" title="Who can hear whom, right now">
      <div class="table-wrap" style="padding:0 var(--sp-5) var(--sp-5)"><table class="matrix" aria-label="Who hears whom"><thead><tr><th scope="col">Speaker</th>${eps.map((e) => html`<th key=${e.id} scope="col">${e.name}</th>`)}</tr></thead>
        <tbody>${eps.map((a) => html`<tr key=${a.id}><th scope="row" style="text-align:left">${a.name}</th>${eps.map((b) => html`<td key=${b.id} class=${a.id === b.id ? 'self' : hears(a, b) ? 'yes' : 'no'}>${a.id === b.id ? '' : hears(a, b) ? html`<span aria-label="yes">●</span>` : html`<span aria-label="no">·</span>`}</td>`)}</tr>`)}</tbody></table>
        <p class="faint small" style="margin-top:8px">Read across: a dot means the person at the top hears the person on the left. Based on the live audio links.</p></div><//>

    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));align-items:start">
      <${Panel} id="why" title="Why can't someone hear someone?">
        <div class="stack"><div class="cluster"><${Field} id="why-dst" label="Who can't hear"><select id="why-dst" class="select" value=${dst} onChange=${(e) => setDst(e.target.value)}>${eps.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//>
          <${Field} id="why-src" label="Whom"><select id="why-src" class="select" value=${src} onChange=${(e) => setSrc(e.target.value)}>${eps.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//></div>
          <div><${Button} onClick=${async () => { const r = await get(`/why?src=${encodeURIComponent(src)}&dst=${encodeURIComponent(dst)}`); setWhy(r.ok ? r.data.why : 'No answer.'); }}>Explain<//></div>
          ${why && html`<${Callout} kind="info" icon="info"><span data-testid="why-out">${why}</span><//>`}</div><//>

      <${Panel} id="check" title="Check one headset">
        <div class="stack"><${Field} id="dx-ep" label="Headset"><select id="dx-ep" class="select" value=${who} onChange=${(e) => { setWho(e.target.value); setDx(null); setMic(null); }}>${eps.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//>
          <div class="cluster"><${Button} data-testid="diagnose" onClick=${async () => { const r = await get('/diagnose/' + encodeURIComponent(who)); if (r.ok) setDx(r.data); }}>Diagnose<//>
            <${Button} icon="mic" onClick=${async () => { setMic({ busy: true }); const r = await api('/api/admin/test/mic/' + encodeURIComponent(who), { body: { seconds: 4 } }); setMic(r.data); }}>Microphone test<//>
            <${Button} icon="volume-2" onClick=${() => call('/test/cue/' + who, {}, 'Beep sent')}>Earpiece test<//></div>
          ${mic && (mic.busy ? html`<${Callout} kind="info" icon="mic">Speak into the headset for 4 seconds…<//>` : html`<${Callout} kind=${mic.ok ? 'live' : 'bad'} icon=${mic.ok ? 'circle-check' : 'circle-alert'}>${mic.ok ? `Microphone works (peak ${mic.peak_dbfs} dBFS).` : (mic.error || `No usable microphone signal (peak ${mic.peak_dbfs} dBFS). Check the headset's own mute and the boom position.`)}<//>`)}
          ${dx && html`<div class="stack-sm">${dx.map((f) => html`<${Callout} kind=${{ ok: 'live', warn: 'warn', fail: 'bad', info: 'info' }[f.level]} icon=${LEVEL_ICON[f.level]}>${f.msg}<//>`)}</div>`}</div><//></div>

    <${Panel} id="log" title="Recent events" eyebrow="Engine log">
      <div class="loglines" role="log" tabindex="0" aria-label="Engine log">${[...log].slice(-80).reverse().map((l, i) => html`<div key=${i} class=${l.level}>${new Date(l.t * 1000).toLocaleTimeString()}  ${l.msg}</div>`)}${!log.length && html`<div class="faint">Nothing yet.</div>`}</div><//></div>`;
}

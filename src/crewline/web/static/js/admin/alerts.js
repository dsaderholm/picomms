import { html, useState } from '/static/js/lib/core.js';
import { Icon, Button, Pill, Panel, Callout, Field, Switch, Empty, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead, endpointBody } from '/static/js/admin/parts.js';

export function AlertsPage() {
  const { S, call, locked } = useAdmin();
  const [cool, setCool] = useState(S.captions.mention_cooldown_s);
  const withTerms = S.endpoints.filter((e) => (e.mention_terms || []).length);
  const calls = S.attention.filter((a) => a.active);
  const nameOf = (id) => (S.endpoints.find((e) => e.id === id) || {}).name || id;
  return html`<div class="stack-lg">
    <${PageHead} title="Alerts">How people get your attention: a deliberate call, or a name heard in the captions.<//>
    <${LockNote} />
    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));align-items:start">
      <${Panel} id="calls" eyebrow="Deliberate" title="Calling ${nameOf(S.attention_target) || 'Sound'}">
        <div class="stack"><p class="muted">Anyone can press <b>Call Sound</b> on their phone remote or a headset button. It shows a persistent red banner on every dashboard until someone acknowledges it. It never depends on captions.</p>
          <${Field} id="att-target" label="Who receives calls"><select id="att-target" class="select" disabled=${locked} value=${S.attention_target} onChange=${(e) => call('/config/attention_target', { id: e.target.value }, 'Saved')}>${S.endpoints.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//>
          ${calls.length ? html`<${Callout} kind="bad" icon="phone-call">${calls.length} unacknowledged ${calls.length === 1 ? 'call' : 'calls'}. <${Button} size="sm" onClick=${() => call('/attention/ack', { by: 'admin' }, 'Cleared')}>Acknowledge all<//><//>` : html`<p class="faint small">No calls waiting.</p>`}</div><//>

      <${Panel} id="mentions" eyebrow="From captions" title="Name alerts">
        <div class="stack"><p class="muted">When captions hear someone's name or word, their screen flashes violet and, if they use a headset or rotary phone, they hear two soft pings in their own ear. It is a nudge, not a promise: captions can miss a name.</p>
          ${withTerms.length ? html`<ul class="rowlist panel flush">${withTerms.map((e) => html`<li key=${e.id} class="person-row"><div class="grow"><b>${e.name}</b><div class="cluster" style="margin-top:4px">${e.mention_terms.map((t) => html`<${Pill} key=${t} kind="mention">${t}<//>`)}</div></div>
            <${Switch} checked=${e.mention_cue} disabled=${locked} onChange=${(v) => call('/config/endpoint', endpointBody(e, { mention_cue: v }), v ? 'Ping on' : 'Ping off')}>Ping in headset<//>
            <${Button} size="sm" icon="play" onClick=${() => call('/test/mention/' + e.id, {}, 'Test sent')}>Test<//></li>`)}</ul>`
            : html`<${Empty} icon="at-sign" title="No names set up">Open a person on the <a href="#/people">People</a> page and add a name to listen for, for example DJ.<//>`}
          <${Field} id="mc" label="Minimum seconds between pings in one headset" hint="Prevents pings piling up in someone's ear. The screen alert is not limited."><div class="cluster"><input id="mc" class="input" type="number" min="0" max="120" value=${cool} onInput=${(e) => setCool(e.target.value)} disabled=${locked} style="max-width:8em" />
            <${Button} onClick=${() => call('/config/captions', { mention_cooldown_s: +cool }, 'Saved')} disabled=${locked || +cool === S.captions.mention_cooldown_s}>Save<//></div><//></div><//></div>

    <${Panel} id="how" title="How each person is reached">
      <div class="table-wrap"><table class="table"><thead><tr><th>Where they are</th><th>Call Sound</th><th>Name heard in captions</th></tr></thead><tbody>
        <tr><td><b>Watching the dashboard</b> (laptop, tablet, Chromebook)</td><td>Red banner, screen edge flashes, optional chime</td><td>Violet banner, screen edge flashes violet, optional chime</td></tr>
        <tr><td><b>Phone with their remote link</b></td><td>Banner, vibration, optional chime</td><td>Banner, vibration, optional chime</td></tr>
        <tr><td><b>Headset only</b></td><td>Banner on any screen; no sound in the headset</td><td>Two soft pings in their ear</td></tr>
        <tr><td><b>Rotary phone</b></td><td>Banner on any screen. Ringing the phone is not built yet.</td><td>Two soft pings in the handset</td></tr></tbody></table></div><//></div>`;
}

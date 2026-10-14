import { html, useState, useEffect, useMemo, api, ago, useNow, groupName } from '/static/js/lib/core.js';
import { Icon, Button, Pill, Led, GroupTag, Panel, Callout, Empty, Dialog, Field, Qr, CopyButton, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead, useReadiness, CheckList } from '/static/js/admin/parts.js';

const HERO = {
  ok: ['circle-check', 'Ready for the show', 'Everything checked is working.'],
  warn: ['triangle-alert', 'Ready, with a few things to look at', 'Nothing is broken, but read the yellow items.'],
  fail: ['circle-alert', 'Not ready yet', 'Fix the red items below before the show.'],
};

export function Overview() {
  const { S, call, locked } = useAdmin();
  const { list, run, busy, worst } = useReadiness();
  const [confirm, setConfirm] = useState(false);
  const now = useNow(5000);
  const [h, setH] = useState(null);
  useEffect(() => { setH(worst); }, [worst]);
  const hero = HERO[worst] || ['activity', 'Checking…', ''];
  const first = !S.endpoints.some((e) => e.address);

  const goLive = () => { if (worst === 'fail') setConfirm(true); else call('/config/show_mode', { on: true }, 'Show mode on. Settings are locked.'); };

  return html`<div class="stack-lg">
    <${PageHead} title="Overview" actions=${html`<${Button} icon="refresh-cw" onClick=${run} disabled=${busy}>${busy ? 'Checking…' : 'Run checks'}<//>`}>${S.site_name ? S.site_name + ': ' : ''}Is everything ready, and who is on the line right now?<//>

    ${first && html`<${Callout} kind="info" icon="rocket"><b>New here?</b> The <a href="#/setup">Setup assistant</a> walks you through pairing the first headset, testing it and opening the dashboard on a phone.<//>`}
    <${LockNote} />

    <section class="panel stack" aria-label="Readiness">
      <div class=${'readiness-hero ' + (worst || '')}><div class="big-led"><${Icon} name=${hero[0]} /></div>
        <div><h2 data-testid="readiness-title">${hero[1]}</h2><p class="muted">${hero[2]}</p></div></div>
      ${list ? html`<${CheckList} list=${list} />` : html`<div class="skeleton" style="height:120px"></div>`}
      <div class="cluster">
        ${locked ? html`<${Button} icon="lock-open" onClick=${() => call('/config/show_mode', { on: false }, 'Settings unlocked.')}>End show mode<//>`
          : html`<${Button} variant="primary" icon="lock" data-testid="go-live" onClick=${goLive} disabled=${!list}>Go live: lock settings<//>`}
        <span class="muted small">${locked ? 'Settings are locked. Talk, mute and groups still work.' : 'Show mode stops accidental pairing and routing changes.'}</span></div>
    </section>

    <${Panel} flush id="crew" title="Who is on the line" eyebrow=${`${S.endpoints.filter((e) => e.connected && e.audio_up).length} of ${S.endpoints.length} online`}>
      ${S.endpoints.length ? html`<div class="table-wrap"><table class="table"><thead><tr><th>Person</th><th>Status</th><th>Talking to</th><th class="no-print"><span class="sr-only">Actions</span></th></tr></thead><tbody>
        ${S.endpoints.map((e) => html`<tr key=${e.id}>
          <td><b>${e.name}</b><div class="xs faint">${e.kind === 'rotary' ? 'Rotary phone' : 'Headset'}${e.battery != null ? ` · battery ${e.battery}%` : ''}</div></td>
          <td><div class="cluster nowrap" style="gap:6px"><${Led} kind=${e.audio_up ? 'live' : e.connected ? 'warn' : 'bad'} on=${e.audio_up} />
            <span>${!e.enabled ? 'Disabled' : !e.connected ? 'Not connected' : !e.audio_up ? 'No voice link' : e.forced_mute ? 'Muted by admin' : e.muted ? 'Muted' : e.speaking ? 'Speaking' : e.allcall ? 'All-call' : 'Online'}</span></div></td>
          <td><div class="cluster" style="gap:4px">${e.talk.map((g) => html`<${GroupTag} key=${g} groups=${S.groups} id=${g} />`)}</div></td>
          <td class="no-print"><div class="cluster" style="justify-content:flex-end">
            <${Button} size="sm" icon=${e.muted ? 'mic' : 'mic-off'} disabled=${!e.audio_up || e.forced_mute} onClick=${() => call('/control', { endpoint: e.id, action: 'mute:toggle', source: 'admin' })}>${e.muted ? 'Unmute' : 'Mute'}<//>
            <${Button} size="sm" icon="volume-2" disabled=${!e.audio_up} onClick=${() => call('/test/cue/' + e.id, {}, 'Beep sent to ' + e.name)}>Beep<//></div></td></tr>`)}
      </tbody></table></div>`
      : html`<div style="padding:var(--sp-5)"><${Empty} icon="headset" title="Nobody is connected yet">Pair a headset on the <a href="#/devices">Devices</a> page.<//></div>`}<//>

    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));align-items:start">
      <${Announce} />
      <${ShareCard} />
    </div></div>
    <${Dialog} open=${confirm} onClose=${() => setConfirm(false)} title="Lock anyway?" width=${520}
      footer=${html`<${Button} onClick=${() => setConfirm(false)}>Cancel<//><${Button} variant="danger" onClick=${() => { setConfirm(false); call('/config/show_mode', { on: true }, 'Show mode on.'); }}>Lock settings<//>`}>
      <${Callout} kind="bad" icon="triangle-alert">The check found problems. You can still lock settings, but you will not be able to pair or fix routing until you end show mode.<//><//>`;
}

function Announce() {
  const { call } = useAdmin();
  const [text, setText] = useState('');
  const send = async (t) => { const r = await call('/announce', { text: t, by: 'Crew lead' }, 'Sent to every screen'); if (r.ok) setText(''); };
  return html`<${Panel} id="announce" title="Send a message to every screen" eyebrow="Standby calls">
    <div class="stack"><div class="cluster">${['Standby', 'Go', 'Hold', 'Clear'].map((w) => html`<${Button} key=${w} onClick=${() => send(w)}>${w}<//>`)}</div>
      <form class="cluster" style="flex-wrap:nowrap" onSubmit=${(e) => { e.preventDefault(); if (text.trim()) send(text); }}>
        <input class="input" aria-label="Custom message" placeholder="Custom message, for example: 5 minutes" maxlength="80" value=${text} onInput=${(e) => setText(e.target.value)} />
        <${Button} type="submit" variant="primary" disabled=${!text.trim()}>Send<//></form>
      <p class="faint small">Shows as a banner with a chime on every dashboard and remote for about 25 seconds. It does not play in headsets.</p></div><//>`;
}

function ShareCard() {
  const { S } = useAdmin();
  const url = location.origin + '/';
  const net = S.network || {};
  return html`<${Panel} id="share" title="Open the dashboard on another screen" eyebrow="Share">
    <div class="cluster" style="align-items:flex-start;gap:var(--sp-5)">
      <${Qr} src="/api/public/qr/dashboard.svg" alt="QR code for the dashboard" />
      <div class="stack-sm grow" style="min-width:200px"><p>Scan with a phone camera, or open:</p><p class="mono"><b>${url}</b></p><${CopyButton} text=${url} />
        ${net.ap_active ? html`<p class="small muted" style="margin-top:8px"><${Icon} name="wifi" /> Phones first join Wi-Fi <b>${net.ap_ssid}</b>.</p>` : html`<p class="small muted">Phones must be on the same network as this box. <a href="#/network">Create a Wi-Fi hotspot</a> if the venue has none.</p>`}
        <a href="#/print">Print setup sheets</a></div></div><//>`;
}

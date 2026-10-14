import {
  html, render, useState, useEffect, useRef, useMemo, useCallback, api, connectEvents, debounce, useStored,
  useNow, ago, clock, groupIdx, groupName, chime, vibrate,
} from '/static/js/lib/core.js';
import {
  Icon, Button, Pill, Led, GroupTag, Meter, Callout, Empty, Panel, Dialog, Toasts, Logo, Segmented, Switch, Field, ThemeMenu, Check,
} from '/static/js/lib/ui.js';

// ---- live data -----------------------------------------------------------------------------
function useLive() {
  const [S, setS] = useState(null);
  const [caps, setCaps] = useState(new Map());
  const [engineOk, setEngineOk] = useState(true);
  const [linkOk, setLinkOk] = useState(true);
  const [needPin, setNeedPin] = useState(false);
  const [pin, setPin] = useStored('pin', '');
  const handlers = useRef({});

  const load = useCallback(async () => {
    const r = await api('/api/public/state', { pin });
    if (r.status === 401 && r.data.pin) { setNeedPin(true); return; }
    setNeedPin(false);
    if (r.status === 503 || r.status === 0) { setEngineOk(false); return; }
    setEngineOk(true); setS(r.data);
  }, [pin]);
  const loadCaps = useCallback(async () => {
    const r = await api('/api/public/captions', { pin });
    if (r.ok) setCaps((m) => { const n = new Map(m); for (const c of r.data) n.set(c.endpoint + ':' + c.seg, c); return n; });
  }, [pin]);

  useEffect(() => { load(); loadCaps(); }, [load, loadCaps]);
  useEffect(() => {
    const soon = debounce(load, 120);
    return connectEvents('/api/public/events' + (pin ? '?pin=' + encodeURIComponent(pin) : ''), (ev) => {
      switch (ev.type) {
        case 'speaking': setS((s) => s && ({ ...s, endpoints: s.endpoints.map((e) => e.id === ev.endpoint ? { ...e, speaking: ev.speaking, transmitting: ev.transmitting ?? e.transmitting } : e) })); break;
        case 'caption': setCaps((m) => { const n = new Map(m); n.set(ev.endpoint + ':' + ev.seg, ev); return n; }); break;
        case 'engine': setEngineOk(ev.ok); if (ev.ok) load(); break;
        case 'mention': handlers.current.onMention && handlers.current.onMention(ev.mention); soon(); break;
        default: soon();
      }
    }, setLinkOk);
  }, [pin, load]);
  return { S, caps, engineOk: engineOk && linkOk, needPin, setPin, reload: load, handlers };
}

// ---- header ----------------------------------------------------------------------------------
function Header({ S, onSettings, onJoin, alertCount }) {
  const cap = S && S.captions || {};
  const net = S && S.network || {};
  return html`<header class="app-header"><div class="app-header-inner">
    <${Logo} site=${S && S.site_name} />
    <div class="cluster grow status-cluster">
      ${S && html`<${Pill} kind=${S.show_mode ? 'live' : 'warn'} icon=${S.show_mode ? 'lock' : 'lock-open'}>${S.show_mode ? 'Show mode' : 'Setup mode'}<//>`}
      ${S && html`<${Pill} kind=${!cap.enabled ? '' : cap.connected ? 'live' : 'warn'} icon="captions">${!cap.enabled ? 'Captions off' : cap.connected ? 'Captions live' : 'Captions offline'}<//>`}
      ${net.ap_active && html`<${Pill} icon="wifi">${net.ap_ssid}${net.clients != null ? ` · ${net.clients}` : ''}<//>`}
    </div>
    <div class="cluster">
      <${Button} variant="quiet" iconOnly icon="qr-code" label="Join this dashboard" onClick=${onJoin} data-testid="join-btn" />
      <${Button} variant="quiet" iconOnly icon="bell" label=${'Alert settings' + (alertCount ? ` (${alertCount} active)` : '')} onClick=${onSettings} data-testid="alert-settings" />
    </div></div></header>`;
}

// ---- stations ----------------------------------------------------------------------------------
function stationState(e) {
  if (!e.enabled) return { text: 'Disabled by an administrator', led: 'bad', online: false };
  if (!e.connected) return { text: 'Not connected', led: 'bad', online: false };
  if (!e.audio_up) return { text: 'Connected, no voice link yet', led: 'warn', online: false };
  if (e.forced_mute) return { text: 'Muted by an administrator', led: 'warn', online: true };
  if (e.muted) return { text: 'Muted', led: 'warn', online: true };
  if (e.allcall) return { text: 'All-call', led: 'live', online: true };
  if (e.private) return { text: 'On a private line', led: 'live', online: true };
  if (e.speaking) return { text: 'Speaking', led: 'live', online: true, speaking: true };
  if (e.transmitting) return { text: e.talk_mode === 'open' ? 'Mic open' : 'Talking', led: 'live', online: true };
  return { text: e.talk_mode === 'ptt' ? 'Push-to-talk' : e.talk_mode === 'latched' ? 'Tap to talk' : 'Listening', led: 'live', online: true };
}
const initials = (n) => n.replace(/\(.*?\)/g, '').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('') || '?';

function Station({ e, groups }) {
  const st = stationState(e);
  return html`<li class=${'station' + (st.speaking ? ' speaking' : '') + (st.online ? '' : ' offline')} data-testid=${'station-' + e.id}>
    <div class=${'avatar' + (st.speaking || e.allcall ? ' live' : '')} aria-hidden="true">${e.muted ? html`<${Icon} name="mic-off" />` : initials(e.name)}</div>
    <div class="station-main">
      <div class="spread" style="flex-wrap:nowrap">
        <div class="station-name">${e.name}</div>
        <div class="cluster nowrap" style="gap:6px"><${Led} kind=${st.led} on=${st.online} pulse=${st.speaking} /><span class="small ${st.speaking ? '' : 'muted'}">${st.text}</span></div>
      </div>
      <div class="cluster" style="gap:6px">
        ${e.talk.map((g) => html`<${GroupTag} key=${'t' + g} groups=${groups} id=${g} mode="talk" />`)}
        ${e.listen.filter((g) => !e.talk.includes(g)).map((g) => html`<${GroupTag} key=${'l' + g} groups=${groups} id=${g} mode="listen" />`)}
      </div>
      <${Meter} level=${e.level_db} active=${st.online && (e.speaking || e.transmitting)} />
    </div></li>`;
}

function Stations({ S }) {
  const list = S.endpoints;
  return html`<${Panel} flush id="stations" eyebrow=${`${list.filter((e) => e.connected && e.audio_up).length} of ${list.length} online`} title="Crew">
    ${list.length ? html`<ul class="rowlist stations">${list.map((e) => html`<${Station} key=${e.id} e=${e} groups=${S.groups} />`)}</ul>`
      : html`<div style="padding:var(--sp-5)"><${Empty} icon="headset" title="No headsets yet">Pair a headset in <a href="/admin">Admin</a> and it will appear here.<//></div>`}
    <p class="faint xs" style="padding:var(--sp-3) var(--sp-5) var(--sp-4)">Speaking lights come straight from each microphone. They do not depend on captions.</p><//>`;
}

// ---- captions ----------------------------------------------------------------------------------
function Captions({ S, caps }) {
  const [filter, setFilter] = useState('');
  const [onlyMentions, setOnlyMentions] = useState(false);
  const [size, setSize] = useStored('capsize', 1.15);
  const box = useRef(null);
  const [stuck, setStuck] = useState(true);
  const list = useMemo(() => [...caps.values()].sort((a, b) => a.t - b.t).slice(-100)
    .filter((c) => !filter || String(c.group || '').split(',').includes(filter))
    .filter((c) => !onlyMentions || c.mention), [caps, filter, onlyMentions]);
  const nameOf = (id) => (S.endpoints.find((e) => e.id === id) || {}).name || id;

  useEffect(() => { const b = box.current; if (b && stuck) b.scrollTop = b.scrollHeight; }, [list, stuck]);
  const onScroll = () => { const b = box.current; setStuck(b.scrollHeight - b.scrollTop - b.clientHeight < 70); };
  const enabled = S.captions && S.captions.enabled;

  return html`<${Panel} id="captions" eyebrow="Live" title="Captions" actions=${html`
      <${Segmented} label="Show captions from" value=${filter} onChange=${setFilter} options=${[['', 'All'], ...S.groups.map((g) => [g.id, g.name])]} />
      <${Check} checked=${onlyMentions} onChange=${setOnlyMentions}>Names only<//>
      <${Button} size="sm" iconOnly icon="chevron-down" label="Smaller text" onClick=${() => setSize(Math.max(.85, size - .15))} class="txt-down" />
      <${Button} size="sm" iconOnly icon="chevron-up" label="Larger text" onClick=${() => setSize(Math.min(2.8, size + .15))} />`}>
    <div class="caps" ref=${box} onScroll=${onScroll} tabindex="0" role="log" aria-label="Live captions" style=${`--cap-size:${size}rem`} data-testid="captions">
      ${list.map((c) => html`<div key=${c.endpoint + ':' + c.seg} class=${'cap' + (c.final ? '' : ' interim') + (c.mention ? ' mention' : '')}>
        <span class="cap-t num faint">${clock(c.t)}</span>
        <div class="cap-body"><div class="cap-who"><span class=${'text-g' + groupIdx(S.groups, String(c.group || '').split(',')[0])}>${c.name || c.endpoint}</span>
          ${String(c.group || '').split(',').filter(Boolean).map((g) => html`<${GroupTag} key=${g} groups=${S.groups} id=${g} />`)}
          ${c.mention && c.mention_targets && c.mention_targets.length ? html`<${Pill} kind="mention" icon="at-sign">${c.mention_targets.map(nameOf).join(', ')}<//>` : null}</div>
          <div class="cap-text">${c.text}${c.final ? '' : '…'}</div></div></div>`)}
      ${!list.length && html`<${Empty} icon="captions" title=${enabled ? 'Waiting for someone to speak' : 'Captions are not set up'}>
        ${enabled ? 'Captions appear here a moment after someone speaks.' : html`The intercom works without captions. An administrator can connect a caption computer in <a href="/admin">Admin</a>.`}<//>`}
    </div>
    ${!stuck && html`<div class="jump"><${Button} size="sm" variant="primary" icon="chevron-down" onClick=${() => { box.current.scrollTop = box.current.scrollHeight; setStuck(true); }}>Jump to latest<//></div>`}
    <p class="faint xs" style="margin-top:var(--sp-3)">Captions are automatic and can be wrong or late. They are not stored unless an administrator turns that on.</p><//>`;
}

// ---- alerts ----------------------------------------------------------------------------------------
function AlertStack({ S, calls, mentions, onAckCall, onAckMention, onAckAllMentions, now }) {
  const nameOf = (id) => (S.endpoints.find((e) => e.id === id) || {}).name || id;
  const target = nameOf(S.attention_target) || 'Sound';
  const newest = mentions.length ? mentions[mentions.length - 1] : null;
  const ann = (S.announcements || [])[0];
  return html`<div class="alert-stack" aria-live="assertive">
    ${ann && html`<div class="alert-announce" role="status" data-testid="announcement"><${Icon} name="megaphone" class="lg" />
      <div class="grow"><div class="alert-title">${ann.text}</div><div class="small">${ann.by || 'Crew lead'} · ${ago(ann.t, now)}</div></div></div>`}
    ${calls.map((a) => html`<div key=${'c' + a.id} class="alert-call" role="alert" data-testid="call-alert">
      <${Icon} name="phone-call" class="lg" />
      <div class="grow"><div class="alert-title">Calling ${target}</div><div class="alert-sub">${nameOf(a.source)} · ${ago(a.created, now)}</div></div>
      <${Button} class="alert-ack" onClick=${() => onAckCall(a.id)}>Acknowledge<//></div>`)}
    ${newest && html`<div class="alert-mention" role="alert" data-testid="mention-alert">
      <${Icon} name="at-sign" class="lg" />
      <div class="grow"><div class="alert-title">${newest.test ? 'Test: ' : ''}${nameOf(newest.target)} was mentioned${newest.source ? html` by ${nameOf(newest.source)}` : ''}</div>
        <div class="alert-sub">${newest.text}</div></div>
      <${Button} size="sm" onClick=${() => onAckMention(newest.id)}>Got it<//></div>`}
    ${mentions.length > 1 && html`<div class="alert-more"><span>${mentions.length - 1} earlier ${mentions.length - 1 === 1 ? 'mention' : 'mentions'}</span><${Button} size="sm" variant="quiet" onClick=${onAckAllMentions}>Clear all<//></div>`}</div>`;
}

function SettingsDialog({ open, onClose, S, prefs, setPrefs }) {
  return html`<${Dialog} open=${open} onClose=${onClose} title="Alerts and appearance" testid="settings-dialog">
    <div class="stack-lg">
      <div class="stack"><h3>Alert me about</h3>
        <${Field} id="me" label="When someone says the name of" hint="You get a violet screen flash and a chime. Calls for the sound operator always show for everyone.">
          <select id="me" class="select" value=${prefs.me ?? S.attention_target ?? ''} onChange=${(e) => setPrefs({ ...prefs, me: e.target.value })}>
            <option value="">Nobody (just highlight captions)</option>
            ${S.endpoints.map((e) => html`<option value=${e.id}>${e.name}</option>`)}</select><//>
        <${Switch} checked=${prefs.sound} onChange=${(v) => { setPrefs({ ...prefs, sound: v }); if (v) chime.call(); }}>Play a chime on this device<//>
        <${Switch} checked=${prefs.vibrate} onChange=${(v) => { setPrefs({ ...prefs, vibrate: v }); if (v) vibrate(120); }}>Vibrate (phones)<//></div>
      <${ThemeMenu} />
      <a class="btn" href="/help"><${Icon} name="life-buoy" /> Help and tips</a></div><//>`;
}

function JoinDialog({ open, onClose, S }) {
  const url = location.origin + '/';
  return html`<${Dialog} open=${open} onClose=${onClose} title="Open this dashboard on another device" testid="join-dialog" width=${520}>
    <div class="stack" style="align-items:flex-start">
      <img class="qr" src="/api/public/qr/dashboard.svg" alt="QR code for this dashboard" />
      <p>Scan with a phone camera, or type <b class="mono">${url}</b></p>
      ${S && S.network && S.network.ap_active && html`<${Callout} kind="info" icon="wifi">First join the Wi-Fi network <b>${S.network.ap_ssid}</b>. Ask the crew lead for the password.<//>`}
    </div><//>`;
}

// ---- app ------------------------------------------------------------------------------------------------
function App() {
  const { S, caps, engineOk, needPin, setPin, reload, handlers } = useLive();
  const [tab, setTab] = useState('crew');
  const [prefs, setPrefs] = useStored('dash', { sound: false, vibrate: true });
  const [settings, setSettings] = useState(false);
  const [join, setJoin] = useState(false);
  const now = useNow(1000);
  const seenCalls = useRef(null);
  const [pinText, setPinText] = useState('');

  const me = S ? (prefs.me === undefined ? S.attention_target : prefs.me) : '';
  const calls = S ? S.attention : [];
  const allMentions = S ? (S.mentions || []) : [];
  const mine = allMentions.filter((m) => me && m.target === me);
  const callIsForMe = !!calls.length;          // a call for the sound operator is shown to everyone
  const glowCall = callIsForMe;
  const glowMention = !glowCall && mine.length > 0;

  // New call: chime, vibrate, title.
  useEffect(() => {
    if (!S) return;
    const ids = new Set(calls.map((c) => c.id));
    if (seenCalls.current && [...ids].some((i) => !seenCalls.current.has(i))) { if (prefs.sound) chime.call(); if (prefs.vibrate) vibrate([200, 100, 200]); }
    seenCalls.current = ids;
  }, [calls.map((c) => c.id).join(',')]);
  useEffect(() => { document.title = (calls.length ? '(!) ' : mine.length ? '(@) ' : '') + 'Crewline'; }, [calls.length, mine.length]);
  // New announcement: chime.
  const annId = S && (S.announcements || [])[0] ? S.announcements[0].t : 0;
  useEffect(() => { if (annId && prefs.sound) chime.call(); if (annId && prefs.vibrate) vibrate([100, 60, 100]); }, [annId]);
  // New mention for me: chime and vibrate.
  useEffect(() => {
    handlers.current.onMention = (m) => { if (me && m.target === me) { if (prefs.sound) chime.mention(); if (prefs.vibrate) vibrate([80, 60, 80]); } };
  }, [me, prefs.sound, prefs.vibrate]);

  const ackCall = async (id) => { await api('/api/public/attention/ack', { body: { id } }); reload(); };
  const ackMention = async (id) => { await api('/api/public/mention/ack', { body: { id } }); reload(); };
  const ackAllMentions = async () => { await api('/api/public/mention/ack', { body: {} }); reload(); };

  if (needPin) return html`<div class="page-pad" style="padding-top:20vh;max-width:420px;margin:0 auto"><${Panel} title="Viewer PIN">
    <form class="stack" onSubmit=${(e) => { e.preventDefault(); setPin(pinText.trim()); }}><${Field} id="pin" label="Enter the PIN from the crew lead"><input id="pin" class="input" inputmode="numeric" autocomplete="off" value=${pinText} onInput=${(e) => setPinText(e.target.value)} /><//>
    <${Button} variant="primary" type="submit">Open dashboard<//></form><//></div>`;
  const alertCount = calls.length + mine.length;

  return html`
    ${S && S.simulated && html`<div class="banner-sim" role="region" aria-label="Simulation notice">SIMULATION: nothing on this page comes from real hardware</div>`}
    ${!engineOk && html`<div class="banner-off" role="alert">Can't reach the intercom controller. Audio keeps running; this page will update when it returns.</div>`}
    <${Header} S=${S} onSettings=${() => setSettings(true)} onJoin=${() => setJoin(true)} alertCount=${alertCount} />
    <div class=${'glow call' + (glowCall ? ' on' : '')} aria-hidden="true"></div><div class=${'glow mention' + (glowMention ? ' on' : '')} aria-hidden="true"></div>
    ${S ? html`
      <${AlertStack} S=${S} calls=${calls} mentions=${mine} onAckCall=${ackCall} onAckMention=${ackMention} onAckAllMentions=${ackAllMentions} now=${now} />
      <main id="main" class="dash page-pad" data-tab=${tab}>
        <h1 class="sr-only">${S.site_name || 'Crewline'} crew list and captions</h1>
        <div class="dash-col crew-col"><${Stations} S=${S} /></div>
        <div class="dash-col caps-col"><${Captions} S=${S} caps=${caps} /></div>
        <div class="dash-col alerts-col"><${Panel} title="Alerts" eyebrow="Calls and names">
          ${calls.length + allMentions.length === 0 ? html`<${Empty} icon="bell" title="All quiet">Calls for Sound and name mentions show here and flash the screen.<//>` : null}
          <${AlertList} S=${S} calls=${calls} mentions=${allMentions} now=${now} onAckCall=${ackCall} onAckMention=${ackMention} /><//></div>
      </main>
      <nav class="tabbar" aria-label="Sections">
        ${[['crew', 'users', 'Crew'], ['captions', 'captions', 'Captions'], ['alerts', 'bell', 'Alerts']].map(([id, icon, label]) => html`
          <button type="button" aria-current=${tab === id ? 'page' : undefined} onClick=${() => setTab(id)}>
            <${Icon} name=${icon} />${label}${id === 'alerts' && alertCount ? html`<span class="badge">${alertCount}</span>` : null}</button>`)}</nav>`
      : html`<main class="page-pad" style="padding-top:var(--sp-6)"><div class="skeleton" style="height:240px"></div></main>`}
    <${SettingsDialog} open=${settings} onClose=${() => setSettings(false)} S=${S || { endpoints: [] }} prefs=${prefs} setPrefs=${setPrefs} />
    <${JoinDialog} open=${join} onClose=${() => setJoin(false)} S=${S} />
    <${Toasts} />`;
}

function AlertList({ S, calls, mentions, now, onAckCall, onAckMention }) {
  const nameOf = (id) => (S.endpoints.find((e) => e.id === id) || {}).name || id;
  return html`<ul class="rowlist">
    ${calls.map((a) => html`<li key=${'c' + a.id} class="alert-row"><${Icon} name="phone-call" /><div class="grow"><b>${nameOf(a.source)}</b> is calling ${nameOf(S.attention_target)}<div class="small muted">${ago(a.created, now)}</div></div><${Button} size="sm" onClick=${() => onAckCall(a.id)}>Acknowledge<//></li>`)}
    ${mentions.map((m) => html`<li key=${'m' + m.id} class="alert-row"><${Icon} name="at-sign" /><div class="grow"><b>${nameOf(m.target)}</b> mentioned${m.source ? html` by ${nameOf(m.source)}` : ''}<div class="small muted">${m.text}</div></div><${Button} size="sm" onClick=${() => onAckMention(m.id)}>Got it<//></li>`)}</ul>`;
}

render(html`<${App} />`, document.getElementById('app'));

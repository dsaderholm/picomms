import {
  html, render, useState, useEffect, useRef, useCallback, api, connectEvents, debounce, useStored, groupName, clock, chime, vibrate,
} from '/static/js/lib/core.js';
import { Icon, Button, Pill, Led, GroupTag, Callout, Dialog, Toasts, Logo, Switch, ThemeMenu, toast } from '/static/js/lib/ui.js';

const token = location.pathname.split('/').pop();
const base = `/api/r/${encodeURIComponent(token)}`;

function useRemote() {
  const [S, setS] = useState(null);
  const [caps, setCaps] = useState(new Map());
  const [engineOk, setEngineOk] = useState(true);
  const [linkOk, setLinkOk] = useState(true);
  const [invalid, setInvalid] = useState(false);
  const handlers = useRef({});
  const load = useCallback(async () => {
    const r = await api(base + '/state');
    if (r.status === 404) { setInvalid(true); return; }
    if (r.status === 503 || r.status === 0) { setEngineOk(false); return; }
    setEngineOk(true); setS(r.data);
  }, []);
  useEffect(() => {
    load();
    api(base + '/captions').then((r) => r.ok && setCaps(new Map(r.data.map((c) => [c.endpoint + ':' + c.seg, c]))));
    const soon = debounce(load, 120);
    return connectEvents(base + '/events', (ev) => {
      if (ev.type === 'caption') setCaps((m) => { const n = new Map(m); n.set(ev.endpoint + ':' + ev.seg, ev); return n; });
      else if (ev.type === 'engine') { setEngineOk(ev.ok); if (ev.ok) load(); }
      else if (ev.type === 'mention') { handlers.current.onMention && handlers.current.onMention(ev.mention); soon(); }
      else if (ev.type !== 'speaking') soon();
    }, setLinkOk);
  }, [load]);
  return { S, caps, invalid, engineOk: engineOk && linkOk, reload: load, handlers };
}

function App() {
  const { S, caps, invalid, engineOk, reload, handlers } = useRemote();
  const [prefs, setPrefs] = useStored('remote', { vibrate: true, sound: false });
  const [confirmAll, setConfirmAll] = useState(false);
  const [settings, setSettings] = useState(false);
  const held = useRef(false);

  const act = useCallback(async (action) => {
    const r = await api(base + '/do', { body: { action } });
    if (r.data && r.data.ok === false && r.data.reason) toast(r.data.reason, 'bad');
    else if (!r.ok && r.data && r.data.error) toast(r.data.error, 'bad');
    reload();
    return r;
  }, [reload]);

  const me = S && S.me;
  const myMentions = S ? (S.mentions || []).filter((m) => m.target === (me && me.id)) : [];
  const calls = S && me && me.id === S.attention_target ? S.attention : [];
  const myCall = S && me ? S.attention.find((a) => a.source === me.id) : null;

  useEffect(() => {
    handlers.current.onMention = (m) => { if (me && m.target === me.id) { if (prefs.vibrate) vibrate([120, 80, 120]); if (prefs.sound) chime.mention(); } };
  }, [me && me.id, prefs.vibrate, prefs.sound]);
  const callIds = calls.map((c) => c.id).join(',');
  useEffect(() => { if (calls.length && prefs.vibrate) vibrate([250, 100, 250]); if (calls.length && prefs.sound) chime.call(); }, [callIds]);

  const pttUp = () => { if (!held.current) return; held.current = false; act('ptt:up'); };
  useEffect(() => {
    const rel = () => { if (held.current) pttUp(); };
    document.addEventListener('visibilitychange', rel); window.addEventListener('blur', rel);
    return () => { document.removeEventListener('visibilitychange', rel); window.removeEventListener('blur', rel); };
  });

  if (invalid) return html`<main class="page-pad" style="padding-top:20vh;max-width:460px;margin:0 auto"><h1>This link is no longer valid</h1><p class="muted" style="margin-top:12px">Ask the crew lead for a new one. Your headset still works.</p></main>`;
  if (!S) return html`<main class="page-pad" style="padding-top:var(--sp-6)"><div class="skeleton" style="height:320px"></div></main>`;

  const up = me.enabled && me.connected && me.audio_up;
  const gname = (id) => groupName(S.groups, id);
  const headline = !me.enabled ? 'Disabled' : !me.connected ? 'Headset not connected' : !me.audio_up ? 'Connecting voice…'
    : me.forced_mute ? 'Muted by admin' : me.muted ? 'You are muted' : me.allcall ? 'All-call' : me.private_to ? 'Private line' : me.transmitting ? (me.talk_mode === 'open' ? 'Mic open' : 'Talking') : 'Listening';
  const talkTo = me.talk.map(gname).join(' + ') || 'nobody';

  const pttDown = (e) => {
    if (me.talk_mode !== 'ptt' || held.current) return;
    e.preventDefault(); held.current = true;
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
    act('ptt:down');
  };

  const talkBtn = me.talk_mode === 'open' ? null : html`
    <${Button} class=${'big talk no-select' + (me.transmitting && !me.muted ? ' live' : '')} data-testid="talk" disabled=${!up}
      onPointerDown=${pttDown} onPointerUp=${pttUp} onPointerCancel=${pttUp} onContextMenu=${(e) => e.preventDefault()}
      onClick=${() => me.talk_mode === 'latched' && act('talk:toggle')}
      aria-pressed=${me.talk_mode === 'latched' ? String(!!me.latched_on) : undefined}>
      <${Icon} name="mic" />${me.talk_mode === 'ptt' ? 'Hold to talk' : me.latched_on ? 'Talking: tap to stop' : 'Tap to talk'}<//>`;

  return html`
    ${S.simulated && html`<div class="banner-sim" role="region" aria-label="Simulation notice">SIMULATION</div>`}
    ${!engineOk && html`<div class="banner-off" role="alert">Can't reach the intercom controller. Your headset audio is not affected, but these buttons won't work until it returns.</div>`}
    <div class=${'glow call' + (calls.length ? ' on' : '')} aria-hidden="true"></div><div class=${'glow mention' + (myMentions.length ? ' on' : '')} aria-hidden="true"></div>
    <header class="app-header"><div class="app-header-inner">
      <${Logo} />
      <div class="grow"></div>
      <${Pill} kind=${up ? 'live' : me.connected ? 'warn' : 'bad'}><${Led} kind=${up ? 'live' : me.connected ? 'warn' : 'bad'} on=${up} />${up ? 'Headset online' : me.connected ? 'No voice link' : 'Not connected'}<//>
      <${Button} variant="quiet" iconOnly icon="settings" label="Appearance and alerts" onClick=${() => setSettings(true)} />
    </div></header>
    <main class="remote page-pad" id="main">
      ${calls.map((a) => html`<${Callout} key=${a.id} kind="bad" icon="phone-call"><b>${((S.endpoints.find((e) => e.id === a.source) || {}).name) || 'Someone'}</b> is calling you.
        <div class="cluster" style="margin-top:8px"><${Button} size="sm" onClick=${async () => { await api('/api/public/attention/ack', { body: { id: a.id } }); reload(); }}>Acknowledge<//></div><//>`)}
      ${myMentions.map((m) => html`<${Callout} key=${m.id} kind="info" icon="at-sign"><b>${m.test ? 'Test: ' : ''}Someone said “${m.term}”</b><div class="small muted">${m.text}</div>
        <div class="cluster" style="margin-top:8px"><${Button} size="sm" onClick=${async () => { await api(base + '/mention/ack', { body: { id: m.id } }); reload(); }}>Got it<//></div><//>`)}

      <section class="remote-status" aria-live="polite"><div class="eyebrow">${me.name}</div><h1 class="headline" data-testid="headline">${headline}</h1>
        <div class="cluster"><${Pill} kind="accent" icon="mic">Talking to ${talkTo}<//>
          ${me.talk_mode !== 'open' || me.muted ? html`<${Pill} kind=${me.transmitting && !me.muted ? 'live' : ''} icon=${me.transmitting && !me.muted ? 'volume-2' : 'volume-x'}>${me.transmitting && !me.muted ? 'Others can hear you' : 'Others cannot hear you'}<//>` : null}</div></section>

      <section class="control-grid">
        ${talkBtn}
        <${Button} class="big mute no-select" style=${talkBtn ? undefined : 'grid-column:1 / -1'} data-testid="mute" aria-pressed=${String(!!me.muted)} disabled=${me.forced_mute}
          onClick=${() => act('mute:toggle')}><${Icon} name=${me.muted ? 'mic-off' : 'mic'} />${me.muted ? 'Unmute' : 'Mute'}<//>
        ${me.id !== S.attention_target && html`<${Button} class=${'big call no-select' + (myCall ? ' sent' : '')} data-testid="call" onClick=${() => act('attention')}>
          <${Icon} name="phone-call" />${myCall ? 'Sound has been alerted' : 'Call Sound'}${myCall ? html`<span class="small" style="font:500 .9rem var(--font-ui);letter-spacing:0;text-transform:none">Tap again only if urgent</span>` : null}<//>`}
      </section>

      <section class="stack">
        <h2>${me.can_select ? 'Talk to' : 'Your groups (set by the crew lead)'}</h2>
        <div class="groups-grid">${S.groups.filter((g) => me.talk_allowed.includes(g.id)).map((g) => html`
          <${Button} key=${g.id} class="group-btn" aria-pressed=${String(me.talk.includes(g.id))} disabled=${!me.can_select} data-testid=${'talk-' + g.id} onClick=${() => act('select:' + g.id)}>
            <${GroupTag} groups=${S.groups} id=${g.id} />${g.name}<//>`)}</div>
        <h3>Also listen to</h3>
        <div class="groups-grid">${S.groups.filter((g) => me.listen_allowed.includes(g.id)).map((g) => html`
          <${Button} key=${g.id} class="group-btn listen-btn" aria-pressed=${String(me.listen.includes(g.id))} disabled=${!me.can_select} data-testid=${'listen-' + g.id} onClick=${() => act('listen:' + g.id)}>
            <${Icon} name=${me.listen.includes(g.id) ? 'check' : 'ear'} />${g.name}<//>`)}</div>
        ${me.can_allcall && html`<${Button} class=${'lg' + (me.allcall ? ' alert-solid' : '')} data-testid="allcall" icon="megaphone" onClick=${() => me.allcall ? act('allcall:off') : setConfirmAll(true)}>${me.allcall ? 'End all-call' : 'All-call: everyone hears you'}<//>`}
      </section>

      ${me.can_private && html`<section class="stack" data-testid="private-section">
        <h2>Private line</h2>
        <p class="muted small">${me.private_to ? 'Only that person hears you. Tap them again to end it.' : 'Talk to one person; nobody else hears you. It ends by itself, or when you mute or pick a group.'}</p>
        <div class="groups-grid">${S.endpoints.filter((o) => o.id !== me.id && o.enabled).map((o) => html`
          <${Button} key=${o.id} class="group-btn" aria-pressed=${String(me.private_to === o.id)} data-testid=${'private-' + o.id} disabled=${!o.connected && me.private_to !== o.id} onClick=${() => act('private:' + o.id)}>
            <${Icon} name="lock" />${o.name}<//>`)}</div></section>`}

      <section>
        <details><summary><${Icon} name="captions" />Recent captions<${Icon} name="chevron-down" class="chev" /></summary>
          <div class="stack-sm">${[...caps.values()].sort((a, b) => a.t - b.t).slice(-6).map((c) => html`<div key=${c.endpoint + ':' + c.seg} class="small"><b>${c.name || c.endpoint}</b> <span class="faint">${clock(c.t)}</span><div>${c.text}</div></div>`)}
            ${!caps.size && html`<p class="muted small">No captions yet.</p>`}</div></details>
        <details><summary><${Icon} name="headset" />My headset buttons<${Icon} name="chevron-down" class="chev" /></summary><${Cheat} S=${S} /></details>
        ${me.dial_codes && me.dial_codes.length ? html`<details><summary><${Icon} name="phone" />Dial codes<${Icon} name="chevron-down" class="chev" /></summary>
          <table class="table"><tbody>${me.dial_codes.map((d) => html`<tr><td><span class="kbd">${(me.dial_prefix || '') + d.digit}</span></td><td>${d.does}</td></tr>`)}</tbody></table></details>` : null}
        <details><summary><${Icon} name="ear" />What the beeps mean<${Icon} name="chevron-down" class="chev" /></summary><${Beeps} /></details>
      </section>
    </main>

    <${Dialog} open=${confirmAll} onClose=${() => setConfirmAll(false)} title="Start an all-call?" width=${440}
      footer=${html`<${Button} onClick=${() => setConfirmAll(false)}>Cancel<//><${Button} variant="primary" data-testid="confirm-allcall" onClick=${() => { setConfirmAll(false); act('allcall:on'); }}>Start all-call<//>`}>
      <p>Everyone connected will hear you, whatever group they are in.</p><//>
    <${Dialog} open=${settings} onClose=${() => setSettings(false)} title="Appearance and alerts" width=${480}>
      <div class="stack-lg"><${ThemeMenu} /><a class="btn" href="/help"><${Icon} name="life-buoy" /> Help and tips</a>
        <div class="stack"><${Switch} checked=${prefs.vibrate} onChange=${(v) => { setPrefs({ ...prefs, vibrate: v }); if (v) vibrate(100); }}>Vibrate for calls and name mentions<//>
        <${Switch} checked=${prefs.sound} onChange=${(v) => { setPrefs({ ...prefs, sound: v }); if (v) chime.mention(); }}>Play a chime on this device<//></div></div><//>
    <${Toasts} />`;
}

function Cheat({ S }) {
  const c = S.cheatsheet;
  return html`<div class="stack-sm"><p class="muted small">${c.note}</p>
    ${c.mapped.length ? html`<table class="table"><tbody>${c.mapped.map((r) => html`<tr><td>${r.button}</td><td>${r.does}</td><td class="small ${r.verified ? '' : 'faint'}">${r.verified ? 'confirmed' : 'not yet confirmed'}</td></tr>`)}</tbody></table>`
      : html`<p class="muted">No headset buttons are set up for you. Use the buttons on this page.</p>`}
    ${c.local_only.map((t) => html`<${Callout} icon="info">${t}<//>`)}
    ${c.unmapped_seen.length ? html`<p class="small faint">Other buttons the system has seen from your headset (nothing assigned): ${c.unmapped_seen.map((u) => u.button).join(', ')}</p>` : null}</div>`;
}

function Beeps() {
  const rows = [['One beep', 'You now talk to the first group'], ['Two beeps', 'You now talk to the second group'], ['Falling two tones', 'Your microphone is muted'], ['Rising two tones', 'Your microphone is on'],
    ['Rising three tones', 'All-call is on'], ['Falling three tones', 'All-call ended'], ['Two soft pings', 'Someone said your name'], ['Low double buzz', 'That was not allowed']];
  return html`<table class="table"><tbody>${rows.map(([a, b]) => html`<tr><td><b>${a}</b></td><td>${b}</td></tr>`)}</tbody></table>`;
}

render(html`<${App} />`, document.getElementById('app'));

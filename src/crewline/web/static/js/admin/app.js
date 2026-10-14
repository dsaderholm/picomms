import { html, render, useState, useEffect, useMemo, api, ago, useNow } from '/static/js/lib/core.js';
import { ConfirmHost, Icon, Button, Pill, Led, Dialog, Toasts, Logo, Field, Panel, Callout, ThemeMenu, Switch, toast } from '/static/js/lib/ui.js';
import { Ctx, useAdminData, useAdmin } from '/static/js/admin/data.js';
import { Overview } from '/static/js/admin/overview.js';
import { Setup } from '/static/js/admin/setup.js';
import { Devices } from '/static/js/admin/devices.js';
import { People } from '/static/js/admin/people.js';
import { Groups } from '/static/js/admin/groups.js';
import { DialCodes } from '/static/js/admin/dialcodes.js';
import { AlertsPage } from '/static/js/admin/alerts.js';
import { CaptionsPage } from '/static/js/admin/captions.js';
import { NetworkPage } from '/static/js/admin/network.js';
import { Diagnostics } from '/static/js/admin/diagnostics.js';
import { SettingsPage } from '/static/js/admin/settings.js';
import { PrintSheets } from '/static/js/admin/print.js';

const PAGES = [
  ['overview', 'Overview', 'layout-dashboard', Overview],
  ['setup', 'Setup assistant', 'rocket', Setup],
  ['devices', 'Devices', 'bluetooth', Devices],
  ['people', 'People', 'users', People],
  ['groups', 'Groups', 'radio', Groups],
  ['dial', 'Dial codes', 'phone', DialCodes],
  ['alerts', 'Alerts', 'bell', AlertsPage],
  ['captions', 'Captions', 'captions', CaptionsPage],
  ['network', 'Network', 'wifi', NetworkPage],
  ['diagnostics', 'Diagnostics', 'activity', Diagnostics],
  ['settings', 'Settings and backup', 'settings', SettingsPage],
  ['print', 'Print sheets', 'printer', PrintSheets],
];

const routeFromHash = () => (location.hash.replace(/^#\/?/, '') || 'overview');

function Login() {
  const { setAuthed, refresh } = useAdmin();
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    const r = await api('/api/login', { body: { password: pw } });
    setBusy(false);
    if (r.ok) { setPw(''); await refresh(); } else setErr(r.data.error || 'That did not work.');
  };
  return html`<main id="main" class="page-pad" style="min-height:100dvh;display:grid;place-items:center">
    <div class="panel stack" style="width:min(420px,100%)">
      <${Logo} /><h1>Admin sign-in</h1>
      <p class="muted">Only the crew lead needs this. Everyone else uses the dashboard or their own remote link.</p>
      <form class="stack" onSubmit=${submit}>
        <${Field} id="pw" label="Password" error=${err}><input id="pw" class="input" type="password" autocomplete="current-password" value=${pw} onInput=${(e) => setPw(e.target.value)} autofocus /><//>
        <${Button} variant="primary" type="submit" disabled=${busy || !pw}>Sign in<//>
      </form>
      <p class="faint small">First time? The starting password was printed by the installer and saved in <span class="mono">/var/lib/crewline/FIRST-RUN-ADMIN-PASSWORD.txt</span>.</p>
    </div></main>`;
}

function ShowModeControl({ compact }) {
  const { S, call, locked } = useAdmin();
  const [confirm, setConfirm] = useState(false);
  const [problems, setProblems] = useState(null);
  const turnOn = async () => {
    const r = await api('/api/admin/readiness');
    const fails = (r.data || []).filter((c) => c.level === 'fail');
    if (fails.length) { setProblems(fails); setConfirm(true); } else call('/config/show_mode', { on: true }, 'Show mode on. Settings are locked.');
  };
  const toggle = () => (locked ? setConfirm(true) : turnOn());
  return html`<div class=${compact ? '' : 'lockbar'}>
    <${Switch} checked=${locked} onChange=${toggle} id="show-mode-switch"><span class="nowrap">${locked ? 'Show mode on' : 'Show mode off'}</span><//>
    <${Dialog} open=${confirm} onClose=${() => { setConfirm(false); setProblems(null); }} title=${locked ? 'End show mode?' : 'Lock anyway?'} width=${520}
      footer=${html`<${Button} onClick=${() => { setConfirm(false); setProblems(null); }}>Cancel<//>
        <${Button} variant=${locked ? 'primary' : 'danger'} data-testid="confirm-show-mode" onClick=${async () => { setConfirm(false); setProblems(null); await call('/config/show_mode', { on: !locked }, locked ? 'Settings unlocked.' : 'Show mode on. Settings are locked.'); }}>${locked ? 'Unlock settings' : 'Lock settings'}<//>`}>
      ${locked ? html`<p>Unlocking lets you pair headsets, change groups and edit settings. Talking and muting are not affected either way.</p>`
        : html`<${Callout} kind="bad" icon="triangle-alert"><b>The readiness check found problems:</b><ul>${(problems || []).map((p) => html`<li><b>${p.name}:</b> ${p.msg}</li>`)}</ul><//>
          <p style="margin-top:12px">You can still lock settings, but fix these first if you can.</p>`}<//></div>`;
}

function Shell({ page, children }) {
  const { S, engineOk } = useAdmin();
  const [menu, setMenu] = useState(false);
  const alerts = S ? S.attention.filter((a) => a.active).length + (S.mentions || []).length : 0;
  return html`<div class="admin">
    <nav class="admin-nav" aria-label="Admin sections">
      <div class="admin-nav-top"><${Logo} site=${S && S.site_name} /><div class="grow"></div>
        <a class="btn quiet icon sm" href="/" aria-label="Open the crew dashboard" title="Crew dashboard"><${Icon} name="monitor" /></a></div>
      <div class="nav-scroll">${PAGES.map(([id, label, icon]) => html`<a key=${id} class="nav-item" href=${'#/' + id} aria-current=${page === id ? 'page' : undefined} data-testid=${'nav-' + id}>
        <${Icon} name=${icon} />${label}${id === 'alerts' && alerts ? html`<span class="count">${alerts}</span>` : null}</a>`)}</div>
      <div class="nav-foot"><${ShowModeControl} /><${Button} size="sm" variant="quiet" icon="door-open" onClick=${async () => { await api('/api/logout', { body: {} }); location.reload(); }}>Sign out<//></div>
    </nav>
    <div>
      ${S && S.simulated && html`<div class="banner-sim" role="region" aria-label="Simulation notice">SIMULATION: nothing here comes from real hardware</div>`}
      ${!engineOk && html`<div class="banner-off" role="alert">The intercom controller is offline. Audio keeps running; settings cannot change until it returns (it restarts itself).</div>`}
      <div class="admin-mobile-bar page-pad no-print"><${ShowModeControl} compact /><${Button} size="sm" variant="quiet" onClick=${async () => { await api('/api/logout', { body: {} }); location.reload(); }}>Sign out<//></div>
      <main id="main" class="admin-main">${children}</main>
    </div><${ConfirmHost} /><${Toasts} /></div>`;
}

function App() {
  const data = useAdminData();
  const [page, setPage] = useState(routeFromHash());
  useEffect(() => { const f = () => setPage(routeFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  const entry = PAGES.find((p) => p[0] === page) || PAGES[0];
  useEffect(() => { document.title = entry[1] + ' · Crewline Admin'; }, [entry]);

  if (data.authed === null) return html`<div class="page-pad" style="padding-top:20vh"><div class="skeleton" style="height:120px;max-width:420px;margin:0 auto"></div></div>`;
  if (data.authed === false) return html`<${Ctx.Provider} value=${data}><${Login} /><${Toasts} /><//>`;
  const Page = entry[3];
  return html`<${Ctx.Provider} value=${data}><${Shell} page=${entry[0]}>${data.S ? html`<${Page} />` : html`<div class="skeleton" style="height:240px"></div>`}<//><//>`;
}

render(html`<${App} />`, document.getElementById('app'));

import { html, useState, api } from '/static/js/lib/core.js';
import { ask, Icon, Button, Pill, Panel, Callout, Field, ThemeMenu, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

export function SettingsPage() {
  const { S, call, locked, refresh } = useAdmin();
  const [site, setSite] = useState(S.site_name || '');
  const [cur, setCur] = useState(''); const [pw1, setPw1] = useState(''); const [pw2, setPw2] = useState('');
  const [file, setFile] = useState(null);
  const pwErr = pw1 && pw1.length < 8 ? 'Use at least 8 characters.' : pw2 && pw1 !== pw2 ? 'The two passwords differ.' : '';
  const changePw = async (e) => {
    e.preventDefault();
    const r = await api('/api/admin/password', { body: { current: cur, new: pw1 } });
    if (r.ok) { toast('Password changed.'); setCur(''); setPw1(''); setPw2(''); refresh(); } else toast(r.data.error || 'That did not work.', 'bad');
  };
  return html`<div class="stack-lg">
    <${PageHead} title="Settings and backup">Your site name, password, how this screen looks, and a copy of everything.<//>
    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));align-items:start">
      <${Panel} id="site" title="This site">
        <div class="stack"><${LockNote} /><${Field} id="site-name" label="Name shown on the dashboard" hint="For example: ICS Tech Crew"><input id="site-name" class="input" value=${site} onInput=${(e) => setSite(e.target.value)} maxlength="60" disabled=${locked} data-testid="site-name" /><//>
          <div><${Button} variant="primary" disabled=${locked || site === (S.site_name || '')} onClick=${() => call('/config/site_name', { name: site }, 'Saved')}>Save name<//></div></div><//>
      <${Panel} id="appearance" title="Appearance on this device"><${ThemeMenu} /><//>
      <${Panel} id="password" title="Admin password">
        <form class="stack" onSubmit=${changePw}><${Field} id="pw-cur" label="Current password"><input id="pw-cur" class="input" type="password" autocomplete="current-password" value=${cur} onInput=${(e) => setCur(e.target.value)} /><//>
          <${Field} id="pw-new" label="New password" error=${pwErr && pw1.length < 8 ? pwErr : ''}><input id="pw-new" class="input" type="password" autocomplete="new-password" value=${pw1} onInput=${(e) => setPw1(e.target.value)} /><//>
          <${Field} id="pw-new2" label="New password again" error=${pw1.length >= 8 ? pwErr : ''}><input id="pw-new2" class="input" type="password" autocomplete="new-password" value=${pw2} onInput=${(e) => setPw2(e.target.value)} /><//>
          <div><${Button} variant="primary" type="submit" disabled=${!cur || pw1.length < 8 || pw1 !== pw2}>Change password<//></div></form><//>
      <${Panel} id="backup" title="Back up and restore">
        <div class="stack"><p class="muted">One file with your groups, people, dial codes, hotspot and caption settings. It includes the hotspot password, so store it like a password. It does not include Bluetooth pairings: after restoring onto new hardware, headsets must be paired again.</p>
          <div class="cluster"><a class="btn primary" href="/api/admin/config/export" data-testid="backup-download"><${Icon} name="download" />Download backup</a></div>
          <${Field} id="restore" label="Restore from a backup file"><input id="restore" class="input" type="file" accept=".json,application/json" disabled=${locked} onChange=${(e) => setFile(e.target.files[0] || null)} /><//>
          <div><${Button} icon="upload" disabled=${locked || !file} onClick=${async () => { if (await ask({ title: 'Replace all settings?', body: 'Everything is replaced with the contents of this file.', confirm: 'Restore', danger: true })) { await call('/config/restore', { json: await file.text() }, 'Restored'); } }}>Restore<//></div>
          <p class="faint small">The box also keeps its last 20 automatic versions in /var/lib/crewline/backups/.</p></div><//></div></div>`;
}

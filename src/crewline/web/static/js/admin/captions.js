import { html, useState } from '/static/js/lib/core.js';
import { Icon, Button, Pill, Panel, Callout, Field, Check, Switch, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

export function CaptionsPage() {
  const { S, call, locked } = useAdmin();
  const c = S.captions;
  const [server, setServer] = useState(c.server_cfg || '');
  const [terms, setTerms] = useState((c.highlight_terms || []).join(', '));
  const [retain, setRetain] = useState(!!c.retain_transcripts);
  const state = !c.enabled ? ['', 'Not set up'] : c.connected ? ['live', 'Connected'] : ['warn', 'Caption computer unreachable'];
  const save = () => call('/config/captions', { server: server.trim(), highlight_terms: terms.split(',').map((t) => t.trim()).filter(Boolean), retain_transcripts: retain }, 'Saved');
  return html`<div class="stack-lg">
    <${PageHead} title="Captions" actions=${html`<${Button} variant="primary" onClick=${save} disabled=${locked}>Save<//>`}>Live captions come from a separate computer. If it is slow, off or unplugged, the intercom keeps working normally.<//>
    <${LockNote} />
    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));align-items:start">
      <${Panel} id="cap-status" eyebrow="Status" title="Caption computer">
        <div class="stack"><div class="cluster"><${Pill} kind=${state[0]} icon="captions">${state[1]}<//>${c.engine && html`<span class="muted small">engine: ${c.engine}</span>`}</div>
          <dl class="kv"><dt>Last result took</dt><dd>${c.last_result_ms == null ? 'unknown' : c.last_result_ms + ' ms'}</dd><dt>Audio skipped</dt><dd>${c.dropped_kb || 0} KB (while the computer was away or slow)</dd><dt>Last error</dt><dd>${c.last_error || 'none'}</dd></dl>
          <${Field} id="cap-server" label="Caption computer address" hint="Example: 192.168.1.50:7070. Leave empty to turn captions off."><input id="cap-server" class="input mono" placeholder="192.168.1.50:7070" value=${server} onInput=${(e) => setServer(e.target.value)} disabled=${locked} /><//></div><//>
      <${Panel} id="cap-options" eyebrow="Options" title="Highlights and privacy">
        <div class="stack"><${Field} id="cap-terms" label="Always highlight these words" hint="Separate with commas. To alert a person when their name is heard, use Name alerts on the People page."><input id="cap-terms" class="input" value=${terms} onInput=${(e) => setTerms(e.target.value)} disabled=${locked} /><//>
          <${Callout} kind=${retain ? 'warn' : 'info'} icon="shield-check"><${Switch} checked=${retain} disabled=${locked} onChange=${setRetain}>Keep transcripts on this appliance (off by default)<//>
            <p class="small muted" style="margin-top:6px">Turning this on stores what people say as text files. Check your school's rules and tell the crew first. Audio is never stored.</p><//></div><//></div></div>`;
}

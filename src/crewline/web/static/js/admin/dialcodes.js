import { html, useState, api, groupName } from '/static/js/lib/core.js';
import { Icon, Button, Panel, Callout, Field, Dialog, Pill, toast } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

const KEYS = [['1', ''], ['2', 'ABC'], ['3', 'DEF'], ['4', 'GHI'], ['5', 'JKL'], ['6', 'MNO'], ['7', 'PQRS'], ['8', 'TUV'], ['9', 'WXYZ'], ['*', ''], ['0', ''], ['#', '']];

export function actionLabel(a, groups) {
  if (!a) return 'Nothing';
  const [k, arg] = a.split(':');
  return ({ 'mute:toggle': 'Mute / unmute', 'mute:on': 'Mute', 'mute:off': 'Unmute', 'allcall:toggle': 'All-call on/off', 'allcall:on': 'All-call on', 'allcall:off': 'All-call off',
    'talk:toggle': 'Latched talk', attention: 'Call Sound', status: 'Status beep' }[a]) || (k === 'select' ? 'Talk to ' + groupName(groups, arg) : k === 'listen' ? 'Hear ' + groupName(groups, arg) : a);
}

export function DialCodes() {
  const { S, call, locked } = useAdmin();
  const d = S.dtmf;
  const [commands, setCommands] = useState({ ...d.commands });
  const [prefix, setPrefix] = useState(d.prefix || '');
  const [ac, setAc] = useState(d.allcall_timeout_s);
  const [minTone, setMinTone] = useState(d.min_tone_ms);
  const [hold, setHold] = useState(d.gate_hold_ms);
  const [editKey, setEditKey] = useState(null);
  const acts = [['', 'Nothing'], ['mute:toggle', 'Mute / unmute'], ['allcall:toggle', 'All-call on/off'], ['attention', 'Call Sound'], ['status', 'Status beep'], ['talk:toggle', 'Latched talk on/off'],
    ...S.groups.map((g) => ['select:' + g.id, 'Talk to ' + g.name]), ...S.groups.map((g) => ['listen:' + g.id, 'Hear ' + g.name + ' on/off'])];
  const sound = S.endpoints.find((e) => e.tone_control);
  const dirty = JSON.stringify(commands) !== JSON.stringify(d.commands) || prefix !== (d.prefix || '') || +ac !== d.allcall_timeout_s || +minTone !== d.min_tone_ms || +hold !== d.gate_hold_ms;
  const save = () => call('/config/dtmf', { commands, prefix: prefix.trim(), allcall_timeout_s: +ac, min_tone_ms: +minTone, gate_hold_ms: +hold }, 'Dial codes saved');
  const tryIt = async (digit) => {
    const a = commands[digit]; if (!a || !sound) return;
    const r = await call('/control', { endpoint: sound.id, action: a, source: 'admin' });
    if (r.data && r.data.ok) toast(`Sent "${actionLabel(a, S.groups)}" to ${sound.name}`);
  };
  return html`<div class="stack-lg">
    <${PageHead} title="Dial codes" actions=${html`<${Button} variant="primary" onClick=${save} disabled=${locked || !dirty} data-testid="dial-save">Save dial codes<//>`}>What each key on the rotary or desk phone does. Tap a key to change it.<//>
    <${LockNote} />
    <${Callout} kind="warn" icon="triangle-alert">These are proposals until they are tried on the real phone. The Cell2Jack may use <span class="kbd">#</span> and <span class="kbd">*</span> for its own functions, so avoid them until its manual is checked.<//>
    <div class="dial-layout">
      <${Panel} id="keypad" eyebrow="Keypad" title="Keys">
        <div class="keypad" role="group" aria-label="Keypad">${KEYS.map(([k, letters]) => html`<button key=${k} type="button" class=${'key' + (commands[k] ? ' set' : '')} data-testid=${'key-' + k} disabled=${locked} onClick=${() => setEditKey(k)}>
          <span class="digit">${k}</span>${' '}<span class="what">${actionLabel(commands[k], S.groups)}</span></button>`)}</div><//>
      <div class="stack">
        <${Panel} id="rules" title="Rules">
          <div class="stack"><${Field} id="dt-prefix" label="Required first key (optional)" hint="With a first key such as * every command is two keys, for example * then 1. It makes accidental triggers by speech practically impossible."><input id="dt-prefix" class="input" maxlength="1" value=${prefix} onInput=${(e) => setPrefix(e.target.value)} disabled=${locked} style="max-width:6em" /><//>
            <${Field} id="dt-ac" label="All-call ends by itself after (seconds, 0 = never)"><input id="dt-ac" class="input" type="number" min="0" value=${ac} onInput=${(e) => setAc(e.target.value)} disabled=${locked} style="max-width:10em" /><//>
            <div class="form-grid"><${Field} id="dt-min" label="Shortest tone that counts (ms)"><input id="dt-min" class="input" type="number" min="20" max="200" value=${minTone} onInput=${(e) => setMinTone(e.target.value)} disabled=${locked} /><//>
              <${Field} id="dt-hold" label="Keep the mic closed after a tone (ms)"><input id="dt-hold" class="input" type="number" min="0" max="1000" value=${hold} onInput=${(e) => setHold(e.target.value)} disabled=${locked} /><//></div></div><//>
        <${Panel} id="tips" title="Good to know">
          <ul class="stack-sm" style="margin:0;padding-left:20px"><li>While a command tone is present, your microphone is held closed so the tone is not broadcast to the crew.</li>
            <li>Every command plays a beep only in <b>your</b> ear: one beep for the first group, two for the second, and so on.</li>
            <li>Not sure what a key does? <b>Try it</b> sends the action to ${sound ? sound.name : 'the phone'} without dialling.</li></ul><//></div></div>
    ${editKey && html`<${Dialog} open=${true} onClose=${() => setEditKey(null)} title=${`Key ${editKey}`} width=${460}
      footer=${html`${commands[editKey] && html`<${Button} onClick=${() => tryIt(editKey)} disabled=${!sound}>Try it<//>`}<${Button} variant="primary" onClick=${() => setEditKey(null)}>Done<//>`}>
      <${Field} id="key-action" label="When this key is dialled"><select id="key-action" class="select" value=${commands[editKey] || ''} data-testid="key-action" onChange=${(e) => setCommands({ ...commands, [editKey]: e.target.value })}>${acts.map(([v, t]) => html`<option value=${v}>${t}</option>`)}</select><//><//>`}</div>`;
}

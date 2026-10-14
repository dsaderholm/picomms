import { html, useState } from '/static/js/lib/core.js';
import { ask, Icon, Button, Panel, GroupTag, Dialog, Field, Empty } from '/static/js/lib/ui.js';
import { useAdmin, LockNote } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';

function GroupDialog({ group, onClose }) {
  const { S, call } = useAdmin();
  const isNew = !group.id;
  const [name, setName] = useState(group.name || '');
  const [beeps, setBeeps] = useState(group.cue_beeps || Math.min(5, S.groups.length + 1));
  const save = async () => {
    const id = isNew ? name.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 20) : group.id;
    const r = await call('/config/group', { id, name: name.trim(), cue_beeps: +beeps }, 'Saved');
    if (r.ok && r.data.ok !== false) onClose();
  };
  return html`<${Dialog} open=${true} onClose=${onClose} title=${isNew ? 'Add a group' : 'Edit group'} width=${480}
    footer=${html`<${Button} onClick=${onClose}>Cancel<//><${Button} variant="primary" onClick=${save} disabled=${!name.trim()} data-testid="group-save">Save<//>`}>
    <div class="stack"><${Field} id="g-name" label="Name"><input id="g-name" class="input" value=${name} onInput=${(e) => setName(e.target.value)} data-testid="group-name" autofocus /><//>
      <${Field} id="g-beeps" label="Beeps in the headset when someone switches to this group" hint="Each group should have a different number so people can tell them apart by ear."><input id="g-beeps" class="input" type="number" min="1" max="5" value=${beeps} onInput=${(e) => setBeeps(e.target.value)} /><//></div><//>`;
}

export function Groups() {
  const { S, call, locked } = useAdmin();
  const [edit, setEdit] = useState(null);
  return html`<div class="stack-lg"><${PageHead} title="Groups" actions=${html`<${Button} variant="primary" icon="plus" disabled=${locked} onClick=${() => setEdit({})}>Add group<//>`}>
    Groups are channels, like Tech and Stage. Each person chooses who they talk to and which groups they hear.<//>
    <${LockNote} />
    <${Panel} flush id="groups">${S.groups.length ? html`<ul class="rowlist">${S.groups.map((g) => html`<li key=${g.id} class="person-row">
      <${GroupTag} groups=${S.groups} id=${g.id} /><div class="grow"><b>${g.name}</b><div class="xs faint">${S.endpoints.filter((e) => e.home_talk.includes(g.id)).length} start talking here · ${S.endpoints.filter((e) => e.home_listen.includes(g.id)).length} start listening</div></div>
      <span class="small muted">${g.cue_beeps} ${g.cue_beeps === 1 ? 'beep' : 'beeps'}</span>
      <div class="cluster"><${Button} size="sm" disabled=${locked} onClick=${() => setEdit(g)}>Edit<//>
        <${Button} size="sm" variant="danger" disabled=${locked} onClick=${async () => { if (await ask({ title: `Delete ${g.name}?`, body: 'People lose this group. This cannot be undone.', confirm: 'Delete', danger: true })) call('/config/group_delete', { id: g.id }, 'Deleted'); }}>Delete<//></div></li>`)}</ul>`
      : html`<div style="padding:var(--sp-5)"><${Empty} icon="radio" title="No groups">Add a group to get started.<//></div>`}<//>
    ${edit && html`<${GroupDialog} group=${edit} onClose=${() => setEdit(null)} />`}</div>`;
}

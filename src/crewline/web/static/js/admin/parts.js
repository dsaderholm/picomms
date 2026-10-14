// Small shared pieces for the admin pages.
import { html, useState, useEffect, useCallback, api } from '/static/js/lib/core.js';
import { Icon, Button } from '/static/js/lib/ui.js';
import { useAdmin } from '/static/js/admin/data.js';

export function PageHead({ title, children, actions }) {
  return html`<div class="page-head"><div><h1>${title}</h1>${children && html`<p>${children}</p>`}</div>${actions && html`<div class="cluster no-print">${actions}</div>`}</div>`;
}

export function useReadiness() {
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async () => {
    setBusy(true);
    const r = await api('/api/admin/readiness');
    setBusy(false);
    if (r.ok) setList(r.data);
    return r.data;
  }, []);
  useEffect(() => { run(); }, [run]);
  const worst = !list ? null : list.some((c) => c.level === 'fail') ? 'fail' : list.some((c) => c.level === 'warn') ? 'warn' : 'ok';
  return { list, run, busy, worst };
}

export const LEVEL_ICON = { ok: 'circle-check', warn: 'triangle-alert', fail: 'circle-alert', info: 'info' };

export function CheckList({ list }) {
  const order = { fail: 0, warn: 1, ok: 2, info: 3 };
  const sorted = [...list].sort((a, b) => order[a.level] - order[b.level]);
  return html`<div role="list">${sorted.map((c) => html`<div role="listitem" class="check-row">
    <${Icon} name=${LEVEL_ICON[c.level]} class=${c.level} label=${{ ok: 'OK', warn: 'Warning', fail: 'Problem', info: 'Note' }[c.level]} /><b>${c.name}</b><span class="check-msg muted">${c.msg}</span></div>`)}</div>`;
}

export function networkUrls(S) {
  const urls = [location.origin + '/'];
  const net = S.network || {};
  return { dashboard: location.origin + '/', hotspot: net.ap_active ? net.ap_ssid : '' };
}

export const TALK_MODES = [['open', 'Open mic: always on unless muted'], ['latched', 'Latched: tap to talk, tap to stop'], ['ptt', 'Push-to-talk: hold to talk']];
export const modeLabel = (m) => ({ open: 'Open mic', latched: 'Latched talk', ptt: 'Push-to-talk' }[m] || m);

export function endpointBody(e, over = {}) {
  // Rebuild the config payload for an endpoint from its published state (used by quick edits).
  return {
    id: e.id, name: e.name, kind: e.kind, address: e.address, enabled: e.enabled, listen: e.home_listen, talk: e.home_talk,
    listen_allowed: e.listen_allowed, talk_allowed: e.talk_allowed, can_allcall: e.can_allcall, can_private: !!e.can_private, can_select: e.can_select,
    select_scope: e.select_scope, talk_mode: e.talk_mode, forced_mute: e.forced_mute, tone_control: e.tone_control,
    captions: e.captions, buttons: e.buttons || {}, mention_terms: e.mention_terms || [], mention_cue: e.mention_cue, ...over,
  };
}

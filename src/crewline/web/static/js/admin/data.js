// Admin data layer: one state object kept fresh by server-sent events, plus helpers for calling the API.
import { html, createContext, useContext, useState, useEffect, useCallback, useRef, api, connectEvents, debounce } from '/static/js/lib/core.js';
import { toast } from '/static/js/lib/ui.js';

export const Ctx = createContext(null);
export const useAdmin = () => useContext(Ctx);

export function useAdminData() {
  const [S, setS] = useState(null);
  const [authed, setAuthed] = useState(null);       // null = unknown, false = show login
  const [engineOk, setEngineOk] = useState(true);
  const authedRef = useRef(null);
  authedRef.current = authed;

  const refresh = useCallback(async () => {
    const r = await api('/api/admin/state');
    if (r.status === 401) { setAuthed(false); return null; }
    if (r.status === 503 || r.status === 0) { setEngineOk(false); return null; }
    setEngineOk(true); setAuthed(true); setS(r.data);
    return r.data;
  }, []);

  // Ask /api/me first so a signed-out visitor sees the login form without a failed request in the console.
  useEffect(() => {
    api('/api/me').then((r) => {
      if (r.data && r.data.admin === false) setAuthed(false);
      else refresh();
    });
  }, [refresh]);
  useEffect(() => {
    if (!authed) return;
    const soon = debounce(refresh, 250);
    return connectEvents('/api/public/events', (ev) => {
      if (['state', 'config', 'attention', 'attention_ack', 'mention', 'mention_ack', 'engine', 'announce'].includes(ev.type)) soon();
    }, () => {});
  }, [authed, refresh]);
  // periodic refresh keeps levels, adapters and connection state honest even if an event is missed
  useEffect(() => {
    if (!authed) return;
    const t = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
    return () => clearInterval(t);
  }, [authed, refresh]);

  // POST to the admin API. Shows a toast on failure (and on success when okMsg is given); always refreshes.
  const call = useCallback(async (path, body, okMsg) => {
    const r = await api('/api/admin' + path, { body: body === undefined ? {} : body });
    if (r.status === 401) { setAuthed(false); return r; }
    const d = r.data || {};
    if (!r.ok || d.ok === false) toast(d.error || d.message || d.reason || 'That did not work.', 'bad');
    else if (okMsg) toast(okMsg);
    refresh();
    return r;
  }, [refresh]);
  const get = useCallback((path) => api('/api/admin' + path), []);

  return { S, authed, setAuthed, engineOk, refresh, call, get, locked: !!(S && S.show_mode) };
}

export function LockNote() {
  const { locked } = useAdmin();
  if (!locked) return null;
  return html`<div class="callout warn" role="status"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <div><b>Show mode is on.</b> Settings are locked so nothing changes by accident. Talking, muting, switching groups and calling Sound still work for everyone. Turn show mode off to change settings.</div></div>`;
}

// Shared foundation: Preact + htm (vendored, no build step), API/SSE helpers, storage, theme.
import { h, render, Fragment, createContext } from '/static/vendor/preact.mjs';
import { useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect, useReducer, useContext } from '/static/vendor/hooks.mjs';
import htm from '/static/vendor/htm.mjs';

export const html = htm.bind(h);
export { h, render, Fragment, createContext, useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect, useReducer, useContext };

// ---- storage (every access guarded: private windows and blocked storage must not break the page)
export const storage = {
  get(key, fallback) { try { const v = localStorage.getItem('crewline.' + key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem('crewline.' + key, JSON.stringify(value)); } catch (e) { /* ignore */ } },
};
export function useStored(key, initial) {
  const [v, setV] = useState(() => storage.get(key, initial));
  const set = useCallback((next) => { setV(next); storage.set(key, next); }, [key]);
  return [v, set];
}

// ---- HTTP
export async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: { 'X-Requested-With': 'crewline' }, credentials: 'same-origin' };
  if (opts.body !== undefined) { o.method = opts.method || 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  if (opts.pin) o.headers['X-Viewer-Pin'] = opts.pin;
  let r;
  try { r = await fetch(path, o); } catch (e) { return { ok: false, status: 0, data: { error: 'Cannot reach the appliance. Check the network connection.' } }; }
  let data = null;
  try { data = await r.json(); } catch (e) { data = {}; }
  return { ok: r.ok, status: r.status, data };
}

// Server-sent events with automatic reconnect and a connection flag.
export function connectEvents(url, onEvent, onStatus) {
  let es, delay = 600, stopped = false, timer = null;
  const open = () => {
    if (stopped) return;
    es = new EventSource(url);
    es.onopen = () => { delay = 600; onStatus && onStatus(true); };
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { /* ignore malformed */ } };
    es.onerror = () => { onStatus && onStatus(false); es.close(); timer = setTimeout(open, delay); delay = Math.min(delay * 2, 8000); };
  };
  open();
  return () => { stopped = true; clearTimeout(timer); es && es.close(); };
}

export function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ---- time
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), intervalMs); return () => clearInterval(t); }, [intervalMs]);
  return now;
}
export function ago(ts, now = Date.now()) {
  const s = Math.max(0, Math.round(now / 1000 - ts));
  if (s < 5) return 'just now';
  if (s < 60) return s + ' s ago';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  return Math.floor(s / 3600) + ' h ago';
}
export const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });

// ---- groups: colour index is stable per group id order
export const groupIdx = (groups, id) => Math.max(0, groups.findIndex((g) => g.id === id)) % 6;
export const groupName = (groups, id) => (groups.find((g) => g.id === id) || {}).name || id;

// ---- theme (theme.js applied the stored value before first paint; this changes it later)
export const THEMES = [['dark', 'Dark'], ['night', 'Night'], ['light', 'Light'], ['auto', 'Auto']];
export const FLASH = [['strong', 'Strong'], ['subtle', 'Subtle'], ['off', 'Border only']];
const THEME_COLOR = { dark: '#0b0f14', night: '#080202', light: '#f2f5f9', auto: '#0b0f14' };
export function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t); storage.set('theme', t);
  try { localStorage.setItem('crewline.theme', t); } catch (e) { /* ignore */ }
  const m = document.querySelector('meta[name="theme-color"]'); if (m) m.setAttribute('content', THEME_COLOR[t] || THEME_COLOR.dark);
}
export function setFlash(f) { document.documentElement.setAttribute('data-flash', f); try { localStorage.setItem('crewline.flash', f); } catch (e) { /* ignore */ } }
export const currentTheme = () => document.documentElement.getAttribute('data-theme') || 'dark';
export const currentFlash = () => document.documentElement.getAttribute('data-flash') || 'strong';

// ---- attention aids: sound and vibration (both are opt-in and may be refused by the browser)
let _ac;
export function beep(freq = 880, ms = 150, gain = 0.12) {
  try {
    _ac = _ac || new (window.AudioContext || window.webkitAudioContext)();
    if (_ac.state === 'suspended') _ac.resume();
    const o = _ac.createOscillator(), g = _ac.createGain();
    o.frequency.value = freq; g.gain.value = gain; o.connect(g); g.connect(_ac.destination);
    o.start(); o.stop(_ac.currentTime + ms / 1000);
  } catch (e) { /* no audio */ }
}
export const chime = { call: () => { beep(740, 130); setTimeout(() => beep(988, 220), 170); }, mention: () => { beep(1318, 80, 0.09); setTimeout(() => beep(1760, 120, 0.09), 110); } };
export function vibrate(pattern) {
  try { if (navigator.vibrate && navigator.userActivation && navigator.userActivation.hasBeenActive) navigator.vibrate(pattern); } catch (e) { /* ignore */ }
}

// ---- tiny event bus for toasts
const toastListeners = new Set();
export const onToast = (fn) => { toastListeners.add(fn); return () => toastListeners.delete(fn); };
export const toast = (message, kind = 'ok') => toastListeners.forEach((fn) => fn({ id: Math.random(), message, kind }));

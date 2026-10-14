// Component library: small, accessible building blocks used by every page.
import {
  html, h, useState, useEffect, useRef, useCallback, onToast, toast, groupIdx, groupName,
  THEMES, FLASH, setTheme, setFlash, currentTheme, currentFlash,
} from '/static/js/lib/core.js';
import { ICONS } from '/static/js/lib/icons.js';

export { toast };

export function Icon({ name, label, size, class: cls }) {
  const nodes = ICONS[name] || [];
  const style = size ? `width:${size}px;height:${size}px` : undefined;
  return h('svg', { class: 'icon' + (cls ? ' ' + cls : ''), viewBox: '0 0 24 24', 'aria-hidden': label ? undefined : 'true', role: label ? 'img' : undefined, 'aria-label': label, style },
    nodes.map(([tag, attrs], i) => h(tag, { key: i, ...attrs })));
}

export function Button({ children, variant, size, icon, iconOnly, label, block, class: cls, ...rest }) {
  const c = ['btn', variant, size, iconOnly && 'icon', block && 'block', cls].filter(Boolean).join(' ');
  return html`<button type="button" class=${c} aria-label=${iconOnly ? label : undefined} title=${iconOnly ? label : undefined} ...${rest}>
    ${icon && html`<${Icon} name=${icon} />`}${children}</button>`;
}

export function Switch({ checked, onChange, children, disabled, id }) {
  return html`<button type="button" role="switch" id=${id} class="switch" aria-checked=${checked ? 'true' : 'false'} disabled=${disabled}
    onClick=${() => onChange(!checked)}><span class="track"><span class="thumb"></span></span><span>${children}</span></button>`;
}

export function Field({ label, hint, error, children, id }) {
  return html`<div class="field">${label && html`<label for=${id}>${label}</label>`}${children}
    ${hint && html`<div class="hint">${hint}</div>`}${error && html`<div class="error" role="alert">${error}</div>`}</div>`;
}

export function Check({ checked, onChange, children, disabled, testid }) {
  return html`<label class="check"><input type="checkbox" checked=${checked} disabled=${disabled} data-testid=${testid}
    onChange=${(e) => onChange(e.target.checked)} /><span>${children}</span></label>`;
}

// Radio-group style segmented control.
export function Segmented({ value, options, onChange, label, testid }) {
  return html`<div class="segmented" role="radiogroup" aria-label=${label} data-testid=${testid}>
    ${options.map(([v, text]) => html`<button type="button" role="radio" aria-checked=${value === v ? 'true' : 'false'} onClick=${() => onChange(v)}>${text}</button>`)}</div>`;
}

export function Pill({ kind, icon, children, ...rest }) {
  return html`<span class=${'pill' + (kind ? ' ' + kind : '')} ...${rest}>${icon && html`<${Icon} name=${icon} />`}${children}</span>`;
}

export function Led({ kind, on, pulse }) {
  return html`<span class=${['led', kind, on && 'on', pulse && 'pulse'].filter(Boolean).join(' ')} aria-hidden="true"></span>`;
}

// A group label. mode: 'talk' (mic icon) | 'listen' (ear icon, dimmed) | undefined
export function GroupTag({ groups, id, mode }) {
  return html`<span class=${'tag g' + groupIdx(groups, id) + (mode === 'listen' ? ' dim' : '')}
    title=${mode === 'talk' ? 'talking to this group' : mode === 'listen' ? 'listening to this group' : undefined}>
    ${mode && html`<${Icon} name=${mode === 'talk' ? 'mic' : 'ear'} />`}${groupName(groups, id)}</span>`;
}

// Segmented LED level meter. level is dBFS (-70 .. -15).
export function Meter({ level, active }) {
  const n = 18;
  const lit = active ? Math.max(0, Math.min(n, Math.round(((level + 70) / 55) * n))) : 0;
  return html`<div class="meter" role="img" aria-label=${active ? 'microphone level' : 'no signal'}>
    ${Array.from({ length: n }, (_, i) => html`<i key=${i} class=${i < lit ? 'on' + (i >= 14 ? ' peak' : i >= 11 ? ' hot' : '') : ''}></i>`)}</div>`;
}

export function Callout({ kind, icon, children }) {
  return html`<div class=${'callout ' + (kind || '')} role=${kind === 'bad' ? 'alert' : undefined}>${icon && html`<${Icon} name=${icon} />`}<div class="grow">${children}</div></div>`;
}

export function Empty({ icon, title, children }) {
  return html`<div class="empty">${icon && html`<${Icon} name=${icon} />`}<h3>${title}</h3><div class="stack-sm">${children}</div></div>`;
}

export function Panel({ title, eyebrow, actions, children, flush, id }) {
  return html`<section class=${'panel' + (flush ? ' flush' : '')} id=${id} aria-labelledby=${title ? id + '-h' : undefined}>
    ${(title || actions) && html`<div class=${'panel-head' + (flush ? ' pad' : '')} style=${flush ? 'padding:var(--sp-4) var(--sp-5) 0' : undefined}>
      <div>${eyebrow && html`<div class="eyebrow">${eyebrow}</div>`}${title && html`<h2 id=${id + '-h'}>${title}</h2>`}</div>${actions && html`<div class="cluster">${actions}</div>`}</div>`}
    ${children}</section>`;
}

// Modal dialog / side sheet using the native <dialog> (focus trap, Escape and inert background for free).
export function Dialog({ open, onClose, title, sheet, children, footer, testid, width }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current; if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  useEffect(() => {
    const d = ref.current; if (!d) return;
    const onc = () => onClose && onClose();
    d.addEventListener('close', onc);
    return () => d.removeEventListener('close', onc);
  }, [onClose]);
  const click = (e) => { if (e.target === ref.current) onClose && onClose(); };
  return html`<dialog ref=${ref} class=${'dlg' + (sheet ? ' sheet' : '')} aria-label=${title} data-testid=${testid} style=${width ? `width:min(${width}px, calc(100vw - 24px))` : undefined} onClick=${click}>
    ${open && html`<div class="dlg-head"><h2>${title}</h2><${Button} variant="quiet" iconOnly icon="x" label="Close" onClick=${onClose} /></div>
      <div class="dlg-body">${children}</div>${footer && html`<div class="dlg-foot">${footer}</div>`}`}</dialog>`;
}

export function Toasts() {
  const [items, setItems] = useState([]);
  useEffect(() => onToast((t) => {
    setItems((x) => [...x, t]);
    setTimeout(() => setItems((x) => x.filter((y) => y.id !== t.id)), t.kind === 'bad' ? 7000 : 3200);
  }), []);
  return html`<div class="toasts" role="status" aria-live="polite">${items.map((t) => html`<div key=${t.id} class=${'toast ' + t.kind}>
    <${Icon} name=${t.kind === 'bad' ? 'circle-alert' : 'circle-check'} /><span>${t.message}</span></div>`)}</div>`;
}

// Promise-based confirmation in a proper dialog (replaces the browser's confirm()).
let confirmListener = null;
export function ask(opts) { return new Promise((res) => { if (confirmListener) confirmListener({ ...opts, res }); else res(true); }); }
export function ConfirmHost() {
  const [req, setReq] = useState(null);
  useEffect(() => { confirmListener = setReq; return () => { confirmListener = null; }; }, []);
  const done = (v) => { if (req) req.res(v); setReq(null); };
  return html`<${Dialog} open=${!!req} onClose=${() => done(false)} title=${req ? req.title : ''} width=${460} testid="confirm-dialog"
    footer=${req && html`<${Button} onClick=${() => done(false)}>Cancel<//><${Button} variant=${req.danger ? 'danger' : 'primary'} data-testid="confirm-yes" onClick=${() => done(true)}>${req.confirm || 'Continue'}<//>`}>
    ${req && html`<p>${req.body}</p>`}<//>`;
}

export function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch (e) {
      const t = document.createElement('textarea'); t.value = text; document.body.append(t); t.select();
      try { document.execCommand('copy'); } catch (e2) { /* ignore */ } t.remove();
    }
    setDone(true); setTimeout(() => setDone(false), 1500);
  };
  return html`<${Button} size="sm" icon=${done ? 'check' : 'copy'} onClick=${copy}>${done ? 'Copied' : label}<//>`;
}

export function Qr({ src, alt }) {
  const [bad, setBad] = useState(false);
  if (bad) return html`<div class="muted small">QR code unavailable on this appliance.</div>`;
  return html`<img class="qr" src=${src} alt=${alt} onError=${() => setBad(true)} />`;
}

export function Logo({ site }) {
  return html`<a class="logo" href="/" aria-label="Crewline home">
    <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 19v-3a10 10 0 0 1 20 0v3" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><rect x="4" y="18" width="5" height="9" rx="2.2" fill="currentColor"/><rect x="23" y="18" width="5" height="9" rx="2.2" fill="currentColor"/><path d="M25.5 27c0 2.5-3 3-7 3" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
    <b>Crewline</b></a>${site && html`<span class="faint small" style="margin-left:-4px">· ${site}</span>`}`;
}

// Theme and flash style picker (used in every page header menu).
export function ThemeMenu() {
  const [theme, setT] = useState(currentTheme());
  const [flash, setF] = useState(currentFlash());
  return html`<div class="stack">
    <div class="field"><span class="label">Screen theme</span><${Segmented} label="Screen theme" value=${theme} options=${THEMES} onChange=${(v) => { setTheme(v); setT(v); }} testid="theme-seg" />
      <div class="hint">${theme === 'night' ? 'Night uses only red light so your eyes stay adjusted in a dark booth.' : 'Dark is the default for a dark booth. Night is red-only.'}</div></div>
    <div class="field"><span class="label">Alert flash</span><${Segmented} label="Alert flash" value=${flash} options=${FLASH} onChange=${(v) => { setFlash(v); setF(v); }} />
      <div class="hint">How strongly the screen edge glows for a call or a name mention.</div></div></div>`;
}

export function useDialog() {
  const [open, setOpen] = useState(false);
  return [open, useCallback(() => setOpen(true), []), useCallback(() => setOpen(false), [])];
}

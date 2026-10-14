import { html } from '/static/js/lib/core.js';
import { Icon, Button, Panel, Qr, Callout } from '/static/js/lib/ui.js';
import { useAdmin } from '/static/js/admin/data.js';
import { PageHead } from '/static/js/admin/parts.js';
import { useNetwork } from '/static/js/admin/network.js';

export function PrintSheets() {
  const { S } = useAdmin();
  const [info] = useNetwork();
  const url = location.origin + '/';
  const n = info && info.settings;
  const running = info && info.status && info.status.ap && info.status.ap.active;
  return html`<div class="stack-lg">
    <${PageHead} title="Print sheets" actions=${html`<${Button} variant="primary" icon="printer" onClick=${() => window.print()}>Print<//>`}>A join sheet for the booth wall and one card per person with their phone remote. Print to paper or PDF.<//>
    <${Callout} kind="warn" icon="triangle-alert" class="no-print">Each remote card is a private link that controls that person's microphone settings. Hand each card to its owner only.<//>
    <section class="panel stack">
      <div class="eyebrow">Crew intercom</div><h2>${S.site_name || 'Crewline'}</h2>
      <div class="cluster" style="gap:var(--sp-6);align-items:flex-start">
        ${running && info.wifi_qr && html`<div class="stack-sm"><div class="eyebrow">1. Join the Wi-Fi</div><${Qr} src=${'/api/admin/qr.svg?data=' + encodeURIComponent(info.wifi_qr)} alt="QR code to join Wi-Fi" /><div><b>${n.ap_ssid}</b></div><div class="mono small">Password: ${n.ap_password}</div></div>`}
        <div class="stack-sm"><div class="eyebrow">${running ? '2. ' : ''}Open the dashboard</div><${Qr} src="/api/public/qr/dashboard.svg" alt="QR code for the dashboard" /><div class="mono"><b>${url}</b></div></div></div>
      <p class="muted small">Dashboard: who is speaking, live captions, calls for Sound. Nothing here records audio.</p></section>
    <div class="print-cards">${S.endpoints.filter((e) => e.remote_token).map((e) => html`<section key=${e.id} class="panel stack-sm">
      <div class="eyebrow">Your phone remote</div><h2>${e.name}</h2>
      <${Qr} src=${`/api/admin/qr.svg?data=${encodeURIComponent(location.origin + '/r/' + e.remote_token)}`} alt=${'QR code for ' + e.name} />
      <p class="small muted">Scan to talk, mute, switch groups and call Sound from your phone. Keep this card private.</p></section>`)}</div></div>`;
}

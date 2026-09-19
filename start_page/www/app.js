/* Start Page: render the cards from services.json, colour the dots from status.json.
   No build step, no dependencies, every request relative so ingress and the host port both work. */
'use strict';

const THEME_KEY = 'start-page.theme';
function applyTheme(t) { document.documentElement.setAttribute('data-theme', t); }
try { applyTheme(localStorage.getItem(THEME_KEY) || 'dark'); } catch { applyTheme('dark'); }
document.getElementById('themetoggle').addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch { /* private window */ }
  applyTheme(next);
});

const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* ---------- render ---------- */
function render(model) {
  document.title = model.title ? `${model.title} · Start` : 'Start';
  $('#title').textContent = model.title || 'Home';
  $('#tagline').textContent = model.tagline || 'start here';
  $('#lede').textContent = model.lede || '';
  const root = $('#groups');
  root.replaceChildren();
  for (const g of model.groups) {
    const sec = el('section', 'group');
    sec.dataset.group = g.name;
    sec.append(el('h2', null, g.name));
    const cards = el('div', 'cards');
    for (const c of g.cards) {
      const a = el('a', 'card');
      a.href = c.url;
      if (c.monitor) {
        a.dataset.monitor = c.monitor;
        const dot = el('span', 'dot');
        dot.setAttribute('aria-hidden', 'true');
        a.append(dot);
      }
      a.append(el('span', 'cname', c.name));
      a.append(el('span', 'cdesc mute', c.description || ''));
      cards.append(a);
    }
    sec.append(cards);
    root.append(sec);
  }
  const problems = $('#problems');
  if (model.problems && model.problems.length) {
    problems.textContent = 'Cards left off the page:\n' + model.problems.join('\n');
    problems.hidden = false;
  }
  applyFilter();
}

/* ---------- filter ----------
   Matches name, description and href, so "10.10" finds the LAN boxes. A group whose cards all hide,
   hides too. "/" focuses the box, Escape clears it. */
const filter = $('#filter');
function applyFilter() {
  const q = filter.value.trim().toLowerCase();
  let shown = 0;
  for (const c of document.querySelectorAll('.card')) {
    const hit = !q || (c.textContent + ' ' + c.getAttribute('href')).toLowerCase().includes(q);
    c.hidden = !hit;
    if (hit) shown++;
  }
  for (const g of document.querySelectorAll('.group')) g.hidden = !g.querySelector('.card:not([hidden])');
  $('#empty').hidden = shown > 0 || !document.querySelector('.card');
}
filter.addEventListener('input', applyFilter);
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && document.activeElement !== filter) { e.preventDefault(); filter.focus(); }
  else if (e.key === 'Escape' && document.activeElement === filter) { filter.value = ''; applyFilter(); }
});

/* ---------- status ----------
   The dots are Uptime Kuma's verdict, read by the server; the browser never probes anything. A card
   whose monitor Uptime Kuma does not list stays grey and says so in its tooltip. When the server
   cannot reach Uptime Kuma the last verdict is kept, dimmed, and the footer says since when. */
function clock(iso) {
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}
function applyStatus(s) {
  const stale = !!s.error;
  for (const card of document.querySelectorAll('.card[data-monitor]')) {
    const dot = card.querySelector('.dot');
    const m = s.monitors[card.dataset.monitor];
    dot.className = 'dot';
    if (!m) { dot.title = `no monitor named "${card.dataset.monitor}" in Uptime Kuma`; continue; }
    dot.classList.add(m.status);
    if (stale) dot.classList.add('stale');
    const ms = m.response_ms != null ? ` · ${Math.round(m.response_ms)} ms` : '';
    dot.title = `${m.status}${ms} · checked ${clock(s.checked_at)}`;
  }
  const line = $('#status');
  line.className = stale ? 'bad' : '';
  if (!s.source) line.textContent = 'Status: no Uptime Kuma configured.';
  else if (stale) line.textContent = `Status: Uptime Kuma unreachable since ${clock(s.error_since)} (${s.error}); dots are the last verdict.`;
  else line.textContent = `Status from Uptime Kuma, checked ${clock(s.checked_at)}.`;
}
async function pollStatus(interval) {
  try {
    const r = await fetch('status.json', { cache: 'no-store' });
    applyStatus(await r.json());
  } catch (e) {
    $('#status').textContent = `Status: the page server did not answer (${e.message}).`;
    $('#status').className = 'bad';
  } finally {
    setTimeout(() => pollStatus(interval), interval * 1000);
  }
}

/* ---------- boot ---------- */
(async () => {
  let model;
  try {
    const r = await fetch('services.json', { cache: 'no-store' });
    model = await r.json();
  } catch (e) {
    $('#lede').textContent = `The page server did not answer: ${e.message}`;
    return;
  }
  render(model);
  pollStatus(Math.max(10, model.status_interval || 30));
})();

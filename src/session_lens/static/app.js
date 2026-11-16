'use strict';
const $ = (id) => document.getElementById(id);
const state = { flags: {}, drafts: new Map(), flaggedLibrary: false, saving: false, sessions: [], events: [], selected: null, session: null, filter: 'all', query: '', tab: 'readable', raw: new Map(), sessionRequest: 0, detailRequest: 0 };
const groups = [['all', 'All events'], ['messages', 'Messages'], ['tools', 'Tools'], ['reasoning', 'Reasoning'], ['system', 'System'], ['flagged', '⚑ Flagged']];
const icons = { messages: '≡', tools: '⌘', reasoning: '◇', system: '·' };
let toastTimer;
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function toast(message, error = false) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').className = error ? 'error' : ''; $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500); }
async function api(url, options) { const res = await fetch(url, options); const value = await res.json(); if (!res.ok) throw new Error(value.error || `Request failed (${res.status})`); return value; }
function dateText(value, options) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString(undefined, options || { month: 'short', day: 'numeric', year: 'numeric' }); }
function timeText(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }); }
function sessionURL() { return '/api/sessions/' + encodeURIComponent(state.session.id); }
function eventFlag(id, session = state.session?.id) { return state.flags[session]?.[String(id)]; }
function flagCount(session) { return Object.keys(state.flags[session] || {}).length; }
function draftKey(session, line) { return session + ':' + line; }
function filtered() { return state.events.filter(e => (state.filter === 'all' || (state.filter === 'flagged' ? !!eventFlag(e.id) : e.category === state.filter)) && (!state.query || `${e.label} ${e.body} ${e.type} ${e.subtype} ${e.line} ${eventFlag(e.id)?.note || ''}`.toLowerCase().includes(state.query))); }
function renderSessions() {
  const sessions = state.sessions.filter(s => !state.flaggedLibrary || flagCount(s.id));
  $('session-count').textContent = sessions.length;
  $('flag-total').textContent = Object.values(state.flags).reduce((sum, flags) => sum + Object.keys(flags).length, 0);
  $('flagged-library').setAttribute('aria-pressed', String(state.flaggedLibrary));
  $('sessions').replaceChildren();
  for (const session of sessions) {
    const button = el('button', 'session-card' + (state.session?.id === session.id ? ' active' : ''));
    button.setAttribute('aria-pressed', String(state.session?.id === session.id));
    button.title = session.title;
    button.append(el('div', 'session-card-title', session.title));
    const meta = el('div', 'session-card-meta');
    meta.append(el('span', '', dateText(session.timestamp, { month: 'short', day: 'numeric' })), el('span', '', '·'), el('span', '', `${session.count} events`));
    if (flagCount(session.id)) meta.append(el('span', 'session-flag-count', `⚑ ${flagCount(session.id)}`));
    button.append(meta); button.addEventListener('click', () => openSession(session.id)); $('sessions').append(button);
  }
  if (!sessions.length) $('sessions').append(el('p', 'muted', state.flaggedLibrary ? 'No flagged events yet. Select an event and click Flag event to start a review list.' : 'No sessions yet. Import a .jsonl file below.'));
}
async function loadSessions(preferred) {
  try {
    [state.sessions, state.flags] = await Promise.all([api('/api/sessions'), api('/api/flags')]); renderSessions();
    const session = state.sessions.find(s => s.id === preferred) || state.sessions[0];
    if (session) await openSession(session.id);
  } catch (err) { toast(err.message, true); $('sessions').replaceChildren(el('p', 'muted', 'Could not load sessions. Check that the server is running.')); }
}
async function openSession(id) {
  const request = ++state.sessionRequest;
  try {
    const result = await api('/api/sessions/' + encodeURIComponent(id));
    if (request !== state.sessionRequest) return;
    state.session = result.session; state.events = result.events; state.raw.clear();
    state.filter = state.flaggedLibrary ? 'flagged' : 'all'; state.query = ''; state.selected = null; state.tab = 'readable'; $('search').value = '';
    renderSessions(); renderHeader(); renderFilters(); renderEvents();
    // Open the first actual user request, while keeping every source event in the list.
    const first = (state.flaggedLibrary && filtered()[0]) || state.events.find(e => e.role === 'user' && !e.body.startsWith('<') && !e.body.startsWith('# AGENTS.md')) || state.events[0];
    if (first) selectEvent(first.id, true); else { $('details').replaceChildren(el('p', 'muted', 'This session has no events.')); }
  } catch (err) { if (request === state.sessionRequest) toast(err.message, true); }
}
function renderHeader() {
  const s = state.session;
  $('title').textContent = s.title; $('title').title = s.title;
  $('session-meta').replaceChildren();
  for (const [i, text] of [dateText(s.timestamp), s.model || 'Model not recorded', s.cwd || 'Working directory not recorded'].entries()) {
    if (i) $('session-meta').append(el('span', 'meta-dot', '·'));
    const span = el('span', i === 2 ? 'path' : '', text); span.title = text; $('session-meta').append(span);
  }
  $('stats').replaceChildren();
  for (const [key, title] of [['all', 'events'], ['messages', 'messages'], ['tools', 'tool events'], ['reasoning', 'reasoning records']]) {
    const stat = el('div', 'stat'); stat.append(el('i', 'stat-dot ' + key), el('strong', '', key === 'all' ? s.count : s.counts[key] || 0), el('span', '', title)); $('stats').append(stat);
  }
  const turns = el('div', 'stat'); turns.append(el('strong', '', s.turns), el('span', '', 'turns')); $('stats').append(turns);
}
function renderFilters() {
  $('filters').replaceChildren();
  for (const [key, label] of groups) {
    const button = el('button', 'filter' + (state.filter === key ? ' active' : ''));
    button.setAttribute('aria-pressed', String(state.filter === key));
    button.append(el('span', '', label), el('span', 'filter-count', key === 'all' ? state.events.length : key === 'flagged' ? flagCount(state.session?.id) : state.session?.counts[key] || 0));
    button.addEventListener('click', () => { state.filter = key; renderFilters(); renderEvents(); if (key === 'flagged' && filtered().length) selectEvent(filtered()[0].id, true); }); $('filters').append(button);
  }
}
function renderEvents() {
  const visible = filtered(); const fragment = document.createDocumentFragment();
  for (const event of visible) {
    const row = el('button', 'event-row' + (state.selected === event.id ? ' active' : ''));
    row.id = 'event-' + event.id; row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(state.selected === event.id));
    row.append(el('span', `event-icon ${event.category} ${event.role}`, icons[event.category]));
    const content = el('div', 'event-content'); const title = el('div', 'event-title', event.label);
    if (eventFlag(event.id)) { const marker = el('span', 'flag-marker', ' ⚑'); marker.title = eventFlag(event.id).note || 'Flagged for review'; title.append(marker); }
    title.append(el('span', 'event-line', `L${event.line}`)); content.append(title, el('div', 'event-preview', event.summary));
    row.append(content, el('span', 'event-time', timeText(event.timestamp))); row.addEventListener('click', () => selectEvent(event.id)); fragment.append(row);
  }
  if (!visible.length) { const empty = el('div', 'empty'); empty.append(el('span', '', '⌕'), el('h2', '', 'No matching events'), el('p', '', state.filter === 'flagged' ? 'Flag an event to collect it here for review.' : 'Try another search or event type.')); fragment.append(empty); }
  $('events').replaceChildren(fragment); $('event-count').textContent = visible.length;
  $('list-footer').textContent = `${visible.length} of ${state.events.length} events · in source order`;
  updateNavigation();
}
function selectEvent(id, scroll = false) {
  state.selected = id;
  for (const row of $('events').querySelectorAll('.event-row')) { const active = row.id === 'event-' + id; row.classList.toggle('active', active); row.setAttribute('aria-selected', String(active)); }
  if (scroll) $('event-' + id)?.scrollIntoView({ block: 'nearest' });
  renderDetail(); updateNavigation();
}
function updateNavigation() {
  const visible = filtered(); const index = visible.findIndex(e => e.id === state.selected);
  $('previous').disabled = index <= 0; $('next').disabled = !visible.length || index === visible.length - 1;
}
function navigate(delta) { const events = filtered(); const index = events.findIndex(e => e.id === state.selected); const next = events[index < 0 ? 0 : index + delta]; if (next) selectEvent(next.id, true); }
async function getRaw(event) { const key = state.session.id + ':' + event.id; if (!state.raw.has(key)) { const raw = await api(sessionURL() + '/events/' + event.id); state.raw.set(key, JSON.stringify(raw, null, 2)); } return state.raw.get(key); }
async function renderDetail() {
  const request = ++state.detailRequest; const event = state.events.find(e => e.id === state.selected); if (!event) return;
  renderFlagControls();
  const head = $('detail-head'); head.replaceChildren(el('div', 'eyebrow', `EVENT ${String(event.line).padStart(3, '0')}${event.turn ? ' / TURN ' + event.turn : ''}`));
  const heading = el('div', 'detail-heading-row'); heading.append(el('span', `event-icon ${event.category}`, icons[event.category]), el('h2', '', event.label)); if (event.phase) heading.append(el('span', 'badge', event.phase)); head.append(heading);
  head.append(el('div', 'detail-meta', `${event.type} / ${event.subtype}  ·  ${timeText(event.timestamp)}`));
  $('readable-tab').setAttribute('aria-selected', String(state.tab === 'readable')); $('raw-tab').setAttribute('aria-selected', String(state.tab === 'raw'));
  $('source-location').textContent = `${state.session.filename} : ${event.line}`; $('source-location').title = $('source-location').textContent;
  const details = $('details'); details.replaceChildren();
  if (state.tab === 'raw') {
    details.append(el('div', 'body-label', 'ORIGINAL EVENT · JSON'), el('pre', 'event-body raw', 'Loading raw record…'));
    try { const text = await getRaw(event); if (request !== state.detailRequest) return; details.lastChild.textContent = text; }
    catch (err) { if (request === state.detailRequest) details.lastChild.textContent = `Could not load record: ${err.message}`; }
  } else {
    if (event.related.length) {
      const related = el('div', 'related', 'Linked event');
      for (const id of event.related) {
        const linked = state.events.find(e => e.id === id); if (!linked) continue;
        const button = el('button', '', `${linked.label} · L${id} ↗`);
        button.addEventListener('click', () => { state.filter = 'all'; state.query = ''; $('search').value = ''; renderFilters(); renderEvents(); selectEvent(id, true); }); related.append(button);
      }
      details.append(related);
    }
    details.append(el('div', 'body-label', event.category === 'messages' ? 'MESSAGE CONTENT' : event.category === 'reasoning' ? 'RECORDED TEXT / AVAILABILITY' : 'EVENT CONTENT'));
    details.append(el('pre', 'event-body' + (event.category === 'messages' ? ' message' : ''), event.body || 'No readable content. Open Raw JSON to inspect this record.'));
  }
  $('inspector-scroll').scrollTop = 0;
}
function renderFlagControls() {
  const event = state.events.find(e => e.id === state.selected);
  const flag = event && eventFlag(event.id);
  $('flag-event').disabled = !event || state.saving;
  $('flag-event').textContent = flag ? '⚑ Remove flag' : '⚑ Flag event';
  $('flag-event').setAttribute('aria-pressed', String(!!flag));
  $('review-note').hidden = !flag;
  if (!flag) return;
  const key = draftKey(state.session.id, event.id);
  $('flag-note').value = state.drafts.get(key) ?? flag.note;
  $('note-status').textContent = state.drafts.has(key) ? 'Unsaved changes' : 'Saved locally';
  $('save-note').disabled = state.saving || !state.drafts.has(key);
}
async function saveFlag(flagged) {
  if (state.saving || !state.session || !state.selected) return;
  const session = state.session.id, line = state.selected, key = draftKey(session, line);
  const note = state.drafts.get(key) ?? eventFlag(line, session)?.note ?? '';
  state.saving = true; renderFlagControls();
  try {
    state.flags = await api('/api/flags', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Viewer': '1' }, body: JSON.stringify({ session, line, flagged, note, fingerprint: state.events.find(e => e.id === line)?.fingerprint }) });
    if (!flagged || state.drafts.get(key) === note) state.drafts.delete(key);
    renderSessions(); renderFilters(); renderEvents();
    toast(flagged ? 'Flag saved for review' : 'Flag removed');
  } catch (err) { toast(err.message, true); }
  finally { state.saving = false; renderFlagControls(); }
}
$('flag-event').addEventListener('click', () => saveFlag(!eventFlag(state.selected)));
$('save-note').addEventListener('click', () => saveFlag(true));
$('flag-note').addEventListener('input', () => {
  const key = draftKey(state.session.id, state.selected);
  if ($('flag-note').value === eventFlag(state.selected)?.note) state.drafts.delete(key);
  else state.drafts.set(key, $('flag-note').value);
  $('note-status').textContent = state.drafts.has(key) ? 'Unsaved changes' : 'Saved locally';
  $('save-note').disabled = state.saving || !state.drafts.has(key);
});
$('flagged-library').addEventListener('click', () => {
  state.flaggedLibrary = !state.flaggedLibrary; renderSessions();
  if (state.flaggedLibrary) {
    const first = state.sessions.find(s => flagCount(s.id));
    if (first) openSession(first.id);
    else toast('Select an event and click Flag event to save it for review.');
  } else if (state.session) { state.filter = 'all'; renderFilters(); renderEvents(); }
});
window.addEventListener('beforeunload', event => { if (state.drafts.size || state.saving) { event.preventDefault(); event.returnValue = ''; } });
$('search').addEventListener('input', e => { state.query = e.target.value.trim().toLowerCase(); renderEvents(); });
$('readable-tab').addEventListener('click', () => { state.tab = 'readable'; renderDetail(); });
$('raw-tab').addEventListener('click', () => { state.tab = 'raw'; renderDetail(); });
$('previous').addEventListener('click', () => navigate(-1)); $('next').addEventListener('click', () => navigate(1));
$('refresh').addEventListener('click', async () => { await loadSessions(state.session?.id); toast('Session snapshots reloaded'); });
$('copy').addEventListener('click', async () => {
  const event = state.events.find(e => e.id === state.selected); if (!event) return;
  try { const content = state.tab === 'raw' ? await getRaw(event) : event.body; await navigator.clipboard.writeText(content); toast('Copied to clipboard'); } catch (err) { toast('Could not copy. Select the text to copy it manually.', true); }
});
$('import').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async e => {
  const file = e.target.files[0]; if (!file) return;
  if (file.size > 32 * 1024 * 1024) { toast('Choose a JSONL file smaller than 32 MB.', true); e.target.value = ''; return; }
  $('import').disabled = true;
  try { const session = await api('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/x-ndjson', 'X-Session-Viewer': '1' }, body: file }); await loadSessions(session.id); toast('Session imported'); }
  catch (err) { toast(err.message, true); }
  finally { $('import').disabled = false; e.target.value = ''; }
});
document.addEventListener('keydown', event => {
  if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName) || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === '/') { event.preventDefault(); $('search').focus(); }
  if (['j', 'k'].includes(event.key)) { event.preventDefault(); navigate(event.key === 'j' ? 1 : -1); }
  if (document.activeElement === $('events') && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); navigate(event.key === 'ArrowDown' ? 1 : -1); }
});
loadSessions();

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Exercise the actual review state and handlers without a browser dependency.
function app(fetchImpl) {
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, { value: '', listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, setAttribute(key, value) { this[key] = value; } });
      return nodes.get(id);
    },
    addEventListener() {},
  };
  const context = vm.createContext({ document, window: { addEventListener() {} }, fetch: fetchImpl, setTimeout: () => 1, clearTimeout() {} });
  const source = fs.readFileSync(path.join(__dirname, '../src/session_lens/static/app.js'), 'utf8');
  vm.runInContext(source.slice(0, source.lastIndexOf('loadSessions();')), context);
  const run = code => vm.runInContext(code, context);
  run(`state.session = {id: 'a.jsonl'}; state.selected = 1;
    state.events = [{id: 1, category: 'messages', body: 'hello', label: 'User', type: 'message', subtype: 'message', line: 1},
                    {id: 2, category: 'tools', body: 'done', label: 'Tool', type: 'call', subtype: 'call', line: 2}];
    state.flags = {'a.jsonl': {'1': {note: 'Ignored error'}}};`);
  return { run, nodes };
}

test('flagged filter and search include saved review notes', () => {
  const { run } = app();
  assert.equal(run("flagCount('a.jsonl')"), 1);
  assert.equal(run("state.filter = 'flagged'; filtered().length"), 1);
  assert.equal(run("state.query = 'ignored error'; filtered()[0].id"), 1);
  assert.equal(run("state.query = 'unmatched'; filtered().length"), 0);
});

test('note drafts survive event changes and remain isolated by session', () => {
  const { run, nodes } = app();
  run('renderFlagControls()');
  assert.equal(nodes.get('flag-note').value, 'Ignored error');
  nodes.get('flag-note').value = 'Check verification';
  nodes.get('flag-note').listeners.input();
  run('state.selected = 2; renderFlagControls(); state.selected = 1; renderFlagControls()');
  assert.equal(nodes.get('flag-note').value, 'Check verification');
  assert.equal(nodes.get('note-status').textContent, 'Unsaved changes');
  run("state.session = {id:'b.jsonl'}; renderFlagControls()");
  assert.equal(nodes.get('review-note').hidden, true);
});

test('failed save retains flags and unsaved notes for retry', async () => {
  const { run, nodes } = app(async () => ({ ok: false, json: async () => ({error: 'Disk unavailable'}) }));
  run("state.drafts.set('a.jsonl:1', 'Keep this draft'); renderFlagControls()");
  await run('saveFlag(true)');
  assert.equal(run("eventFlag(1).note"), 'Ignored error');
  assert.equal(run("state.drafts.get('a.jsonl:1')"), 'Keep this draft');
  assert.equal(nodes.get('save-note').disabled, false);
  assert.equal(nodes.get('toast').textContent, 'Disk unavailable');
});

test('save clears only the submitted draft, keeping edits made during a request', async () => {
  let resolve;
  const pending = new Promise(r => { resolve = r; });
  const { run } = app(() => pending);
  run("renderSessions = () => {}; renderFilters = () => {}; renderEvents = () => {}; state.drafts.set('a.jsonl:1', 'Submitted note')");
  const saving = run('saveFlag(true)');
  run("state.drafts.set('a.jsonl:1', 'A newer edit')");
  resolve({ok: true, json: async () => ({'a.jsonl': {'1': {note: 'Submitted note'}}})});
  await saving;
  assert.equal(run("eventFlag(1).note"), 'Submitted note');
  assert.equal(run("state.drafts.get('a.jsonl:1')"), 'A newer edit');
  assert.equal(run('state.saving'), false);
});

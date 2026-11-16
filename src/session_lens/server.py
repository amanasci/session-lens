"""Inspect and annotate Codex session snapshots in a local browser."""
from __future__ import annotations

import argparse
from contextlib import closing
from collections import Counter
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from importlib.resources import files
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
from uuid import uuid4
from . import __version__


def default_data_directory():
    if os.environ.get('SESSION_LENS_DATA_DIR'):
        return Path(os.environ['SESSION_LENS_DATA_DIR']).expanduser()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / 'session-lens'


DATA = default_data_directory() / 'sessions'
MAX_IMPORT = 32 * 1024 * 1024
FLAGS_DB = DATA.parent / 'flags.sqlite3'


def fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def flags_connection():
    FLAGS_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(FLAGS_DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS flags (
        session TEXT NOT NULL, line INTEGER NOT NULL, fingerprint TEXT NOT NULL,
        note TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (session, line))''')
    return db


def read_flags():
    result = {}
    with closing(flags_connection()) as db:
        for row in db.execute('SELECT * FROM flags ORDER BY updated_at DESC'):
            path = DATA / row['session']
            if not path.is_file():
                continue
            record = load(path)[2].get(row['line'])
            # A replaced snapshot must not attach a note to a different event.
            if record is not None and fingerprint(record) == row['fingerprint']:
                result.setdefault(row['session'], {})[str(row['line'])] = dict(row)
    return result


def pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def readable(value):
    """Extract display text without rendering images or opaque encrypted payloads."""
    if isinstance(value, str):
        return re.sub(r'data:[^\s"\']+;base64,[A-Za-z0-9+/=]+', '[embedded media]', value)
    if isinstance(value, list):
        return '\n\n'.join(filter(None, (readable(x) for x in value)))
    if isinstance(value, dict):
        for key in ('text', 'content', 'output'):
            if key in value:
                return readable(value[key])
        if value.get('type') in ('image', 'input_image', 'output_image', 'audio', 'input_audio'):
            return '[' + value['type'].replace('_', ' ') + ']'
        return pretty(value)
    return '' if value is None else str(value)


def normalize(record, line, turn):
    kind = record.get('type', 'unknown')
    p = record.get('payload', record)
    if not isinstance(p, dict):
        p = {'value': p}
    subtype = p.get('type', kind)
    category, label = 'system', str(subtype).replace('_', ' ')
    body = ''
    role = p.get('role', '')
    if subtype == 'message' or kind in ('user', 'assistant'):
        role = role or kind
        category = 'messages'
        label = {'user': 'User message', 'assistant': 'Assistant message', 'developer': 'Developer instructions', 'system': 'System instructions'}.get(role, role.title() + ' message')
        body = readable(p.get('content', p.get('text', '')))
    elif subtype in ('agent_message', 'user_message'):
        category, role = 'messages', 'assistant' if subtype == 'agent_message' else 'user'
        label, body = role.title() + ' message', readable(p.get('message', p.get('text', '')))
    elif subtype in ('function_call', 'custom_tool_call'):
        category, label = 'tools', p.get('name', 'Tool call')
        body = readable(p.get('arguments', p.get('input', '')))
        try:
            body = pretty(json.loads(body))
        except (ValueError, TypeError):
            pass
    elif subtype in ('function_call_output', 'custom_tool_call_output'):
        category, label, body = 'tools', 'Tool result', readable(p.get('output', ''))
    elif subtype in ('reasoning', 'agent_reasoning'):
        category, label = 'reasoning', 'Recorded reasoning'
        body = readable(p.get('summary', [])) or readable(p.get('content', p.get('text', '')))
        if not body:
            body = 'This record contains encrypted reasoning; no readable reasoning text is available.' if p.get('encrypted_content') else 'No readable reasoning text is recorded.'
    elif subtype == 'item_completed':
        label = 'Item completed · ' + str(p.get('item', {}).get('type', 'item'))
        body = readable(p.get('item', {}))
    elif kind == 'session_meta':
        label = 'Session metadata'
        body = pretty({k: v for k, v in p.items() if k != 'base_instructions'})
    else:
        body = pretty(p)
    # Readable previews are bounded; the raw source remains available on demand.
    truncated = len(body) > 120_000
    body = body[:120_000]
    if truncated:
        body += '\n\n[Readable view truncated. Open Raw JSON for the full record.]'
    summary = re.sub(r'\s+', ' ', body).strip()[:190] or 'No text content'
    return dict(id=line, line=line, timestamp=record.get('timestamp', ''), type=kind,
                subtype=subtype, category=category, label=label, role=role,
                phase=p.get('phase', ''), turn=turn, call_id=p.get('call_id'),
                related=[], body=body, summary=summary, fingerprint=fingerprint(record))


@lru_cache(maxsize=12)
def parse_session(path_string, mtime_ns, size):
    path = Path(path_string)
    events, records, calls = [], {}, {}
    turn, meta, model, title, user_messages = 0, {}, '', '', []
    with path.open(encoding='utf-8') as f:
        for line_num, text in enumerate(f, 1):
            if not text.strip():
                continue
            try:
                record = json.loads(text)
                if not isinstance(record, dict):
                    raise ValueError('Record must be a JSON object')
            except (ValueError, TypeError) as exc:
                record = {'type': 'parse_error', 'payload': {'error': str(exc), 'original_line': text.rstrip()}}
            p = record.get('payload', {})
            if not isinstance(p, dict):
                p = {}
            if record.get('type') == 'session_meta':
                meta = p
            if record.get('type') == 'turn_context':
                model = p.get('model', model)
            if p.get('type') in ('task_started', 'turn_started') or record.get('type') == 'turn.started':
                turn += 1
            event = normalize(record, line_num, turn)
            if event['role'] == 'user' and event['category'] == 'messages':
                msg = event['body'].strip()
                if msg and not msg.startswith(('<environment_context>', '# AGENTS.md', '<permissions', '<INSTRUCTIONS>')):
                    user_messages.append(msg)
            events.append(event)
            records[line_num] = record
            if event['call_id']:
                calls.setdefault(event['call_id'], []).append(event)
    for siblings in calls.values():
        for event in siblings:
            event['related'] = [s['id'] for s in siblings if s is not event]
            if event['subtype'].endswith('_output'):
                call = next((s for s in siblings if not s['subtype'].endswith('_output')), None)
                if call:
                    event['label'] = call['label'] + ' · result'
    title = re.sub(r'\s+', ' ', user_messages[0])[:100] if user_messages else Path(meta.get('cwd', '')).name or path.stem
    counts = Counter(e['category'] for e in events)
    info = dict(id=path.name, title=title, timestamp=meta.get('timestamp', events[0]['timestamp'] if events else ''),
                cwd=meta.get('cwd', ''), model=model, count=len(events), counts=counts,
                turns=turn, bytes=size, session_id=meta.get('id', meta.get('session_id', '')), filename=path.name)
    return info, events, records


def load(path):
    stat = path.stat()
    return parse_session(str(path), stat.st_mtime_ns, stat.st_size)


class Handler(BaseHTTPRequestHandler):
    def send(self, value, status=200, content_type='application/json; charset=utf-8'):
        data = (pretty(value) if content_type.startswith('application/json') else value).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = unquote(urlparse(self.path).path).strip('/').split('/')
        try:
            if parts == ['api', 'flags']:
                return self.send(read_flags())
            if parts == ['api', 'sessions']:
                result = [load(p)[0] for p in DATA.glob('*.jsonl')]
                return self.send(sorted(result, key=lambda s: s['timestamp'], reverse=True))
            if len(parts) in (3, 5) and parts[:2] == ['api', 'sessions']:
                name = parts[2]
                if Path(name).name != name or not name.endswith('.jsonl'):
                    return self.send({'error': 'Invalid session name'}, 400)
                path = DATA / name
                if not path.is_file():
                    return self.send({'error': 'Session not found'}, 404)
                info, events, records = load(path)
                if len(parts) == 5 and parts[3] == 'events':
                    record = records.get(int(parts[4]))
                    return self.send(record if record is not None else {'error': 'Event not found'}, 200 if record is not None else 404)
                if len(parts) == 3:
                    return self.send({'session': info, 'events': events})
            assets = {'': ('index.html', 'text/html; charset=utf-8'), 'app.js': ('app.js', 'text/javascript; charset=utf-8'), 'styles.css': ('styles.css', 'text/css; charset=utf-8')}
            asset = assets.get('/'.join(parts))
            if asset:
                return self.send(files('session_lens').joinpath('static', asset[0]).read_text(encoding='utf-8'), content_type=asset[1])
            self.send({'error': 'Not found'}, 404)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.send({'error': str(exc)}, 400)

    def do_POST(self):
        if self.path == '/api/flags':
            return self.save_flag()
        # Uploads come only from this local UI, never a cross-origin webpage.
        if self.path != '/api/import':
            return self.send({'error': 'Not found'}, 404)
        if self.headers.get('X-Session-Viewer') != '1':
            return self.send({'error': 'Use the local viewer to import files'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_IMPORT:
                return self.send({'error': 'Choose a JSONL file between 1 byte and 32 MB'}, 400)
            content = self.rfile.read(length).decode('utf-8-sig')
            lines = [line for line in content.splitlines() if line.strip()]
            if not lines:
                raise ValueError('The file is empty')
            for number, line in enumerate(lines, 1):
                if not isinstance(json.loads(line), dict):
                    raise ValueError(f'Line {number} must be a JSON object')
            name = f'import-{uuid4().hex[:12]}.jsonl'
            path = DATA / name
            path.write_text(content, encoding='utf-8')
            self.send(load(path)[0], 201)
        except (ValueError, OSError, UnicodeError) as exc:
            self.send({'error': f'Could not import JSONL: {exc}'}, 400)

    def save_flag(self):
        if self.headers.get('X-Session-Viewer') != '1':
            return self.send({'error': 'Use the local viewer to save flags'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('Invalid flag request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a flag object')
            name, line = data.get('session'), data.get('line')
            if not isinstance(name, str) or Path(name).name != name or not name.endswith('.jsonl'):
                raise ValueError('Invalid session name')
            if type(line) is not int or line < 1 or type(data.get('flagged')) is not bool:
                raise ValueError('Expected a source line and flagged boolean')
            note = data.get('note', '')
            if not isinstance(note, str) or len(note) > 10000:
                raise ValueError('Notes must be text, up to 10,000 characters')
            path = DATA / name
            if not path.is_file():
                return self.send({'error': 'Session not found'}, 404)
            record = load(path)[2].get(line)
            if record is None:
                return self.send({'error': 'Event not found'}, 404)
            if data.get('fingerprint') is not None and data['fingerprint'] != fingerprint(record):
                return self.send({'error': 'The source event changed. Refresh before flagging it.'}, 409)
            with closing(flags_connection()) as db, db:
                if data['flagged']:
                    db.execute('''INSERT INTO flags VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(session, line) DO UPDATE SET
                        fingerprint=excluded.fingerprint, note=excluded.note,
                        updated_at=excluded.updated_at''',
                        (name, line, fingerprint(record), note, datetime.now(timezone.utc).isoformat()))
                else:
                    db.execute('DELETE FROM flags WHERE session=? AND line=?', (name, line))
            self.send(read_flags())
        except (OSError, ValueError, UnicodeError, sqlite3.Error) as exc:
            self.send({'error': f'Could not save flag: {exc}'}, 400)


def main(argv=None, *, default_data_dir=None):
    global DATA, FLAGS_DB
    parser = argparse.ArgumentParser(prog='session-lens', description=__doc__)
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=default_data_dir or default_data_directory(),
                        help='Directory for session snapshots and flags (default: %(default)s)')
    parser.add_argument('--import-dir', type=Path, help='Copy JSONL snapshots from this directory before starting')
    parser.add_argument('--demo', action='store_true', help='Load a small synthetic example session')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.import_dir and not args.import_dir.expanduser().is_dir():
        parser.error(f'Import directory does not exist: {args.import_dir}')
    DATA = args.data_dir.expanduser().resolve() / 'sessions'
    FLAGS_DB = DATA.parent / 'flags.sqlite3'
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        if args.import_dir:
            for path in args.import_dir.expanduser().rglob('*.jsonl'):
                target = DATA / path.name
                if path.resolve() != target.resolve():
                    shutil.copyfile(path, target)
        if args.demo:
            demo = DATA / 'demo.jsonl'
            if not demo.exists():
                demo.write_text(files('session_lens').joinpath('examples', 'demo.jsonl').read_text(encoding='utf-8'), encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as exc:
        parser.exit(1, f'session-lens: {exc}\n')
    print(f'\n  Session lens → http://127.0.0.1:{args.port}\n  Reading snapshots from {DATA}\n', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

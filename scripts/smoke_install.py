"""Run with an installed wheel's interpreter: python -I scripts/smoke_install.py."""
import io
import json
from importlib import metadata, resources
from pathlib import Path
import tempfile
from unittest.mock import patch

from session_lens import __version__, server

assert metadata.version('codex-session-lens') == __version__
for name in ('index.html', 'app.js', 'styles.css'):
    assert resources.files('session_lens').joinpath('static', name).read_text(encoding='utf-8')


class Connection:
    def __init__(self, request):
        self.request = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, *args, **kwargs):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


def request(path, body=None):
    headers = f'{"POST" if body else "GET"} {path} HTTP/1.0\r\nHost: localhost\r\n'
    if body:
        headers += f'X-Session-Viewer: 1\r\nContent-Length: {len(body)}\r\n'
    conn = Connection(headers.encode() + b'\r\n' + (body or b''))
    server.Handler(conn, ('127.0.0.1', 0), None)
    headers, body = bytes(conn.response).split(b'\r\n\r\n', 1)
    assert headers.split()[1] == b'200', headers
    return body


with tempfile.TemporaryDirectory() as folder:
    # Exercise all startup preparation without requiring network permissions.
    with patch.object(server, 'ThreadingHTTPServer'):
        server.main(['--data-dir', folder, '--demo'])
    assert server.FLAGS_DB == Path(folder) / 'flags.sqlite3'
    for path in ('/', '/app.js', '/styles.css'):
        assert request(path)
    sessions = json.loads(request('/api/sessions'))
    assert len(sessions) == 1 and sessions[0]['id'] == 'demo.jsonl'
    events = json.loads(request('/api/sessions/demo.jsonl'))['events']
    assert len(events) == 14 and any(e['related'] for e in events)
    request('/api/flags', json.dumps({'session': 'demo.jsonl', 'line': 4, 'flagged': True, 'note': 'Installation smoke test'}).encode())
    assert json.loads(request('/api/flags'))['demo.jsonl']['4']['note'] == 'Installation smoke test'
print(f'Installed package {__version__}: assets, demo, request handlers, and saved flags OK')

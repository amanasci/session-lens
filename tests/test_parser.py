import json
from pathlib import Path
import tempfile
import io
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from session_lens import server


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'sample.jsonl'

    def parse(self, records):
        self.path.write_text('\n'.join(json.dumps(r) if isinstance(r, dict) else r for r in records))
        return server.load(self.path)

    def test_preserves_lines_unknowns_and_bad_records(self):
        _, events, records = self.parse([
            {'type': 'new_future_event', 'payload': {'new_field': 12}}, '',
            'bad JSON', '[]', {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Fix the parser'}]}}
        ])
        self.assertEqual([e['line'] for e in events], [1, 3, 4, 5])
        self.assertEqual([events[1]['type'], events[2]['type']], ['parse_error', 'parse_error'])
        self.assertEqual(records[1]['payload']['new_field'], 12)
        self.assertEqual(events[-1]['body'], 'Fix the parser')

    def test_links_interleaved_tools_by_call_id(self):
        _, events, _ = self.parse([
            {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'a', 'name': 'exec', 'arguments': '{"cmd":"ls"}'}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'b', 'name': 'patch', 'input': 'patch text'}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'b', 'output': [{'type': 'input_text', 'text': 'done'}]}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'a', 'output': 'files'}}
        ])
        self.assertEqual(events[0]['related'], [4])
        self.assertEqual(events[1]['related'], [3])
        self.assertEqual(events[2]['label'], 'patch · result')
        self.assertEqual(events[2]['body'], 'done')

    def test_encrypted_reasoning_never_claims_to_be_readable(self):
        _, events, records = self.parse([{'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque'}}])
        self.assertIn('no readable reasoning text', events[0]['body'])
        self.assertEqual(records[1]['payload']['encrypted_content'], 'opaque')

    def test_title_skips_environment_and_tracks_turns(self):
        info, events, _ = self.parse([
            {'type': 'session_meta', 'payload': {'id': 's', 'cwd': '/tmp/project'}},
            {'type': 'event_msg', 'payload': {'type': 'task_started'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': '<environment_context>private config</environment_context>'}]}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': 'Fix the bug'}]}},
            {'type': 'turn_context', 'payload': {'model': 'sample-model'}}
        ])
        self.assertEqual(info['title'], 'Fix the bug')
        self.assertEqual(info['model'], 'sample-model')
        self.assertEqual(info['turns'], 1)
        self.assertEqual(events[-1]['turn'], 1)

    def test_large_readable_body_is_bounded_but_raw_is_intact(self):
        text = 'x' * 130000
        _, events, records = self.parse([{'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': text}]}}])
        self.assertIn('truncated', events[0]['body'])
        self.assertEqual(records[1]['payload']['content'][0]['text'], text)


class CliTests(unittest.TestCase):
    def test_demo_and_custom_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(server, 'DATA'), patch.object(server, 'FLAGS_DB'), patch.object(server, 'ThreadingHTTPServer') as http:
                server.main(['--data-dir', folder, '--demo', '--port', '9000'])
                self.assertEqual(server.DATA, Path(folder).resolve() / 'sessions')
                self.assertEqual(server.FLAGS_DB, Path(folder).resolve() / 'flags.sqlite3')
                self.assertEqual(len(server.load(server.DATA / 'demo.jsonl')[1]), 14)
                http.assert_called_once_with(('127.0.0.1', 9000), server.Handler)

    def test_invalid_import_and_port_do_not_start_server(self):
        with patch.object(server, 'ThreadingHTTPServer') as http:
            for argv in (['--port', '0'], ['--port', '65536'], ['--import-dir', '/nonexistent/session-lens-input']):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    server.main(argv)
            http.assert_not_called()

    def test_environment_data_directory(self):
        with patch.dict(server.os.environ, {'SESSION_LENS_DATA_DIR': '~/lens-private'}):
            self.assertEqual(server.default_data_directory(), Path.home() / 'lens-private')


class MemoryConnection:
    """Feed actual HTTP request bytes through the handler without opening sockets."""
    def __init__(self, request):
        self.request = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, *args, **kwargs):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(server, 'DATA', Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        db_patch = patch.object(server, 'FLAGS_DB', Path(self.tmp.name) / 'review' / 'flags.sqlite3')
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def request(self, path, body=None, trusted=True):
        method = 'POST' if body is not None else 'GET'
        headers = f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n'
        if body is not None:
            headers += f'Content-Length: {len(body)}\r\n'
            if trusted:
                headers += 'X-Session-Viewer: 1\r\n'
        conn = MemoryConnection(headers.encode() + b'\r\n' + (body or b''))
        server.Handler(conn, ('127.0.0.1', 0), None)
        response_headers, response_body = bytes(conn.response).split(b'\r\n\r\n', 1)
        return int(response_headers.split()[1]), response_headers, response_body

    def test_import_list_read_and_original_record(self):
        record = {'timestamp': '2026-11-16T12:00:00Z', 'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': '<script>alert(1)</script>'}]}}
        status, _, body = self.request('/api/import', json.dumps(record).encode())
        self.assertEqual(status, 201)
        imported = json.loads(body)
        status, _, body = self.request('/api/sessions')
        self.assertEqual(len(json.loads(body)), 1)
        status, _, body = self.request('/api/sessions/' + imported['id'])
        self.assertEqual(json.loads(body)['events'][0]['body'], '<script>alert(1)</script>')
        status, _, body = self.request('/api/sessions/' + imported['id'] + '/events/1')
        self.assertEqual(json.loads(body), record)
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b"script-src 'self'", headers)

    def test_invalid_import_rejected_without_partial_file(self):
        status, _, _ = self.request('/api/import', b'{}\nnot JSON')
        self.assertEqual(status, 400)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_cross_origin_style_import_rejected(self):
        status, _, _ = self.request('/api/import', b'{}', trusted=False)
        self.assertEqual(status, 403)

    def flag_fixture(self):
        record = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': 'Investigate this'}]}}
        path = server.DATA / 'review.jsonl'
        path.write_text(json.dumps(record))
        return path, record

    def flag_request(self, **updates):
        data = {'session': 'review.jsonl', 'line': 1, 'flagged': True, 'note': 'Ignored failed test'}
        data.update(updates)
        return self.request('/api/flags', json.dumps(data).encode())

    def test_flags_persist_update_and_remove_without_modifying_source(self):
        path, _ = self.flag_fixture()
        original = path.read_bytes()
        status, _, body = self.flag_request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['review.jsonl']['1']['note'], 'Ignored failed test')
        # GET uses a fresh database connection, as it does after a server restart.
        status, _, body = self.request('/api/flags')
        self.assertEqual(json.loads(body)['review.jsonl']['1']['note'], 'Ignored failed test')
        self.flag_request(note='Revised hypothesis')
        _, _, body = self.request('/api/flags')
        self.assertEqual(json.loads(body)['review.jsonl']['1']['note'], 'Revised hypothesis')
        status, _, body = self.flag_request(flagged=False)
        self.assertEqual(json.loads(body), {})
        self.assertEqual(path.read_bytes(), original)

    def test_replaced_event_does_not_inherit_flag(self):
        path, record = self.flag_fixture()
        self.flag_request()
        path.write_text(json.dumps({'type': 'different_event'}))
        _, _, body = self.request('/api/flags')
        self.assertEqual(json.loads(body), {})
        status, _, _ = self.flag_request(fingerprint=server.fingerprint(record))
        self.assertEqual(status, 409)

    def test_flags_validate_event_note_and_origin(self):
        self.flag_fixture()
        for updates, expected in [({'line': 2}, 404), ({'line': True}, 400),
                                  ({'session': '../private.jsonl'}, 400),
                                  ({'note': 'x' * 10001}, 400),
                                  ({'note': {}}, 400), ({'flagged': 'yes'}, 400)]:
            with self.subTest(updates=str(updates)[:70]):
                self.assertEqual(self.flag_request(**updates)[0], expected)
        self.assertEqual(self.request('/api/flags', b'{}', trusted=False)[0], 403)
        self.assertEqual(self.request('/api/flags', b'[]')[0], 400)

    def test_unknown_session_and_path_traversal(self):
        status, _, _ = self.request('/api/sessions/missing.jsonl')
        self.assertEqual(status, 404)
        status, _, _ = self.request('/api/sessions/..%2Fprivate.jsonl')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()

"""Capture actual HTTP bodies so request adaptation cannot pass as a UI-only fix."""
import copy
import http.client
import io
import json
import queue
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'manager'))
from tfmanager.gateway import completion, proxy, validate_payload
from tfmanager.state import APIError, Store


class GatewayThinkingTests(unittest.TestCase):
    def setUp(self):
        self.received = queue.Queue()
        received = self.received

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.put(data)
                if data.get('stream'):
                    body = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
                else:
                    body = b'{"choices":[{"message":{"content":"ok"}}]}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        port = server.server_port

        class Engine:
            def status(self):
                return {'model': '/fixture/model', 'served_name': 'fixture'}

            def request_metadata(self):
                return {'engine_version': 'fixture'}

            @contextmanager
            def request(self):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    yield conn
                finally:
                    conn.close()

        self.engine = Engine()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.addCleanup(self.store.close)
        client, self.browser = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(self.browser.close)
        self.handler = SimpleNamespace(connection=client, wfile=io.BytesIO(),
            send_response=lambda *args: None, send_header=lambda *args: None,
            security_headers=lambda: None, end_headers=lambda: None, respond=lambda *args: None)
        self.app = SimpleNamespace(engine=self.engine, store=self.store)

    def test_both_clients_forward_canonical_thinking_and_record_actual_parameters(self):
        for internal in (False, True):
            for stream in (False, True):
                for thinking in (False, True):
                    with self.subTest(internal=internal, stream=stream, thinking=thinking):
                        request = {'messages': [{'role': 'user', 'content': 'fixture'}],
                            'stream': stream, 'enable_thinking': thinking,
                            'chat_template_kwargs': {'custom_template_option': 'preserved'}}
                        original = copy.deepcopy(request)
                        if internal:
                            completion(self.engine, self.store, request, observe_stream=stream)
                        else:
                            proxy(self.handler, self.app, '/v1/chat/completions', request)
                        actual = self.received.get(timeout=1)
                        self.assertNotIn('enable_thinking', actual)
                        self.assertEqual(actual['chat_template_kwargs'],
                            {'custom_template_option': 'preserved', 'enable_thinking': thinking})
                        self.assertEqual(actual['stream'], stream)
                        recorded = self.store.stats()['requests'][0]['parameters']
                        self.assertEqual(recorded['chat_template_kwargs'], actual['chat_template_kwargs'])
                        self.assertNotIn('enable_thinking', recorded)
                        self.assertEqual(request, original)

    def test_invalid_or_conflicting_thinking_never_reaches_upstream(self):
        invalid = [
            {'enable_thinking': value} for value in (None, 0, 1, 'false', [], {})
        ] + [
            {'chat_template_kwargs': {'enable_thinking': value}} for value in (None, 0, 1, 'false')
        ] + [
            {'chat_template_kwargs': value} for value in (None, [], 'false')
        ] + [
            {'enable_thinking': False, 'chat_template_kwargs': {'enable_thinking': True}},
            {'enable_thinking': True, 'chat_template_kwargs': {'enable_thinking': False}},
        ]
        for internal in (False, True):
            for fields in invalid:
                with self.subTest(internal=internal, fields=fields):
                    data = {'messages': [{'role': 'user', 'content': 'fixture'}], **fields}
                    with self.assertRaises(APIError):
                        if internal:
                            completion(self.engine, self.store, data)
                        else:
                            proxy(self.handler, self.app, '/v1/chat/completions', data)
                    self.assertTrue(self.received.empty())

    def test_canonical_and_equal_duplicate_inputs_preserve_standard_kwargs(self):
        for fields in ({}, {'enable_thinking': False}):
            kwargs = {'enable_thinking': False, 'reasoning_effort': 'none', 'custom': {'a': 1}}
            data = {'messages': [{'role': 'user', 'content': 'fixture'}], 'chat_template_kwargs': kwargs, **fields}
            result = validate_payload(data)
            self.assertNotIn('enable_thinking', result)
            self.assertEqual(result['chat_template_kwargs'], kwargs)
        self.assertNotIn('chat_template_kwargs', validate_payload({'messages': ['fixture']}))

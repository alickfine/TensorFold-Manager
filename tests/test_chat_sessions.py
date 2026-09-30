import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'manager'))
from tfmanager.state import APIError, Store
from test_backend_server import ServerTests


class ChatSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)

    def test_legacy_history_migrates_once_without_removing_original(self):
        messages = [{'role': 'user', 'content': 'Old question'}, {'role': 'assistant', 'content': 'Old answer'}]
        self.store.history_save({'messages': messages})
        first = self.store.chat_sessions()
        self.assertEqual(len(first), 1)
        self.assertEqual(self.store.chat_session(first[0]['id'])['messages'], messages)
        self.assertEqual(self.store.history()['messages'], messages)
        self.assertEqual(self.store.chat_sessions(), first)
        reopened = Store(self.tmp.name)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.chat_sessions(), first)

    def test_sessions_keep_messages_and_titles_isolated_with_revision_check(self):
        first = self.store.chat_session_create({'title': 'One'})
        second = self.store.chat_session_create({'title': 'Two'})
        one = self.store.chat_session_update(first['id'], {'revision': first['revision'], 'messages': [{'role': 'user', 'content': 'one'}]})
        self.store.chat_session_update(second['id'], {'revision': second['revision'], 'messages': [{'role': 'user', 'content': 'two'}]})
        self.assertEqual(self.store.chat_session(first['id'])['messages'][0]['content'], 'one')
        self.assertEqual(self.store.chat_session(second['id'])['messages'][0]['content'], 'two')
        self.assertNotIn('messages', self.store.chat_sessions()[0])
        with self.assertRaises(APIError) as conflict:
            self.store.chat_session_update(first['id'], {'revision': first['revision'], 'title': 'stale'})
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(one['title'], 'One')

    def test_session_validation_rejects_bad_id_title_and_content(self):
        for payload in ({'title': ''}, {'title': 'a' * 121}, {'title': '<script>' * 20}):
            with self.assertRaises(APIError): self.store.chat_session_create(payload)
        session = self.store.chat_session_create({'title': 'Safe'})
        for messages in ([{'role': 'agent', 'content': 'x'}], [{'role': 'user', 'content': object()}], [{'role': 'user', 'content': 'x' * 1000001}]):
            with self.assertRaises(APIError): self.store.chat_session_update(session['id'], {'revision': 0, 'messages': messages})
        with self.assertRaises(APIError): self.store.chat_session('../bad')


class ChatSessionAPITests(unittest.TestCase):
    setUp = ServerTests.setUp
    request = ServerTests.request
    def test_session_endpoints_require_auth_and_preserve_isolation(self):
        self.assertEqual(self.request('/api/chat/sessions', token=None)[0], 401)
        status, raw = self.request('/api/chat/sessions', 'POST', {'title': 'First'})
        self.assertEqual(status, 200)
        first = json.loads(raw)
        status, raw = self.request('/api/chat/sessions', 'POST', {'title': 'Second'})
        self.assertEqual(status, 200)
        second = json.loads(raw)
        body = {'revision': first['revision'], 'messages': [{'role': 'user', 'content': 'hello'}]}
        self.assertEqual(self.request(f"/api/chat/sessions/{first['id']}", 'PUT', body)[0], 200)
        self.assertEqual(json.loads(self.request(f"/api/chat/sessions/{second['id']}")[1])['messages'], [])
        listing = json.loads(self.request('/api/chat/sessions')[1])['sessions']
        self.assertEqual(len(listing), 2)
        self.assertNotIn('messages', listing[0])

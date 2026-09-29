import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'manager'))
try:
    from tfmanager.state import Store, APIError
except ImportError:
    Store = None

class StateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Store, 'persistent backend not implemented')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)); self.addCleanup(self.store.close)
    def test_settings_survive_restart_and_reject_shell_and_engine_override(self):
        self.store.settings_update({'temperature':0.4,'engine_port':18888})
        other=Store(Path(self.tmp.name)); self.addCleanup(other.close)
        self.assertEqual(other.settings()['temperature'],0.4)
        for value in ({'engine_port':8089},{'engine_port':'1; touch /tmp/x'}, {'engine_python':'/tmp/x'}, {'parallel':'$(id)'}, {'snapshot_dir':'/tmp/external'}):
            with self.assertRaises(APIError): self.store.settings_update(value)
    def test_keys_are_hash_only_expire_toggle_and_revoke(self):
        key=self.store.key_create({'name':'test','expires_days':1})
        self.assertTrue(self.store.key_valid(key['key']))
        self.assertFalse(self.store.key_valid('wrong'))
        self.assertNotIn(key['key'],str(self.store.keys()))
        self.store.key_toggle(key['id']); self.assertFalse(self.store.key_valid(key['key']))
        self.store.key_toggle(key['id']); self.store.key_delete(key['id'])
        self.assertFalse(self.store.key_valid(key['key']))
        self.assertNotIn(key['key'].encode(), (Path(self.tmp.name)/'state.sqlite3').read_bytes())
    def test_profiles_history_and_stats_persist_and_null_metrics(self):
        p=self.store.profile_save({'name':'work','config':{'temperature':0.2}})
        self.assertEqual(self.store.profiles()[0]['id'],p['id'])
        self.store.history_save({'messages':[{'role':'user','content':'hello'}]})
        self.assertEqual(self.store.history()['messages'][0]['content'],'hello')
        self.store.record_request({'model':'a','status':200,'elapsed':1.5,'output_tokens':3})
        stats=self.store.stats(); self.assertEqual(stats['total']['requests'],1)
        self.assertIsNone(stats['requests'][0]['prefill_tps'])
        self.store.profile_delete(p['id']); self.assertEqual(self.store.profiles(),[])
    def test_logs_redact_secrets(self):
        self.store.log('error','Authorization: Bearer secret-token tfm_live_12345')
        self.assertNotIn('secret-token',str(self.store.logs()))

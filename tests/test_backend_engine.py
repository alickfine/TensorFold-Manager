import json,os,socket,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import Store,APIError
try:
 from tfmanager.engine import Engine
 from tfmanager.models import Models
except ImportError: Engine=None
FIXTURE=Path(__file__).parent/'fixtures/engine.py'
def freeport():
 with socket.socket() as s: s.bind(('127.0.0.1',0)); return s.getsockname()[1]
def wait_state(engine,state):
 for _ in range(150):
  result=engine.status()
  if result['state']==state:return result
  time.sleep(.03)
 raise AssertionError(str(engine.status()))
class EngineTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Engine,'engine implementation missing')
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.store=Store(self.tmp.name); self.addCleanup(self.store.close)
  self.store.settings_update({'engine_port':freeport()})
  self.models=Models(self.store)
  self.model=Path(self.tmp.name)/'models'/'Vontra--Qwen3.8-27B-MLX-4bit'; self.model.mkdir(parents=True)
  (self.model/'config.json').write_text(json.dumps({'model_type':'qwen3_5','_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'})); (self.model/'model.safetensors').write_bytes(b'fixture')
  self.engine=Engine(self.store,self.models,command=[sys.executable,str(FIXTURE)],startup_timeout=3,stop_timeout=2); self.addCleanup(lambda:self.engine.stop(force=True))
 def test_start_ready_pending_and_stop_owned_child(self):
  self.engine.start(str(self.model)); state=wait_state(self.engine,'ready'); self.assertIsInstance(state['pid'],int)
  self.store.settings_update({'temperature':.2}); self.assertTrue(self.engine.status()['pending'])
  self.engine.stop(); self.assertEqual(self.engine.status()['state'],'stopped')
 def test_port_conflict_never_spawns_or_adopts_listener(self):
  with socket.socket() as listener:
   listener.bind(('127.0.0.1',self.store.settings()['engine_port'])); listener.listen()
   with self.assertRaises(APIError): self.engine.start(str(self.model))
   self.assertIsNone(self.engine.status()['pid'])
 def test_failed_process_is_not_ready(self):
  failed=self.model.parent/'fail-model'; self.model.rename(failed)
  self.engine.start(str(failed)); state=wait_state(self.engine,'failed'); self.assertIn('exited',state['error'])
 def test_unknown_model_and_command_injection_rejected(self):
  for model in ('--help','owner/model;echo bad','/tmp/not-in-model-roots'):
   with self.assertRaises(APIError): self.engine.start(model)
 def test_scan_detects_real_weights_and_unsupported_checkpoint(self):
  rows=self.models.scan(); self.assertTrue(rows[0]['installed']); self.assertTrue(rows[0]['supported'])
  (self.model/'model.safetensors').unlink(); self.assertFalse(self.models.scan()[0]['installed'])

class EngineProbeTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_cli_info_rejects_unsupported_weights_before_spawn(self):
  (self.model/'reject-info').write_text('incompatible quantization')
  with self.assertRaisesRegex(APIError,'incompatible quantization'):self.engine.start(str(self.model))
  self.assertIsNone(self.engine.status()['pid'])

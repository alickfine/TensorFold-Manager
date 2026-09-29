import json,os,socket,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import Store,APIError
from fixtures.resources import FixtureGate
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
  self.engine=Engine(self.store,self.models,command=[sys.executable,str(FIXTURE)],startup_timeout=3,stop_timeout=2,resources=FixtureGate(self.store)); self.addCleanup(lambda:self.engine.stop(force=True))
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

class ModelConfigurationTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_saved_model_configuration_is_pending_until_restart(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  self.models.configure({'model':str(self.model),'config':{'temperature':0.1}})
  self.assertTrue(self.engine.status()['pending'])

class LocalVariantTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_explicit_cli_validation_allows_variant_and_invalidates_changes(self):
  (self.model/'config.json').write_text(json.dumps({'model_type':'qwen3_5','quantization':{'bits':4}}))
  variant=self.model.parent/'Local-Qwen-Variant';self.model.rename(variant)
  self.assertFalse(self.models.describe(variant)['supported'])
  self.assertTrue(hasattr(self.engine,'validate_model'),'explicit local variant validation missing')
  result=self.engine.validate_model(str(variant));self.assertEqual(result['validation']['scope'],'cli_compatibility_only')
  self.assertTrue(self.models.describe(variant)['supported'])
  self.engine.start(str(variant));wait_state(self.engine,'ready');self.engine.stop()
  (variant/'config.json').write_text('{"model_type":"unknown"}')
  self.assertFalse(self.models.describe(variant)['supported'])
 def test_validation_rejects_out_of_scope_or_upstream_incompatible(self):
  self.assertTrue(hasattr(self.engine,'validate_model'),'explicit local variant validation missing')
  with self.assertRaises(APIError):self.engine.validate_model('/tmp/not-a-model')
  (self.model/'reject-info').write_text('Unsupported quantization')
  with self.assertRaisesRegex(APIError,'Unsupported quantization'):self.engine.validate_model(str(self.model))
  self.assertIsNone(self.store.get('model_validation',str(self.model)))

class ResourceLifecycleTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_same_model_configuration_start_is_idempotent(self):
  self.engine.start(str(self.model));first=wait_state(self.engine,'ready')
  again=self.engine.start(str(self.model));self.assertEqual(first['pid'],again['pid']);self.assertEqual(again['state'],'ready')
  self.store.settings_update({'selected_model':str(self.model)})
  self.assertEqual(self.engine.start(str(self.model))['pid'],first['pid'])
  self.models.configure({'model':str(self.model),'config':{'temperature':0.3}})
  with self.assertRaisesRegex(APIError,'Stop the current engine'):self.engine.start(str(self.model))
  self.assertEqual(first['pid'],self.engine.status()['pid'])
 def test_empty_safetensor_never_installed_or_validated(self):
  (self.model/'model.safetensors').write_bytes(b'')
  self.assertFalse(self.models.describe(self.model)['installed'])
  with self.assertRaises(APIError):self.engine.validate_model(str(self.model))
  (self.model/'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'x':'model.safetensors'}}))
  self.assertFalse(self.models.describe(self.model)['installed'])
 def test_attached_proxy_is_read_only_and_detach_leaves_external_process(self):
  from tfmanager.resources import ResourceGate
  from test_backend_resources import Observer
  from tfmanager.gateway import completion
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  observer=Observer();settings=self.store.settings();flags={k.replace('_','-'):str(settings[k]) for k in ('context','max_tokens','temperature','top_p','top_k','parallel','prompt_cache_gib','mlx_cache_gib')}
  flags.update(host='127.0.0.1',port=str(settings['engine_port']),thinking=settings['thinking'],name=self.engine.data['served_name'],**{'snapshot-dir':str(self.store.snapshots)})
  observer.services=[{'pid':self.engine.status()['pid'],'uid':os.getuid(),'kind':'tensorfold','start_time':'fixture','command_signature':'fixture','model_path':str(self.model.resolve()),'flags':flags,'identity_complete':True,'listening_ports':[settings['engine_port']],'health':{'status':'ok'},'model_ids':[self.engine.data['served_name']]}]
  gate=ResourceGate(self.store,observer=observer,lock_dir=self.store.root/'attached-fixture-locks')
  gate.estimate=lambda *args,**kwargs:{'required_bytes':None,'missing':['fixture'],'components':{}}
  attached=Engine(self.store,self.models,resources=gate);self.addCleanup(attached.detach)
  self.assertEqual(attached.start(str(self.model))['control_owner'],'external')
  self.assertEqual(attached.status()['state'],'attached');self.assertIsNone(attached.proc)
  response,_=completion(attached,self.store,{'messages':[{'role':'user','content':'hello'}]});self.assertTrue(response['choices'])
  with self.assertRaisesRegex(APIError,'read-only'):attached.stop()
  from unittest.mock import patch
  log=self.model/'fixture-request-log';log.write_text('')
  for stream in (False,True):
   with patch.object(attached.native,'bind',return_value=('replacement',)):
    with self.assertRaises(APIError):completion(attached,self.store,{'messages':[{'role':'user','content':'PRIVATE PROMPT'}]},observe_stream=stream)
  self.assertEqual(log.read_text(),'')
  attached.detach();self.assertEqual(self.engine.status()['state'],'ready')

class DraftIsolationTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_nemotron_mtp_source_is_explicitly_budgeted_or_disabled(self):
  from unittest.mock import patch
  with patch.dict(os.environ,{'TF_NEMOTRON_MTP':'/unexpected/user/cache/mtp.safetensors'}):
   self.engine.start(str(self.model));wait_state(self.engine,'ready')
   self.assertEqual(self.engine.verify_api(self.store.settings()['engine_port'])['fixture_mtp_source'],'0');self.engine.stop()
   draft=self.model/'mtp-4bit.safetensors';draft.write_bytes(b'fixture-draft')
   self.engine.start(str(self.model));wait_state(self.engine,'ready')
   self.assertEqual(self.engine.verify_api(self.store.settings()['engine_port'])['fixture_mtp_source'],str(draft.resolve()))

class SupervisorLeaseTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_engine_retains_lease_if_supervisor_dies_until_natural_exit(self):
  (self.model/'fixture-exit-after').write_text('2')
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  supervisor=self.engine.proc;supervisor.kill();supervisor.wait(timeout=2)
  if self.engine.reader:self.engine.reader.join(timeout=2)
  with self.assertRaises(APIError):self.engine.resources.acquire_quantize(self.model,{})
  with self.assertRaisesRegex(APIError,'child exit is unconfirmed'):self.engine.stop()
  self.assertEqual(self.engine.status()['state'],'failed');self.assertFalse(self.engine.status()['child_exit_confirmed'])
  for _ in range(100):
   try:
    lease=self.engine.resources.acquire_quantize(self.model,{});lease.release();break
   except APIError:time.sleep(.03)
  else:self.fail('Naturally exited fixture did not release inherited lease')

class PeerOwnershipTests(unittest.TestCase):
 setUp=EngineTests.setUp
 def test_port_winner_is_not_owned_child_and_receives_no_http(self):
  import socketserver,threading
  from unittest.mock import patch
  received=[];servers=[]
  class Handler(socketserver.BaseRequestHandler):
   def handle(self):
    self.request.settimeout(2)
    try:received.append(self.request.recv(65536))
    except OSError:received.append(b'')
  original=self.engine.build_command
  def reserve(*args):
   result=original(*args)
   server=socketserver.ThreadingTCPServer(('127.0.0.1',self.store.settings()['engine_port']),Handler);servers.append(server)
   threading.Thread(target=server.serve_forever,daemon=True).start();return result
  (self.model/'fixture-no-listen').write_text('controlled live child without listener');self.engine.startup_timeout=.5
  try:
   with patch.object(self.engine,'build_command',side_effect=reserve):self.engine.start(str(self.model))
   wait_state(self.engine,'failed');self.assertIsNone(self.engine.proc.poll());self.assertFalse(self.engine.status()['health'])
   with self.assertRaises(APIError):
    with self.engine.request():pass
   self.assertTrue(received);self.assertEqual(b''.join(received),b'')
  finally:
   self.engine.stop(force=True)
   for server in servers:server.shutdown();server.server_close()
 def test_restart_impossible_target_does_not_stop_current_child(self):
  from unittest.mock import patch
  self.engine.start(str(self.model));first=wait_state(self.engine,'ready')
  with patch.object(self.engine.resources,'preflight_capacity',return_value={'allowed':False,'missing':[],'blockers':['physical_capacity']}):
   with self.assertRaises(APIError):self.engine.restart(str(self.model))
  self.assertEqual(self.engine.status()['pid'],first['pid']);self.assertEqual(self.engine.status()['state'],'ready')

 def test_request_keeps_original_instance_during_forced_restart(self):
  self.engine.start(str(self.model));first=wait_state(self.engine,'ready');log=self.model/'fixture-request-log'
  with self.engine.request() as original_connection:
   self.engine.stop(force=True);self.engine.start(str(self.model));second=wait_state(self.engine,'ready');self.assertNotEqual(first['pid'],second['pid']);log.write_text('')
   with self.assertRaises(APIError):original_connection.request('POST','/v1/chat/completions',b'PRIVATE ORIGINAL PROMPT')
   self.assertEqual(log.read_text(),'')

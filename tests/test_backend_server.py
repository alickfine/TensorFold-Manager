import http.client,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from test_backend_engine import FIXTURE,freeport,wait_state
from fixtures.resources import FixtureGate
try:
 from tfmanager.server import Application
except ImportError: Application=None
class ServerTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Application,'HTTP layer missing')
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.app=Application(Path(self.tmp.name)/'data',Path(self.tmp.name)/'web','admin-secret',engine_command=[sys.executable,str(FIXTURE)],resource_factory=FixtureGate)
  self.app.store.settings_update({'gateway_port':freeport(),'engine_port':freeport()})
  self.app.start(port=0,check_updates=False);self.addCleanup(self.app.shutdown)
  self.port=self.app.http.server_port
 def request(self,path,method='GET',body=None,token='admin-secret',headers=None,port=None):
  c=http.client.HTTPConnection('127.0.0.1',port or self.port,timeout=5)
  h={'Authorization':'Bearer '+token} if token else {}
  if body is not None:h['Content-Type']='application/json'
  h.update(headers or {});c.request(method,path,json.dumps(body) if body is not None else None,h);r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
 def test_model_discovery_job_registers_directory_and_is_readable_from_state(self):
  from unittest.mock import patch
  disk=Path(self.tmp.name)/'disk';model=disk/'nested/model';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'model_type':'qwen3_5','_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  from tfmanager.discovery import ModelDiscovery
  with patch.object(self.app,'discovery',ModelDiscovery(self.app.models,roots=[disk]),create=True):
   status,data=self.request('/api/models/discover','POST',{})
   self.assertEqual(status,200);row=json.loads(data)
   for _ in range(100):
    current=self.app.jobs.get(row['id'])
    if current['status'] in ('completed','failed'):break
    time.sleep(.01)
  self.assertEqual(current['status'],'completed',current)
  self.assertIn(str(model.resolve()),self.app.store.settings()['model_dirs'])
 def test_probe_scheduler_does_not_reuse_finished_runner_with_stale_persisted_status(self):
  from unittest.mock import patch
  for _ in range(100):
   if self.app.probe_active is None:break
   time.sleep(.01)
  with patch.object(self.app.jobs,'_start',return_value=None):
   predecessor=self.app.jobs.create('model_probe',{'engine_identity':{'version':'old'}})
  predecessor['status']='running';self.app.store.put('job',predecessor,predecessor['id'])
  successor=self.app.schedule_model_probe()
  self.assertNotEqual(successor['id'],predecessor['id'])
 def test_probe_refresh_during_old_identity_eventually_checks_new_identity(self):
  from unittest.mock import patch
  entered=threading.Event();release=threading.Event();identities=[]
  for _ in range(100):
   if all(r['status'] not in ('running','queued') for r in self.app.jobs.list()):break
   time.sleep(.01)
  model=self.app.store.root/'models/probe';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'model_type':'qwen3_5','_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  current={'version':'old'}
  def validate(path):
   identities.append(current['version'])
   if len(identities)==1:entered.set();release.wait(2)
  with patch.object(self.app.engine,'validation_identity',side_effect=lambda:current.copy()),patch.object(self.app.engine,'validate_model',side_effect=validate):
   self.app.refresh_models();self.assertTrue(entered.wait(2))
   current['version']='new';self.app.refresh_models();release.set()
   for _ in range(200):
    if 'new' in identities and all(r['status'] not in ('running','queued') for r in self.app.jobs.list()):break
    time.sleep(.01)
   self.assertIn('new',identities)
 def test_auth_host_origin_and_state_instance(self):
  self.assertEqual(self.request('/api/state',token=None)[0],401)
  self.assertEqual(self.request('/api/state',headers={'Host':'evil.test'})[0],403)
  self.assertEqual(self.request('/api/state',headers={'Origin':'null'})[0],403)
  self.assertEqual(self.request('/api/state',headers={'Origin':'http://evil.test'})[0],403)
  status,data=self.request('/api/state');self.assertEqual(status,200);self.assertEqual(json.loads(data)['instance_id'],self.app.instance_id)
  c=http.client.HTTPConnection('127.0.0.1',self.port);c.putrequest('GET','/api/state');c.putheader('Host',f'127.0.0.1:{self.port}');c.putheader('Authorization','Bearer admin-secret');c.endheaders();self.assertEqual(c.getresponse().status,403);c.close()
 def test_stream_proxy_records_usage_and_gateway_requires_issued_key(self):
  model=self.app.store.root/'models'/'qwen';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  self.assertEqual(self.request('/api/engine/start','POST',{'model':str(model)})[0],200);wait_state(self.app.engine,'ready')
  status,data=self.request('/api/chat/completions','POST',{'messages':[{'role':'user','content':'hello'}],'stream':True});self.assertEqual(status,200);self.assertIn(b'[DONE]',data)
  self.assertEqual(self.app.store.stats()['total']['output_tokens'],1)
  port=self.app.gateway.server_port;self.assertEqual(self.request('/v1/models',port=port)[0],401)
  key=self.app.store.key_create({'name':'test'})['key'];self.assertEqual(self.request('/v1/models',token=key,port=port)[0],200)
 def test_cache_requires_stopped_and_owned_manifest(self):
  self.assertEqual(self.request('/api/cache/clear','POST',{'confirm':False})[0],400)
  snap=self.app.store.snapshots/'owned';snap.write_text('cache');self.assertEqual(self.request('/api/cache/clear','POST',{'confirm':True})[0],200);self.assertFalse(snap.exists())
  (self.app.store.snapshots/'.tfmanager-owned').unlink();self.assertEqual(self.request('/api/cache/clear','POST',{'confirm':True})[0],409)
 def test_capability_errors_are_not_simulated_success(self):
  for path in ('/api/tools/upload',):
   status,data=self.request(path,'POST',{});self.assertEqual(status,409);self.assertEqual(json.loads(data)['error']['code'],'unsupported_capability')
 def test_parent_pipe_eof_exits_manager_and_ready_contract(self):
  env=dict(os.environ,TFM_ADMIN_TOKEN='secret',TFM_BOOTSTRAP_NONCE='nonce',TFM_DISABLE_UPDATE_CHECK='1',PYTHONPATH=str(Path(__file__).resolve().parents[1]/'manager'))
  proc=subprocess.Popen([sys.executable,'-m','tfmanager.server','--data-dir',str(Path(self.tmp.name)/'child'),'--web-dir',self.tmp.name,'--port','0','--parent-pipe'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
  self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
  row=json.loads(proc.stdout.readline());self.assertEqual(row['pid'],proc.pid);self.assertEqual(row['bootstrap_nonce'],'nonce');self.assertEqual(row['event'],'ready')
  proc.stdin.close();proc.wait(timeout=8);self.assertEqual(proc.returncode,0);proc.stdout.close();proc.stderr.close()

class BenchmarkTests(unittest.TestCase):
 setUp=ServerTests.setUp
 request=ServerTests.request
 def test_benchmark_records_observed_first_token_time(self):
  model=self.app.store.root/'models'/'qwen';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  self.app.engine.start(str(model));wait_state(self.app.engine,'ready')
  status,raw=self.request('/api/benchmark','POST',{'prompt':'hello','runs':1,'max_tokens':1});self.assertEqual(status,200);id=json.loads(raw)['id']
  for _ in range(100):
   job=self.app.jobs.get(id)
   if job['status'] in ('completed','failed'):break
   time.sleep(.02)
  self.assertEqual(job['status'],'completed');self.assertIsInstance(job['result']['results'][0]['ttft'],float)
  self.assertEqual(job['result']['results'][0]['output_tokens'],1)

class StreamEdgeTests(unittest.TestCase):
 setUp=ServerTests.setUp
 request=ServerTests.request
 def start_engine(self):
  model=self.app.store.root/'models'/'qwen';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  self.app.engine.start(str(model));wait_state(self.app.engine,'ready')
 def test_truncated_stream_records_error(self):
  self.start_engine();self.request('/api/chat/completions','POST',{'messages':[{'role':'user','content':'incomplete'}],'stream':True})
  record=self.app.store.stats()['requests'][0]
  self.assertEqual(record['status'],502);self.assertIn('before completion',record['error'])
 def test_benchmark_cancel_interrupts_prefill(self):
  self.start_engine();_,raw=self.request('/api/benchmark','POST',{'prompt':'slow','runs':1,'max_tokens':1});id=json.loads(raw)['id'];time.sleep(.2)
  self.request('/api/jobs/'+id+'/cancel','POST',{})
  for _ in range(50):
   row=self.app.jobs.get(id)
   if row['status']=='cancelled':break
   time.sleep(.02)
  self.assertEqual(row['status'],'cancelled')

class AppVersionTests(unittest.TestCase):
 def test_native_app_version_is_reported(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'TFM_APP_VERSION':'1.2.3-test'}):
   app=Application(Path(root)/'data',root,'token',resource_factory=FixtureGate)
   try:self.assertEqual(app.state()['app_version'],'1.2.3-test')
   finally:app.shutdown()

class ResourceServerTests(unittest.TestCase):
 setUp=ServerTests.setUp
 request=ServerTests.request
 def test_second_application_rejected_before_store_initialization(self):
  from unittest.mock import patch
  from tfmanager.state import APIError
  before=self.app.store.settings();jobs=self.app.jobs.list()
  with patch('tfmanager.server.Store',side_effect=AssertionError('Store must not be constructed')):
   with self.assertRaises(APIError):Application(self.app.store.root,self.app.web_dir,'second',resource_factory=FixtureGate)
  self.assertEqual(before,self.app.store.settings());self.assertEqual(jobs,self.app.jobs.list())
 def test_resources_and_accuracy_api_have_real_state(self):
  status,data=self.request('/api/resources');self.assertEqual(status,200);self.assertIn('memory',json.loads(data))
  status,data=self.request('/api/state');self.assertIn('resources',json.loads(data))
  status,data=self.request('/api/accuracy');self.assertEqual(status,200);self.assertIsInstance(json.loads(data),dict)
 def test_update_loop_wait_is_interruptible_on_shutdown(self):
  from unittest.mock import patch
  with patch.object(self.app.updates,'check') as check:
   worker=threading.Thread(target=self.app._update_loop);worker.start()
   for _ in range(50):
    if check.call_count:break
    time.sleep(.01)
   self.app.update_stop.set();worker.join(timeout=1);self.assertFalse(worker.is_alive());self.assertEqual(check.call_count,1)

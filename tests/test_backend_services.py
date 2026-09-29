import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import APIError
try:
 from tfmanager.services import Services
except ImportError:Services=None

class BindingTests(unittest.TestCase):
 def test_native_binding_module_exists(self):
  self.assertIsNotNone(Services,'instance-bound external lifecycle missing')
 def test_request_never_accepts_client_pid_or_audit_token(self):
  self.assertIsNotNone(Services,'instance-bound external lifecycle missing')
  obj=object.__new__(Services)
  for request in ({'pid':42,'model':'/m','confirm':True},{'snapshot_id':'x','model':'/m','confirm':True,'audit_token':[1]*8},{'snapshot_id':'x','model':'/m','confirm':False}):
   with self.assertRaises(APIError):obj.switch(request)

from unittest.mock import Mock,MagicMock
import threading,time,subprocess,platform
from tfmanager.services import NativeInstances
class ServicesTests(unittest.TestCase):
 def setUp(self):
  self.store=Mock();self.jobs=Mock();self.jobs.create.side_effect=lambda kind,params:{'kind':kind,'params':params}
  self.engine=Mock();self.engine.data={'state':'stopped'};self.engine.proc=None;self.engine.attachment=None;self.engine.lifecycle=threading.RLock();self.engine.prepare_start.return_value=({'path':'/target'}, {}, {})
  self.resources=Mock();self.resources.estimate.return_value={'required_bytes':100,'missing':[]};self.resources.preflight_start.return_value={'allowed':True,'attachment':None}
  self.lease=Mock();self.resources.acquire_switch.return_value=self.lease
  self.service={'pid':42,'uid':os.getuid(),'kind':'tensorfold','executable':'/python','start_time':'today','command_signature':'abc','model_path':'/old','listening_ports':[43219],'port':43219,'health':{'status':'ok'},'argv_verified':True}
  self.resources.snapshot.return_value={'services':[self.service]};self.resources.observer.identity.return_value=self.service
  self.native=Mock();self.native.bind.return_value=('private-token',);self.native.alive.return_value=False
  self.services=Services(self.store,self.jobs,self.engine,self.resources,native=self.native,timeout=.01)
 def confirm(self):
  public=self.services.list();self.assertNotIn('private-token',json.dumps(public));row=public['services'][0]
  return self.services.switch({'snapshot_id':row['snapshot_id'],'model':'/target','confirm':True})
 def run_confirmed(self):
  row=self.confirm();job=Mock();job.params=row['params'];return self.services.run_switch(job)
 def test_success_sends_one_bound_sigterm_and_transfers_lease(self):
  with patch.object(self.services,'endpoints_down',return_value=True):self.run_confirmed()
  self.native.terminate.assert_called_once_with(('private-token',));self.engine.start.assert_called_once_with('/target',allow_attach=False,_lease=self.lease);self.lease.release.assert_not_called()
 def test_snapshot_is_one_use_and_monotonic_expiry_is_enforced(self):
  public=self.services.list();key=public['services'][0]['snapshot_id'];data={'snapshot_id':key,'model':'/target','confirm':True}
  self.services.switch(data)
  with self.assertRaises(APIError):self.services.switch(data)
  self.services.snapshots[key]['expires']=0;job=Mock();job.params={'snapshot_id':key,'model':'/target'}
  with self.assertRaises(APIError):self.services.run_switch(job)
  self.native.terminate.assert_not_called();self.engine.start.assert_not_called()
 def test_changed_instance_never_signalled_or_started(self):
  row=self.confirm();self.native.bind.return_value=('replacement-instance',);job=Mock();job.params=row['params']
  with self.assertRaises(APIError):self.services.run_switch(job)
  self.native.terminate.assert_not_called();self.engine.start.assert_not_called();self.lease.release.assert_called_once()
 def test_permission_error_disables_external_control(self):
  self.native.bind.side_effect=APIError('Permission denied')
  row=self.services.list()['services'][0];self.assertFalse(row['control']['supported']);self.assertIsNone(row['snapshot_id'])
 def test_unknown_target_budget_leaves_old_service_running(self):
  self.resources.estimate.return_value={'required_bytes':None,'missing':['architecture']}
  with self.assertRaises(APIError):self.run_confirmed()
  self.native.terminate.assert_not_called();self.engine.start.assert_not_called()
 def test_exit_port_or_memory_failure_never_starts_target(self):
  for exited,down,allowed in ((False,True,True),(True,False,True),(True,True,False)):
   with self.subTest(exited=exited,down=down,allowed=allowed):
    self.native.alive.return_value=not exited;self.resources.preflight_start.return_value={'allowed':allowed,'attachment':None};self.native.terminate.reset_mock();self.engine.start.reset_mock()
    with patch.object(self.services,'endpoints_down',return_value=down):
     with self.assertRaisesRegex(APIError,'Timed out'):self.run_confirmed()
    self.native.terminate.assert_called_once();self.engine.start.assert_not_called()
 def test_health_model_change_never_signalled(self):
  for change in ({'health':{'status':'ok','model':'changed'}},{'model_ids':['changed']},{'health':{'status':'ok','warming':True}}):
   self.resources.observer.identity.return_value=self.service
   row=self.confirm();self.resources.observer.identity.return_value=self.service|change
   job=Mock();job.params=row['params']
   with self.assertRaises(APIError):self.services.run_switch(job)
   self.native.terminate.assert_not_called();self.engine.start.assert_not_called()
 def test_signal_failure_has_no_fallback_or_start(self):
  self.native.terminate.side_effect=APIError('Kernel rejected')
  with self.assertRaises(APIError):self.run_confirmed()
  self.engine.start.assert_not_called()

class NativeOwnedFixtureTests(unittest.TestCase):
 @unittest.skipUnless(platform.system()=='Darwin','macOS audit-token API')
 def test_real_bound_signal_only_stops_our_spawned_fixture(self):
  from test_backend_engine import FIXTURE,freeport
  from tfmanager.engine import Engine
  native=NativeInstances();self.assertIsNone(native.reason)
  proc=subprocess.Popen([sys.executable,str(FIXTURE),'serve','/controlled-fixture','--port',str(freeport())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   token=native.bind(proc.pid);self.assertTrue(native.alive(token));self.assertEqual(token,native.bind(proc.pid))
   native.terminate(token);proc.wait(timeout=3);self.assertFalse(native.alive(token))
   with self.assertRaises(APIError):native.terminate(token)
  finally:
   if proc.poll() is None:proc.terminate();proc.wait(timeout=3)
 @unittest.skipUnless(platform.system()=='Darwin','macOS audit-token API')
 def test_real_fixture_stop_release_then_owned_target_completion(self):
  from test_backend_engine import FIXTURE,freeport
  from tfmanager.engine import Engine
  from tfmanager.models import Models
  from tfmanager.state import Store
  from tfmanager.jobs import Jobs
  from tfmanager.resources import ResourceGate
  from tfmanager.gateway import completion
  from test_backend_resources import Observer
  with tempfile.TemporaryDirectory() as directory:
   store=Store(directory);jobs=Jobs(store);old_port=freeport();new_port=freeport()
   model=store.root/'models/qwen';model.mkdir(parents=True);(model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit','model_type':'qwen3_5','num_hidden_layers':2,'num_attention_heads':2,'num_key_value_heads':1,'hidden_size':32,'head_dim':16,'intermediate_size':64}));(model/'model.safetensors').write_bytes(b'fixture')
   store.settings_update({'engine_port':new_port,'parallel':1,'context':1024})
   proc=subprocess.Popen([sys.executable,str(FIXTURE),'serve',str(model),'--port',str(old_port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   class ControlledObserver(Observer):
    def capture(self):
     self.services=[service] if proc.poll() is None else []
     return super().capture()
    def identity(self,pid):return service if pid==proc.pid and proc.poll() is None else None
   service={'pid':proc.pid,'uid':os.getuid(),'kind':'tensorfold','executable':sys.executable,'start_time':'controlled-fixture','command_signature':'controlled-fixture','model_path':str(model),'listening_ports':[old_port],'port':old_port,'health':{'status':'ok'},'argv_verified':True}
   observer=ControlledObserver();gate=ResourceGate(store,observer=observer,lock_dir=store.root/'locks');engine=Engine(store,Models(store),command=[sys.executable,str(FIXTURE)],resources=gate,startup_timeout=3,stop_timeout=2)
   try:
    for _ in range(60):
     try:Engine.verify_api(old_port);break
     except Exception:time.sleep(.02)
    else:self.fail('Controlled fixture did not listen')
    services=Services(store,jobs,engine,gate,timeout=3);snapshot=services.list()['services'][0]['snapshot_id'];self.assertTrue(snapshot)
    row=services.switch({'snapshot_id':snapshot,'model':str(model),'confirm':True})
    for _ in range(150):
     row=jobs.get(row['id'])
     if row['status'] in ('completed','failed'):break
     time.sleep(.03)
    self.assertEqual(row['status'],'completed',row);self.assertIsNotNone(proc.poll());self.assertTrue(services.endpoints_down(service))
    result,_=completion(engine,store,{'messages':[{'role':'user','content':'hello'}]});self.assertEqual(result['choices'][0]['message']['content'],'ok')
   finally:
    jobs.shutdown();engine.stop(force=True);store.close()
    if proc.poll() is None:proc.terminate();proc.wait(timeout=3)

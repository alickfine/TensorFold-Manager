import http.client,json,os,signal,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
import test_backend_engine as fixture_engine
from test_backend_engine import FIXTURE,freeport,wait_state
from tfmanager.state import APIError
from tfmanager.jobs import Jobs,Job
from tfmanager.updates import Updates
from tfmanager.gateway import completion

class RecoveryTests(unittest.TestCase):
 setUp=fixture_engine.EngineTests.setUp
 def test_upgrade_and_rollback_keep_os_lease_through_candidate_and_recovery(self):
  for action in ('activate','rollback'):
   for fail in (False,True):
    with self.subTest(action=action,failed_candidate=fail):
     self.engine.start(str(self.model));wait_state(self.engine,'ready')
     jobs=Jobs(self.store);updates=Updates(self.store,jobs,self.engine)
     self.store.put('engine_active',{'version':'old','python':'fixture-old'})
     self.store.put('engine_staged' if action=='activate' else 'engine_previous',{'version':'new','python':'fixture-new'})
     original_put=self.store.put;original_executable=self.engine.executable;blocked=[]
     def put(kind,*args,**kwargs):
      if kind=='engine_recovery':
       with self.assertRaises(APIError):self.engine.resources.acquire_quantize(str(self.model),{})
       blocked.append('after-stop')
      return original_put(kind,*args,**kwargs)
     def executable():
      with self.assertRaises(APIError):self.engine.resources.acquire_quantize(str(self.model),{})
      blocked.append(self.store.get('engine_active')['version'])
      if fail and self.store.get('engine_active')['version']=='new':return [sys.executable,'-c','import sys;sys.exit(7)']
      return original_executable()
     with patch.object(self.store,'put',side_effect=put),patch.object(self.engine,'executable',side_effect=executable):
      job=Job(jobs,{'id':'lease-'+action,'status':'completed','params':{'model':str(self.model)}})
      if fail:
       with self.assertRaisesRegex(APIError,'previous engine API restored'):getattr(updates,'run_'+action)(job)
      else:getattr(updates,'run_'+action)(job)
     self.assertIn('after-stop',blocked);self.assertIn('new',blocked)
     if fail:self.assertIn('old',blocked)
     self.assertEqual(self.engine.status()['state'],'ready')
     self.assertEqual(self.store.get('engine_active')['version'],'old' if fail else 'new')
     self.engine.stop();jobs.shutdown()
     with self.engine.resources.acquire_quantize(str(self.model),{}):pass
 def test_failed_candidate_restores_real_previous_completion(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  good={'version':'v0.0.1','python':'fixture-good'};bad={'version':'v0.0.2','python':'fixture-bad'}
  self.store.put('engine_active',good);self.store.put('engine_staged',bad)
  original=self.engine.executable
  # Replace only the installed CLI boundary: candidate rejects info, old fixture really serves HTTP.
  def executable():
   if self.store.get('engine_active')['version']=='v0.0.2':return [sys.executable,'-c','import sys;sys.exit(7)']
   return original()
  with patch.object(self.engine,'executable',side_effect=executable):
   job=Job(jobs,{'id':'upgrade','params':{'model':str(self.model)}})
   with self.assertRaisesRegex(APIError,'previous engine API restored'):updates.run_activate(job)
  self.assertEqual(self.store.get('engine_active')['version'],'v0.0.1')
  self.assertEqual(self.engine.status()['state'],'ready')
  result,_=completion(self.engine,self.store,{'messages':[{'role':'user','content':'still running'}]});self.assertEqual(result['choices'][0]['message']['content'],'ok')
 def test_failed_candidate_with_different_model_restores_original_model(self):
  import shutil
  target=self.model.parent/'another-model';shutil.copytree(self.model,target)
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'fixture-old'})
  self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  original=self.engine.start_transition;seen=[]
  def start(model,guard,**kwargs):
   seen.append((self.store.get('engine_active')['version'],model))
   if self.store.get('engine_active')['version']=='new':raise APIError('candidate rejected')
   return original(model,guard,**kwargs)
  with patch.object(self.engine,'start_transition',side_effect=start):
   with self.assertRaisesRegex(APIError,'previous engine API restored'):
    updates.run_activate(Job(jobs,{'id':'different-model','params':{'model':str(target)}}))
  self.assertEqual(seen,[('new',str(target)),('old',str(self.model.resolve()))])
  self.assertEqual(self.engine.active_model_id,str(self.model.resolve()))
 def test_external_service_in_fresh_capacity_snapshot_never_stops_current(self):
  self.engine.start(str(self.model));before=wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'fixture-old'});self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  report={'allowed':True,'snapshot':{'services':[{'pid':999}]}}
  with patch.object(self.engine,'preflight_switch',return_value=report),patch.object(self.engine,'stop') as stop:
   with self.assertRaisesRegex(APIError,'External service appeared'):updates.run_activate(Job(jobs,{'id':'fresh-external','params':{}}))
   stop.assert_not_called()
  self.assertEqual(self.engine.status()['pid'],before['pid'])
 def test_incompatible_candidate_is_rejected_before_stopping(self):
  self.engine.start(str(self.model));before=wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'fixture-old'})
  self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  with patch.object(self.engine,'build_command',side_effect=APIError('candidate reader unsupported')),patch.object(self.engine,'stop') as stop:
   with self.assertRaisesRegex(APIError,'reader'):updates.run_activate(Job(jobs,{'id':'incompatible','params':{}}))
   stop.assert_not_called()
  self.assertEqual(self.engine.status()['pid'],before['pid'])
 def test_local_variant_upgrade_refreshes_validation_and_callback_failure_is_nonfatal(self):
  config=json.loads((self.model/'config.json').read_text());config['_name_or_path']='local/custom-checkpoint';(self.model/'config.json').write_text(json.dumps(config))
  self.store.put('engine_active',{'version':'old','python':'fixture-old'})
  self.engine.validation_identity=lambda:{'version':self.store.get('engine_active')['version']}
  self.models.engine_identity=self.engine.validation_identity
  self.engine.validate_model(str(self.model));self.engine.start(str(self.model));wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine,on_change=lambda:(_ for _ in ()).throw(RuntimeError('refresh unavailable')))
  self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  result=updates.run_activate(Job(jobs,{'id':'local-variant','params':{}}))
  self.assertTrue(result['active']['api_verified']);self.assertEqual(self.store.get('engine_active')['version'],'new')
  self.assertTrue(self.models.describe(self.model)['startable'])
 def test_recovery_restores_actual_parameters_and_preserves_pending_edits(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready');original_parameters=self.engine.running_parameters.copy()
  self.store.settings_update({'temperature':.3})
  self.models.configure({'model':str(self.model),'config':{'context':2048}})
  pending=self.store.settings();pending_config=self.store.get('model_config',str(self.model.resolve()))
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'fixture-old'});self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  original=self.engine.start_transition
  def start(model,guard,**kwargs):
   if self.store.get('engine_active')['version']=='new':raise APIError('candidate load failed')
   return original(model,guard,**kwargs)
  with patch.object(self.engine,'start_transition',side_effect=start):
   with self.assertRaisesRegex(APIError,'previous engine API restored'):updates.run_activate(Job(jobs,{'id':'pending','params':{}}))
  self.assertEqual(self.engine.running_parameters,original_parameters)
  self.assertEqual(self.store.settings(),pending);self.assertEqual(self.store.get('model_config',str(self.model.resolve())),pending_config)
  self.assertTrue(self.engine.status()['pending'])
 def test_edits_saved_during_failed_upgrade_are_preserved(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  old_parameters=self.engine.running_parameters.copy()
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'fixture-old'});self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  original=self.engine.start_transition;new_port=freeport();seen=[]
  def start(model,guard,**kwargs):
   if self.store.get('engine_active')['version']=='new':
    self.store.settings_update({'gateway_port':new_port,'temperature':.22})
    seen.append(kwargs['prepared'][2]['temperature'])
    raise APIError('load rejected after saved edits')
   return original(model,guard,**kwargs)
  with patch.object(self.engine,'start_transition',side_effect=start):
   with self.assertRaisesRegex(APIError,'previous engine API restored'):updates.run_activate(Job(jobs,{'id':'edits-during-upgrade','params':{}}))
  self.assertEqual(seen,[old_parameters['temperature']]);self.assertEqual(self.engine.running_parameters,old_parameters)
  self.assertEqual(self.store.settings()['gateway_port'],new_port);self.assertEqual(self.store.settings()['temperature'],.22)
 def test_failed_upgrade_of_stopped_engine_does_not_load_previous_weights(self):
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.settings_update({'selected_model':str(self.model)})
  self.store.put('engine_active',{'version':'old','python':'fixture-old'});self.store.put('engine_staged',{'version':'new','python':'fixture-new'})
  with patch.object(self.engine,'start_transition',side_effect=APIError('candidate load failed')) as start:
   with self.assertRaises(APIError):updates.run_activate(Job(jobs,{'id':'stopped-upgrade','params':{}}))
   self.assertEqual(start.call_count,1)
  self.assertEqual(self.store.get('engine_active')['version'],'old');self.assertEqual(self.engine.status()['state'],'stopped')
 def test_upgrade_job_installs_then_activates_and_refuses_external_service(self):
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.assertIn('engine_upgrade',jobs.runners)
  job=Job(jobs,{'id':'upgrade-flow','params':{'version':'v0.0.2','model':str(self.model)}})
  from unittest.mock import Mock
  candidate={'version':'v0.0.2','python':'fixture-new'}
  with patch.object(updates,'run_install',return_value=candidate) as install,patch.object(updates,'_switch',return_value={'active':candidate}) as switch:
   result=updates.run_upgrade(job)
   self.assertEqual(result['active'],candidate);install.assert_called_once_with(job);switch.assert_called_once_with(candidate,job)
  external={'pid':99,'kind':'tensorfold'}
  with patch.object(self.engine.resources,'snapshot',return_value={'services':[external]}),patch.object(self.engine,'stop') as stop,patch.object(updates,'run_install') as install:
   with self.assertRaisesRegex(APIError,'external'):updates.run_upgrade(job)
   install.assert_not_called();stop.assert_not_called()
 def test_drain_timeout_keeps_previous_environment_running(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  with self.engine.request():
   with self.assertRaisesRegex(APIError,'did not drain'):self.engine.drain(timeout=.02)
  self.assertEqual(self.engine.status()['state'],'ready');self.assertFalse(self.engine.draining)
 def test_supervisor_reaps_engine_after_manager_is_killed(self):
  root=Path(self.tmp.name)/'manager-crash';port=freeport()
  proc=subprocess.Popen([sys.executable,str(FIXTURE.with_name('manager.py')),str(root),str(port),str(freeport())],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
  address=json.loads(proc.stdout.readline())
  model=root/'models/qwen';model.mkdir(parents=True);(model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  def call(path,body=None):
   c=http.client.HTTPConnection('127.0.0.1',address['port']);c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,{'Authorization':'Bearer fixture-token','Content-Type':'application/json'});r=c.getresponse();data=json.loads(r.read());c.close();return data
  call('/api/engine/start',{'model':str(model)})
  for _ in range(100):
   state=call('/api/state')['engine']
   if state['state']=='ready':break
   time.sleep(.03)
  self.assertEqual(state['state'],'ready');pid=state['pid'];proc.kill();proc.wait(timeout=5);proc.stdout.close();proc.stderr.close()
  for _ in range(100):
   try:os.kill(pid,0)
   except ProcessLookupError:break
   time.sleep(.03)
  else:self.fail('Owned engine remained alive after manager crash')
  with socket.socket() as check:self.assertNotEqual(check.connect_ex(('127.0.0.1',port)),0)

class CapacityBeforeUpdateTests(unittest.TestCase):
 setUp=fixture_engine.EngineTests.setUp
 def test_impossible_candidate_model_leaves_previous_running(self):
  self.engine.start(str(self.model));first=wait_state(self.engine,'ready')
  jobs=Jobs(self.store);self.addCleanup(jobs.shutdown);updates=Updates(self.store,jobs,self.engine)
  self.store.put('engine_active',{'version':'old','python':'old'});self.store.put('engine_staged',{'version':'new','python':'new'})
  with patch.object(self.engine.resources,'preflight_capacity',return_value={'allowed':False,'missing':[],'blockers':['physical_capacity']}):
   with self.assertRaises(APIError):updates.run_activate(Job(jobs,{'id':'test','params':{'model':str(self.model)}}))
  self.assertEqual(self.engine.status()['pid'],first['pid']);self.assertEqual(self.store.get('engine_active')['version'],'old')

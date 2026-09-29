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

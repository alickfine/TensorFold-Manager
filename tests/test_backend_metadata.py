import json,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
import test_backend_server as fixtures
from test_backend_engine import wait_state
class BenchmarkMetadataTests(unittest.TestCase):
 setUp=fixtures.ServerTests.setUp
 request=fixtures.ServerTests.request
 def test_benchmark_persists_runtime_snapshot_and_request_overrides(self):
  model=self.app.store.root/'models/qwen';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  self.app.models.configure({'model':str(model),'config':{'name':'local-qwen','thinking_budget':32}})
  self.app.engine.start(str(model));wait_state(self.app.engine,'ready');self.app.store.settings_update({'temperature':0.3})
  _,body=self.request('/api/benchmark','POST',{'prompt':'hello','max_tokens':1,'runs':1});id=json.loads(body)['id']
  for _ in range(100):
   job=self.app.jobs.get(id)
   if job['status'] in ('completed','failed'):break
   time.sleep(.02)
  self.assertEqual(job['status'],'completed',job);result=job['result']
  self.assertEqual(result.get('model'),'local-qwen');self.assertEqual(result['engine_version'],'tensorfold 0.0.1')
  self.assertEqual(result['parameters']['temperature'],0);self.assertEqual(result['parameters']['max_tokens'],1)
  self.assertEqual(result['engine_parameters']['temperature'],0.6);self.assertEqual(result['engine_parameters']['thinking_budget'],32)
  self.assertEqual(self.app.store.all('benchmark')[0]['model'],'local-qwen')

 def test_upstream_sse_error_is_counted_as_failure_even_with_done(self):
  model=self.app.store.root/'models/qwen';model.mkdir(parents=True)
  (model/'config.json').write_text(json.dumps({'_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(model/'model.safetensors').write_bytes(b'fixture')
  self.app.engine.start(str(model));wait_state(self.app.engine,'ready')
  self.request('/api/chat/completions','POST',{'messages':[{'role':'user','content':'error-event'}],'stream':True})
  stats=self.app.store.stats();self.assertEqual(stats['total']['errors'],1);self.assertEqual(stats['requests'][0]['status'],502)

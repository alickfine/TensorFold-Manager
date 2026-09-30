import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import Store,APIError
try:
 from tfmanager.resources import ResourceGate,MacObserver,parse_memory,parse_command,estimate_model
except ImportError:ResourceGate=None
GIB=1024**3
class Observer:
 def __init__(self):self.services=[];self.pressure='normal';self.available=200*GIB
 def capture(self):return {'at':1,'memory':{'physical_bytes':256*GIB,'available_bytes':self.available,'pressure':self.pressure,'swap_used_bytes':0,'missing':[]},'services':self.services,'missing':[]}
 def identity(self,pid):return next((s for s in self.services if s['pid']==pid),None)
class ResourceTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(ResourceGate,'resource gate missing');self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(Path(self.tmp.name)/'data');self.addCleanup(self.store.close);self.observer=Observer();self.gate=ResourceGate(self.store,observer=self.observer,lock_dir=Path(self.tmp.name)/'locks')
  self.model=self.store.root/'models/qwen';self.model.mkdir(parents=True);(self.model/'model.safetensors').write_bytes(b'x'*4096)
  self.config={'model_type':'qwen3_5','num_hidden_layers':4,'num_key_value_heads':2,'num_attention_heads':4,'hidden_size':128,'head_dim':32,'intermediate_size':256};(self.model/'config.json').write_text(json.dumps(self.config));self.settings=self.store.settings()|{'parallel':1,'context':1024}
 def test_unknown_budget_and_pressure_fail_closed(self):
  self.observer.pressure='critical'
  with self.assertRaises(APIError):self.gate.acquire_start(self.model,self.settings)
  self.observer.pressure='normal';(self.model/'config.json').write_text('{"model_type":"unknown"}')
  status=self.gate.preflight_start(self.model,self.settings);self.assertFalse(status['allowed']);self.assertTrue(status['missing'])
 def test_memory_estimate_scales_with_context_parallel_and_cache(self):
  a=estimate_model(self.model,self.settings);b=estimate_model(self.model,self.settings|{'context':2048,'parallel':2,'prompt_cache_gib':5})
  self.assertEqual(a['components']['kv_bytes'],4*2*32*2*2*1024)
  self.assertEqual(b['components']['kv_bytes'],4*a['components']['kv_bytes']);self.assertGreater(b['required_bytes'],a['required_bytes']);self.assertFalse(a['missing'])
 def test_active_external_service_blocks_new_load_and_quantization(self):
  self.observer.services=[{'pid':42,'uid':os.getuid(),'kind':'omlx','start_time':'today','listening_ports':[9000]}]
  with self.assertRaises(APIError):self.gate.acquire_start(self.model,self.settings)
  with self.assertRaises(APIError):self.gate.acquire_quantize(self.model,{'bits':4,'group_size':64})
 def test_cross_process_heavy_and_state_locks(self):
  lease=self.gate.acquire_start(self.model,self.settings)
  self.addCleanup(lease.release)
  code='import fcntl,os,sys;f=os.open(sys.argv[1],os.O_RDWR);\ntry:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:sys.exit(7)'
  result=subprocess.run([sys.executable,'-c',code,str(lease.path)],capture_output=True);self.assertEqual(result.returncode,7)
  with self.assertRaises(APIError):self.gate.acquire_quantize(self.model,{'bits':4,'group_size':64})
  lease.release()
  with self.gate.acquire_quantize(self.model,{'bits':4,'group_size':64}):pass
  state=self.gate.acquire_state();self.addCleanup(state.release)
  other=ResourceGate(self.store,observer=self.observer,lock_dir=Path(self.tmp.name)/'locks')
  with self.assertRaises(APIError):other.acquire_state()
 def test_attachment_requires_same_uid_path_flags_and_current_identity(self):
  flags={'host':'127.0.0.1','port':'9010','context':'1024','max-tokens':'4096','temperature':'0.6','top-p':'0.95','top-k':'20','parallel':'1','thinking':True,'prompt-cache-gib':'4.0','mlx-cache-gib':'8.0','snapshot-dir':str(self.store.snapshots),'name':'qwen'}
  service={'pid':42,'uid':os.getuid(),'kind':'tensorfold','start_time':'today','command_signature':'abc','model_path':str(self.model),'flags':flags,'identity_complete':True,'listening_ports':[9010],'health':{'status':'ok','warming':False},'model_ids':['qwen']}
  self.observer.services=[service]
  settings=self.settings|{'name':'qwen'}
  status=self.gate.preflight_start(self.model,settings);self.assertIsNotNone(status['attachment']);self.assertTrue(status['allowed'])
  flags['snapshot-dir']='/external/read-only-cache';self.assertTrue(self.gate.preflight_start(self.model,settings)['allowed'])
  flags['snapshot-dir']='relative/cache';self.assertFalse(self.gate.preflight_start(self.model,settings)['allowed']);flags['snapshot-dir']=str(self.store.snapshots)
  flags['context']='2048';self.assertIsNone(self.gate.preflight_start(self.model,settings)['attachment']);flags['context']='1024'
  lease=self.gate.acquire_start(self.model,settings);self.addCleanup(lease.release)
  self.assertTrue(self.gate.verify_attachment(service))
  self.observer.services[0]=service|{'health':None}
  self.assertTrue(self.gate.verify_attachment(service),'Transport health unavailable must not erase stable process identity')
  self.observer.services[0]=service|{'start_time':'later'};self.assertFalse(self.gate.verify_attachment(service))
 def test_memory_parser_uses_pressure_available_and_swap_not_rss(self):
  stats='Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 10.\nPages inactive: 20.\nPages speculative: 5.'
  memory=parse_memory(str(1024*1024),stats,'System-wide memory free percentage: 60%','1','vm.swapusage: total = 10.00M used = 2.00M free = 8.00M')
  self.assertEqual(memory['available_bytes'],35*16384);self.assertEqual(memory['pressure'],'normal');self.assertEqual(memory['swap_used_bytes'],2*1024**2)
 def test_command_parser_only_identifies_actual_tensorfold_module(self):
  command=parse_command('/venv/bin/python -m tensorfold serve '+str(self.model)+' --port 9000 --host 127.0.0.1')
  self.assertEqual(command['model_path'],str(self.model));self.assertEqual(command['kind'],'tensorfold')
  self.assertIsNone(parse_command('/usr/bin/python unrelated.py --label tensorfold'))
 def test_process_command_with_space_paths_remains_detected(self):
  exe='/Users/u/Library/Application Support/TensorFold Manager/runtime/bin/python3.12'
  row=parse_command(exe+' -B -m tensorfold serve /Users/u/My Models/qwen --port 9010', executable=exe)
  self.assertEqual(row['kind'],'tensorfold');self.assertFalse(row['identity_complete'])
 def test_bounded_argv_parser_never_reads_environment(self):
  from tfmanager.resources import parse_procargs
  import struct
  argv=['/App Dir/python','-m','tensorfold','serve','/Model Dir/qwen','--port','9010']
  raw=struct.pack('i',len(argv))+b'/App Dir/python\x00\x00'+b'\x00'.join(x.encode() for x in argv)+b'\x00SECRET=never_return\x00'
  self.assertEqual(parse_procargs(raw),argv)
 def test_observer_keeps_space_paths_and_redacts_unknown_flags(self):
  from unittest.mock import patch
  exe='/Users/u/Library/Application Support/TensorFold Manager/runtime/bin/python3'
  argv=[exe,'-B','-m','tensorfold','serve','/Users/u/My Models/qwen','--host','127.0.0.1','--port','9010']
  observer=MacObserver()
  def command(args,**kwargs):
   if 'uid=,lstart=,comm=' in args:return str(os.getuid())+' Tue Sep 29 10:00:00 2026 '+exe
   if 'command=' in args:return ' '.join(argv)
   return 'n127.0.0.1:9010\n'
  with patch.object(observer,'_run',side_effect=command),patch.object(observer,'_argv',return_value=argv),patch.object(observer,'_json',return_value={'status':'ok','data':[{'id':'qwen'}]}):
   row=observer.identity(42)
  self.assertEqual(row['model_path'],'/Users/u/My Models/qwen');self.assertTrue(row['identity_complete']);self.assertEqual(row['listening_ports'],[9010])
  parsed=parse_command('ignored',argv=argv+['--api-key','never-return'])
  self.assertFalse(parsed['identity_complete']);self.assertNotIn('never-return',json.dumps(parsed))
 def test_observer_uses_kernel_argv_for_unquoted_script_path(self):
  from unittest.mock import patch
  exe='/Users/u/Library/Application Support/TensorFold Manager/runtime/bin/python3'
  script='/Users/u/Library/Application Support/TensorFold Manager/runtime/bin/tensorfold'
  argv=[exe,script,'serve','/Users/u/My Models/qwen','--host','127.0.0.1','--port','9010']
  observer=MacObserver()
  def command(args,**kwargs):
   if 'uid=,lstart=,comm=' in args:return str(os.getuid())+' Tue Sep 29 10:00:00 2026 '+exe
   if 'command=' in args:return ' '.join(argv)
   return 'n127.0.0.1:9010\n'
  with patch.object(observer,'_run',side_effect=command),patch.object(observer,'_argv',return_value=argv),patch.object(observer,'_json',return_value={'status':'ok','data':[{'id':'qwen'}]}):
   row=observer.identity(42)
  self.assertIsNotNone(row)
  self.assertEqual(row['model_path'],'/Users/u/My Models/qwen')
  self.assertTrue(row['identity_complete'])
  with patch.object(observer,'_run',side_effect=command),patch.object(observer,'_argv',return_value=['/other/python',*argv[1:]]):
   self.assertIsNone(observer.identity(42))
  with patch.object(observer,'_run',side_effect=command),patch.object(observer,'_argv',side_effect=OSError('unavailable')):
   fallback=observer.identity(42)
  self.assertFalse(fallback and fallback['identity_complete'])
 def test_inherited_lease_blocks_until_holder_exits(self):
  lease=self.gate.acquire_start(self.model,self.settings)
  child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE,pass_fds=(lease.fd,))
  try:
   lease.release()
   with self.assertRaises(APIError):self.gate.acquire_quantize(self.model,{})
  finally:child.stdin.close();child.wait(timeout=3)
  with self.gate.acquire_quantize(self.model,{}):pass
 def test_glm_mla_and_kda_budget_uses_explicit_layout(self):
  text={'model_type':'glm5_next_text','num_hidden_layers':4,'hidden_size':4096,'intermediate_size':12288,'layer_types':['linear_attention']*3+['deepseek_sparse_attention'],'kv_lora_rank':512,'index_head_dim':128,'index_kpool':4,'linear_attn_config':{'num_heads':64,'head_dim':128,'short_conv_kernel_size':4},'num_nextn_predict_layers':1,'head_dim':0}
  (self.model/'config.json').write_text(json.dumps({'model_type':'glm5_next','text_config':text}))
  result=estimate_model(self.model,self.settings);self.assertFalse(result['missing']);self.assertGreater(result['components']['recurrent_state_bytes'],0)
  self.assertEqual(result['components']['kv_bytes'],2*(512+128*2+128/4)*2*1024)
 def test_nemotron_pattern_and_mamba_state_budget(self):
  text=self.config|{'model_type':'nemotron_h','hybrid_override_pattern':['M','*','E','M'],'mamba_num_heads':8,'mamba_head_dim':16,'ssm_state_size':32,'conv_kernel':4,'n_groups':2}
  (self.model/'config.json').write_text(json.dumps(text))
  result=estimate_model(self.model,self.settings);self.assertFalse(result['missing']);self.assertGreater(result['components']['recurrent_state_bytes'],0)
  del text['ssm_state_size'];(self.model/'config.json').write_text(json.dumps(text));self.assertIn('ssm_state_size',estimate_model(self.model,self.settings)['missing'])
 def test_gemma_mixed_head_layout_uses_conservative_global_bound(self):
  text=self.config|{'model_type':'gemma4_text','head_dim':256,'global_head_dim':512,'num_key_value_heads':8,'num_global_key_value_heads':2,'layer_types':['sliding_attention']*3+['full_attention'],'sliding_window':1024,'attention_k_eq_v':True}
  (self.model/'config.json').write_text(json.dumps(text))
  result=estimate_model(self.model,self.settings);self.assertFalse(result['missing']);self.assertEqual(result['components']['kv_bytes'],(2*512*1024+3*8*256*(1024+128))*4)
  self.assertGreaterEqual(result['components']['kv_allocation_headroom_bytes'],result['components']['kv_bytes'])
 def test_switch_capacity_is_physical_bound_and_missing_fails_closed(self):
  from unittest.mock import patch
  self.observer.available=1
  self.assertTrue(self.gate.preflight_capacity(self.model,self.settings)['allowed'])
  with patch.object(self.gate,'estimate',return_value={'required_bytes':250*GIB,'missing':[]}):
   self.assertFalse(self.gate.preflight_capacity(self.model,self.settings)['allowed'])
  with patch.object(self.observer,'capture',return_value={'memory':{'physical_bytes':None,'missing':['physical_memory']},'missing':[]}):
   self.assertFalse(self.gate.preflight_capacity(self.model,self.settings)['allowed'])

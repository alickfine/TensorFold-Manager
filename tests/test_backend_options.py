import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
import test_backend_engine as fixture_engine
from tfmanager.state import APIError
class AdvancedOptionsTests(unittest.TestCase):
 setUp=fixture_engine.EngineTests.setUp
 def test_options_persist_with_strict_types_and_exact_enum(self):
  config={'drafter':'none','drafter_bits':4,'mtp_drafts':3,'no_drafts':True,'checkpoint_slots':8,'spill_gib':2.5,'max_snapshots':5,'reasoning_effort':'xhigh','thinking_budget':128,'name':'qwen-local'}
  self.models.configure({'model':str(self.model),'config':config});self.assertEqual(self.store.get('model_config',str(self.model.resolve())),config)
  for invalid in ({'drafter_bits':True},{'mtp_drafts':'3'},{'no_drafts':'false'},{'reasoning_effort':'high'},{'name':'x;echo hi'},{'drafter':'$(touch x)'},{'checkpoint_slots':-1},{'mtp_confidence':float('nan')}):
   with self.assertRaises(APIError):self.models.configure({'model':str(self.model),'config':invalid})
 def test_verified_flags_are_applied_as_argv_and_missing_flags_rejected(self):
  config={'no_drafts':True,'drafter':'none','drafter_bits':4,'mtp_drafts':3,'checkpoint_slots':8,'spill_gib':2.5,'max_snapshots':5,'reasoning_effort':'xhigh','thinking_budget':128,'name':'qwen-local'}
  self.models.configure({'model':str(self.model),'config':config})
  argv,_=self.engine.build_command(self.models.resolve(str(self.model)),self.store.settings()|config)
  for flag,value in [('--drafter','none'),('--drafter-bits','4'),('--mtp-drafts','3'),('--checkpoint-slots','8'),('--spill-gib','2.5'),('--max-snapshots','5'),('--reasoning-effort','xhigh'),('--thinking-budget','128'),('--name','qwen-local')]:self.assertEqual(argv[argv.index(flag)+1],value)
  self.assertIn('--no-drafts',argv);self.assertEqual(argv.count('--name'),1)
  probe=self.engine.probe();probe['flags'].remove('--spill-gib')
  with patch.object(self.engine,'probe',return_value=probe):
   with self.assertRaisesRegex(APIError,'spill-gib'):self.engine.build_command(self.models.resolve(str(self.model)),self.store.settings()|config)
 def test_mlx_cuda_only_confidence_and_uninstalled_drafter_are_gated(self):
  self.assertIn('mtp_confidence',self.store.defaults())
  for config in ({'mtp_confidence':0.5},{'drafter':'owner/missing'}):
   with self.assertRaises(APIError):self.engine.build_command(self.models.resolve(str(self.model)),self.store.settings()|config)

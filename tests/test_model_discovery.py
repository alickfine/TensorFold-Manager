import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.models import Models
from tfmanager.state import Store
from tfmanager.jobs import Cancelled
try:
 from tfmanager.discovery import ModelDiscovery
except ImportError:ModelDiscovery=None
class ProbeJob:
 def __init__(self,cancel=False):self.cancel=cancel;self.progress_values=[]
 def checkpoint(self):
  if self.cancel:raise Cancelled()
 def progress(self,**values):self.progress_values.append(values)
class DiscoveryTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(ModelDiscovery,'disk model discovery not implemented')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.store=Store(self.root/'state');self.addCleanup(self.store.close)
  self.store.settings_update({'model_dirs':[str(self.root/'state/models')]})
  self.models=Models(self.store);self.disk=self.root/'disk';self.disk.mkdir()
 def make_model(self,where):
  where.mkdir(parents=True);(where/'config.json').write_text(json.dumps({'model_type':'qwen3_5','_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit'}));(where/'model.safetensors').write_bytes(b'fixture');return where.resolve()
 def test_discovers_nested_model_and_adds_exact_read_directory(self):
  model=self.make_model(self.disk/'nested'/'weights')
  result=ModelDiscovery(self.models,roots=[self.disk]).run(ProbeJob())
  self.assertIn(str(model),self.store.settings()['model_dirs'])
  self.assertIn(str(model),result['added_dirs']);self.assertFalse(result['partial'])
  self.assertEqual([r['path'] for r in result['models']],[str(model)])
 def test_cancel_does_not_mutate_directories(self):
  self.make_model(self.disk/'model');before=self.store.settings()['model_dirs']
  with self.assertRaises(Cancelled):ModelDiscovery(self.models,roots=[self.disk]).run(ProbeJob(True))
  self.assertEqual(self.store.settings()['model_dirs'],before)
 def test_never_follows_directory_links_or_scans_application_packages(self):
  outside=self.make_model(self.root/'outside');(self.disk/'link').symlink_to(outside,target_is_directory=True)
  self.make_model(self.disk/'Other.app'/'models')
  result=ModelDiscovery(self.models,roots=[self.disk]).run(ProbeJob())
  self.assertEqual(result['added_dirs'],[])
 def test_non_model_config_does_not_register_directory(self):
  p=self.disk/'private-config';p.mkdir();(p/'config.json').write_text('{"token":"test-only"}')
  result=ModelDiscovery(self.models,roots=[self.disk]).run(ProbeJob())
  self.assertEqual(result['models'],[]);self.assertEqual(result['added_dirs'],[])
 def test_network_mount_is_excluded_from_discovery(self):
  self.make_model(self.disk/'network'/'remote-model');local=self.make_model(self.disk/'local'/'model')
  result=ModelDiscovery(self.models,roots=[self.disk],excluded_mounts=[self.disk/'network']).run(ProbeJob())
  self.assertEqual(result['added_dirs'],[str(local)])
 def test_permission_denied_child_is_skipped_and_reported_partial(self):
  from unittest.mock import patch
  (self.disk/'protected').mkdir();local=self.make_model(self.disk/'readable/model')
  original=Path.is_symlink
  def inspect(path):
   if path.name=='protected':raise PermissionError('protected OS cache')
   return original(path)
  with patch.object(Path,'is_symlink',new=inspect):result=ModelDiscovery(self.models,roots=[self.disk]).run(ProbeJob())
  self.assertTrue(result['partial']);self.assertGreater(result['skipped'],0)
  self.assertIn(str(local),result['added_dirs'])
 def test_excluded_network_root_is_pruned_without_metadata_access(self):
  from unittest.mock import patch
  network=Path('/network-test')
  with patch.object(Path,'is_symlink',side_effect=AssertionError('excluded mount must not be queried')):
   result=ModelDiscovery(self.models,roots=[network],excluded_mounts=[network]).run(ProbeJob())
  self.assertFalse(result['partial']);self.assertEqual(result['skipped'],0)
 def test_scan_limit_is_explicitly_partial(self):
  self.make_model(self.disk/'nested'/'model')
  result=ModelDiscovery(self.models,roots=[self.disk],max_dirs=1).run(ProbeJob())
  self.assertTrue(result['partial']);self.assertIn('directory_limit',result['limits'])

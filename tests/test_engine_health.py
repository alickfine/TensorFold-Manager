import json
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
import test_backend_engine as fixtures
wait_state=fixtures.wait_state
class HealthTests(unittest.TestCase):
 setUp=fixtures.EngineTests.setUp
 def test_actual_health_memory_and_lanes_are_exposed(self):
  self.engine.start(str(self.model));state=wait_state(self.engine,'ready')
  self.assertEqual(state.get('health_detail',{}).get('memory',{}).get('active'),1048576)
  self.assertEqual(state['health_detail']['max_batch_size'],2)
  self.assertFalse(state['health_detail']['warming'])
  self.assertIsInstance(state['last_health_at'],float)
  with self.engine.request():self.assertEqual(self.engine.status()['active_requests'],1)
  self.assertEqual(self.engine.status()['active_requests'],0)
 def test_identity_mismatch_discards_memory_and_reports_probe_error(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  (self.model/'fixture-health-model').write_text('unexpected-model');self.engine._health_checked=0
  state=self.engine.status()
  from tfmanager.state import APIError
  with self.assertRaises(APIError):
   with self.engine.request():pass
  self.assertIsNone(state.get('health_detail'))
  self.assertIn('identity',state.get('health_error',''))
 def test_transient_health_timeout_blocks_requests_and_recovers_next_sample(self):
  from unittest.mock import Mock,patch
  from tfmanager.state import APIError
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  timeout=Mock();timeout.request.side_effect=TimeoutError('temporary health timeout')
  self.engine._health_checked=0
  with patch.object(self.engine,'connection',return_value=timeout):
   state=self.engine.status()
   self.assertEqual(state['state'],'ready')
   self.assertFalse(state['health'])
   self.assertIsNone(state['health_detail'])
   with self.assertRaises(APIError):
    with self.engine.request():pass
  self.engine._health_checked=0
  recovered=self.engine.status()
  self.assertEqual(recovered['state'],'ready')
  self.assertTrue(recovered['health'])
  self.assertIsNone(recovered['health_error'])
  with self.engine.request():pass
 def test_socket_ownership_probe_timeout_recovers_next_sample(self):
  import subprocess
  from unittest.mock import Mock,patch
  self.engine.start(str(self.model));wait_state(self.engine,'ready')
  slow=Mock();slow.request.side_effect=subprocess.TimeoutExpired('lsof',.5)
  self.engine._health_checked=0
  with patch.object(self.engine,'connection',return_value=slow):
   self.assertEqual(self.engine.status()['state'],'ready')
  self.engine._health_checked=0
  self.assertTrue(self.engine.status()['health'])
 def test_stopped_model_does_not_retain_live_memory_measurement(self):
  self.engine.start(str(self.model));wait_state(self.engine,'ready');self.engine.stop()
  state=self.engine.status();self.assertIsNone(state.get('health_detail'))
  self.assertEqual(state.get('active_requests'),0)
if __name__=='__main__':unittest.main()

import math,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import Store
from tfmanager.gateway import usage_into
class MetricsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name);self.addCleanup(self.store.close)
 def test_aggregates_use_observed_denominators_and_separate_cancellation(self):
  for row in [dict(model='a',status=200,elapsed=4,ttft=1,prefill_tps=100,decode_tps=10,cache_tokens=6),dict(model='a',status=499,elapsed=2),dict(model='b',status=500,elapsed=None,ttft=3,decode_tps=20,cache_tokens=0)]:self.store.record_request(row)
  stats=self.store.stats();total=stats['total']
  self.assertEqual(total.get('cancelled'),1);self.assertEqual(total['errors'],1);self.assertEqual(total['avg_elapsed'],3)
  self.assertEqual(total['avg_ttft'],2);self.assertEqual(total['avg_prefill_tps'],100);self.assertEqual(total['avg_decode_tps'],15);self.assertEqual(total['cache_tokens'],6)
  self.assertEqual(total['metric_samples']['ttft'],2)
  model_b=next(row for row in stats['models'] if row['model']=='b');self.assertIsNone(model_b['avg_prefill_tps']);self.assertIsNone(model_b['avg_elapsed'])
 def test_actual_upstream_runtime_and_usage_are_parsed_without_inventing_metrics(self):
  record={};usage_into(record,{'usage':{'prompt_tokens':100,'completion_tokens':12,'prompt_tokens_details':{'cached_tokens':20}},'tensorfold':{'tokens_per_second':30.5,'prefill_seconds':2,'time_to_first_token':2.1}})
  self.assertEqual(record.get('cache_tokens'),20);self.assertEqual(record['decode_tps'],30.5);self.assertEqual(record['prefill_tps'],40);self.assertEqual(record['ttft'],2.1)
  observed={'ttft':2.3};usage_into(observed,{'tensorfold':{'time_to_first_token':2.1}});self.assertEqual(observed['ttft'],2.3)
  missing={};usage_into(missing,{'usage':{'prompt_tokens':100},'tensorfold':{'prefill_seconds':2,'tokens_per_second':float('nan')}})
  self.assertNotIn('prefill_tps',missing);self.assertNotIn('decode_tps',missing)
 def test_legacy_rows_without_new_metrics_remain_readable(self):
  self.store.record_request({'model':None,'status':200,'elapsed':1})
  total=self.store.stats()['total'];self.assertIn('avg_ttft',total);self.assertIsNone(total['avg_ttft']);self.assertIsNone(total['cache_tokens'])

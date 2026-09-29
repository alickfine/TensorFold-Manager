import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'manager'))
from unittest.mock import patch
from tfmanager.state import Store, APIError
from tfmanager.accuracy import Accuracy

class FakeJobs:
    def register(self, kind, runner): self.runner = runner
    def create(self, kind, params): return {'kind': kind, 'params': params}

class FakeEngine:
    def request_metadata(self): return {'model': '/models/test', 'engine_version': 'fixture', 'engine_started_at': 123}

class FakeJob:
    id = 'fixture-job'
    cancelled = False
    def __init__(self, params): self.params = params
    def checkpoint(self): pass
    def progress(self, **values): pass

class AccuracyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.runner = Accuracy(self.store, FakeJobs(), FakeEngine())
    def tearDown(self): self.store.close(); self.tmp.cleanup()
    def test_no_reference_cannot_run(self):
        with self.assertRaises(APIError): self.runner.start({})
    def test_real_response_is_scored_against_explicit_reference(self):
        case = self.runner.add({'name':'known answer','prompt':'say yes','expected':'yes','match':'exact','max_tokens':8})
        task = self.runner.start({})
        with patch('tfmanager.accuracy.completion', return_value=({'choices':[{'message':{'content':'no'}}]}, {'status':200})) as call:
            result = self.runner.run(FakeJob(task['params']))
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['results'][0]['output'], 'no')
        self.assertEqual(result['results'][0]['case_id'], case['id'])
        self.assertEqual(call.call_args.kwargs['job'].id, 'fixture-job')
    def test_completed_rows_survive_later_error(self):
        self.runner.add({'name':'a','prompt':'one','expected':'yes','match':'contains'})
        self.runner.add({'name':'b','prompt':'two','expected':'yes','match':'contains'})
        task = self.runner.start({})
        with patch('tfmanager.accuracy.completion', side_effect=[({'choices':[{'message':{'content':'yes indeed'}}]}, {'status':200}), APIError('fixture failure')]):
            with self.assertRaises(APIError): self.runner.run(FakeJob(task['params']))
        result = self.runner.status()['results'][0]
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['status'], 'failed')
    def test_parameter_validation(self):
        for value in ({'prompt':'x','expected':''}, {'prompt':'x','expected':'y','match':'semantic'}, {'prompt':'x','expected':'y','max_tokens':True}):
            with self.assertRaises(APIError): self.runner.add(value)

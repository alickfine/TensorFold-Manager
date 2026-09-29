"""The production config-only CLI path rejects targets before heavy work."""
import json
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch
import test_tools as fixtures
from tfmanager.engine import Engine
from tfmanager.state import APIError


class TargetCompatibilityTests(unittest.TestCase):
    setUp = fixtures.ToolTests.setUp
    make_tools = fixtures.ToolTests.make_tools

    def cli_fixture(self):
        config=json.loads((self.model/'config.json').read_text())
        config.update(model_type='gemma4', enable_moe_block=True,
            _name_or_path='mlx-community/gemma-4-26b-a4b-it-4bit',
            quantization={'bits':4,'group_size':64,'mode':'affine'})
        (self.model/'config.json').write_text(json.dumps(config))
        capture=self.root/'info-calls.jsonl'
        script=self.root/'tensorfold-info.py'
        script.write_text('''import json,pathlib,sys
path=pathlib.Path(sys.argv[-1])
config=json.loads((path/'config.json').read_text())
q=config['quantization']
with pathlib.Path(CAPTURE).open('a') as stream:
 stream.write(json.dumps({'files':sorted(p.name for p in path.iterdir()),'path':str(path),'q':q})+'\\n')
if q['bits']!=4 or q['group_size'] not in (32,64):
 print("Gemma 4 kernels read MLX 4-bit weights in groups of 32 or 64",file=sys.stderr)
 sys.exit(1)
print('quantization MLX 4-bit; runs on Apple Silicon (MLX)')
'''.replace('CAPTURE',repr(str(capture))))
        self.engine.executable=lambda:[sys.executable,'-I','-B',str(script)]
        self.engine.store=self.store
        self.engine.inspect_model=Engine.inspect_model.__get__(self.engine)
        return capture,script

    def test_unsupported_target_is_rejected_before_job_lease_or_converter(self):
        capture,_=self.cli_fixture()
        tools=self.make_tools()
        before=self.models.fingerprint(self.model)
        with patch.object(tools,'_quantize_lease',side_effect=AssertionError('heavy lease must not be acquired')):
            with self.assertRaisesRegex(APIError,'4-bit'):
                tools.quantize({'model':str(self.model),'bits':3,'group_size':64,'mode':'affine'})
        self.assertFalse(self.jobs.list())
        self.assertFalse(self.capture.exists())
        self.assertEqual(before,self.models.fingerprint(self.model))
        calls=[json.loads(x) for x in capture.read_text().splitlines()]
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['files'],['config.json'])
        self.assertEqual(calls[0]['q'],{'bits':3,'group_size':64,'mode':'affine'})
        self.assertFalse(Path(calls[0]['path']).exists())

    def test_tools_status_exposes_only_actual_cli_accepted_pairs_and_caches_by_engine_config(self):
        capture,script=self.cli_fixture()
        tools=self.make_tools()
        capability=tools.status()['quantization']
        self.assertEqual(capability['scope'],'engine_config_preflight_only')
        model=next(row for row in capability['models'] if row['model']==str(self.model))
        self.assertEqual(model['choices'],[
            {'bits':4,'group_size':32,'mode':'affine'}, {'bits':4,'group_size':64,'mode':'affine'}])
        self.assertEqual(len(model['rejected']),13)
        self.assertTrue(all('4-bit' in row['reason'] for row in model['rejected']))
        count=len(capture.read_text().splitlines())
        self.assertEqual(count,15)
        tools.status()
        self.assertEqual(len(capture.read_text().splitlines()),count)
        config=json.loads((self.model/'config.json').read_text());config['hidden_size']=256
        (self.model/'config.json').write_text(json.dumps(config))
        tools.status()
        self.assertEqual(len(capture.read_text().splitlines()),count+15)
        script.write_text(script.read_text()+'\n# engine changed\n')
        tools.status()
        self.assertEqual(len(capture.read_text().splitlines()),count+30)
        calls=[json.loads(x) for x in capture.read_text().splitlines()]
        self.assertTrue(all(row['files']==['config.json'] and not Path(row['path']).exists() for row in calls))

    def test_queued_target_is_rechecked_against_current_engine_before_heavy_lease(self):
        capture,script=self.cli_fixture()
        tools=self.make_tools()
        with patch.object(self.jobs,'_start',return_value=None):
            row=tools.quantize({'model':str(self.model),'bits':4,'group_size':32,'mode':'affine'})
        script.write_text('import sys\nprint("fixture engine capability changed",file=sys.stderr)\nsys.exit(1)\n')
        with patch.object(tools,'_quantize_lease',side_effect=AssertionError('heavy lease must not be acquired')):
            self.jobs._start(self.jobs.get(row['id']))
            result=fixtures.wait_job(self.jobs,row['id'])
        self.assertEqual(result['status'],'failed',result)
        self.assertIn('capability changed',result['error'])
        self.assertFalse(self.capture.exists())

"""Real supervised converter fixture reproduces MLX's already-quantized skip."""
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_tools as fixtures
from tfmanager.state import APIError


class RequantizeTests(unittest.TestCase):
    setUp = fixtures.ToolTests.setUp
    make_tools = fixtures.ToolTests.make_tools

    def source_config(self, **extra):
        config = json.loads((self.model / 'config.json').read_text())
        config.update(quantization={'bits':4, 'group_size':64, 'mode':'affine',
            'model.layers.0.router.proj':{'bits':8, 'group_size':64}}, **extra)
        (self.model / 'config.json').write_text(json.dumps(config))

    def start(self, tools, name='requantized'):
        return tools.quantize({'model':str(self.model), 'name':name, 'bits':3, 'group_size':64, 'mode':'affine'})

    def assert_clean(self, tools, name='requantized'):
        self.assertFalse((tools.converted_root / name).exists())
        self.assertFalse(list(tools.converted_root.glob('.staging-*')))
        self.assertFalse(list(tools.converted_root.glob('.intermediate-*')))

    def test_quantized_source_runs_two_supervised_phases_with_one_lease_and_actual_metadata(self):
        self.source_config(protected_router=True)
        tools = self.make_tools()
        fingerprint = self.models.fingerprint(self.model)
        leases = []
        original = tools._run
        def run(*args, **kwargs):
            lease = kwargs['lease']
            leases.append((lease, os.fstat(lease.fd).st_ino))
            with self.assertRaises(APIError):
                tools.resources.acquire_quantize(str(self.model), {})
            return original(*args, **kwargs)
        with patch.object(tools, '_run', side_effect=run):
            row = fixtures.wait_job(self.jobs, self.start(tools)['id'])
        self.assertEqual(row['status'], 'completed', row)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertEqual([x['phase'] for x in calls], ['dequantize','quantize'])
        self.assertEqual(len(leases), 2)
        self.assertIs(leases[0][0], leases[1][0])
        self.assertEqual(leases[0][1], leases[1][1])
        first, second = (x['args'] for x in calls)
        self.assertNotIn('--quantize', first)
        self.assertNotIn('--dequantize', second)
        intermediate = Path(first[first.index('--mlx-path')+1])
        self.assertEqual(second[second.index('--hf-path')+1], str(intermediate))
        self.assertFalse(intermediate.exists())
        output = Path(row['result']['path'])
        config = json.loads((output/'config.json').read_text())
        self.assertEqual(config['quantization']['bits'], 3)
        manifest = json.loads((output/'.tfmanager-manifest.json').read_text())
        expected = {'bits':3,'group_size':64,'mode':'affine','overrides':{
            'model.layers.0.router.proj':{'bits':8,'group_size':64,'mode':'affine'}},'mixed':True}
        self.assertEqual(manifest['effective_quantization'], expected)
        self.assertEqual(row['result']['effective_quantization'], expected)
        self.assertEqual(manifest['requested_quantization'], {'bits':3,'group_size':64,'mode':'affine'})
        self.assertEqual(self.models.fingerprint(self.model), fingerprint)

    def test_wrong_global_and_malformed_override_cannot_publish(self):
        bad = [
            {'bits':4,'group_size':64,'mode':'affine','model.layers.0.router.proj':{'bits':8,'group_size':64}},
            {'bits':3,'group_size':128,'mode':'affine'},
            {'bits':3,'group_size':64,'mode':'mxfp4'},
            {'bits':3,'group_size':64,'mode':'affine','model.layer':{'bits':True,'group_size':64}},
            {'bits':3,'group_size':64,'mode':'affine','model.layer':{'bits':8,'group_size':0}},
            {'bits':3,'group_size':64,'mode':'affine','model.layer':{'bits':8,'group_size':64,'mode':'unknown'}},
        ]
        tools = self.make_tools()
        for number, quantization in enumerate(bad):
            with self.subTest(quantization=quantization):
                self.source_config(output_quantization=quantization)
                name = 'bad-'+str(number)
                result = fixtures.wait_job(self.jobs, self.start(tools, name)['id'])
                self.assertEqual(result['status'],'failed',result)
                self.assertIn('quantization',result['error'].lower())
                self.assert_clean(tools,name)
        self.assertFalse(self.engine.inspected)

    def test_source_mutation_during_processing_prevents_publish(self):
        self.source_config(mutate_source=str(self.model/'model.safetensors'))
        tools = self.make_tools()
        row = fixtures.wait_job(self.jobs,self.start(tools)['id'])
        self.assertEqual(row['status'],'failed',row)
        self.assertIn('source changed',row['error'].lower())
        self.assert_clean(tools)

    def test_cancel_each_phase_keeps_lease_until_child_exit_and_cleans_owned_files(self):
        tools = self.make_tools()
        for phase in ('dequantize','quantize'):
            self.source_config(slow_phase=phase)
            self.capture.unlink(missing_ok=True)
            fingerprint = self.models.fingerprint(self.model)
            row = self.start(tools, 'cancel-'+phase)
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                try:
                    capture=json.loads(self.capture.read_text())
                    if capture.get('phase')==phase: break
                except (FileNotFoundError, ValueError): pass
                time.sleep(.02)
            else: self.fail('phase never started: '+phase)
            with self.assertRaises(APIError):tools.resources.acquire_quantize(str(self.model),{})
            self.jobs.action(row['id'],'cancel')
            result=fixtures.wait_job(self.jobs,row['id'])
            self.assertEqual(result['status'],'cancelled',result)
            with self.assertRaises(ProcessLookupError):os.kill(capture['pid'],0)
            with tools.resources.acquire_quantize(str(self.model),{}):pass
            self.assert_clean(tools,'cancel-'+phase)
            self.assertEqual(self.models.fingerprint(self.model),fingerprint)

    def test_dequantization_failure_and_residual_quantization_are_not_published(self):
        tools = self.make_tools()
        for number, extra in enumerate(({'fail_phase':'dequantize'},{'bad_dequantize':True},{'fail_phase':'quantize'})):
            config=json.loads((self.model/'config.json').read_text())
            for key in ('fail_phase','bad_dequantize'):config.pop(key,None)
            (self.model/'config.json').write_text(json.dumps(config))
            self.source_config(**extra)
            name='failure-'+str(number)
            row=fixtures.wait_job(self.jobs,self.start(tools,name)['id'])
            self.assertEqual(row['status'],'failed',row)
            self.assert_clean(tools,name)

    def test_disk_space_is_checked_at_creation_and_again_before_child(self):
        tools=self.make_tools()
        self.source_config()
        with patch('tfmanager.tools.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(APIError,'disk'):self.start(tools)
        with patch.object(self.jobs,'_start',return_value=None):row=self.start(tools)
        with patch('tfmanager.tools.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            self.jobs._start(self.jobs.get(row['id']))
            result=fixtures.wait_job(self.jobs,row['id'])
        self.assertEqual(result['status'],'failed',result)
        self.assertIn('disk',result['error'].lower())
        self.assertFalse(self.capture.exists())
        self.assert_clean(tools)

    def test_disk_space_is_rechecked_between_supervised_phases(self):
        self.source_config()
        tools=self.make_tools()
        with patch('tfmanager.tools.shutil.disk_usage',side_effect=[SimpleNamespace(free=1024**4),
                SimpleNamespace(free=1024**4),SimpleNamespace(free=0)]):
            row=fixtures.wait_job(self.jobs,self.start(tools)['id'])
        self.assertEqual(row['status'],'failed',row)
        self.assertIn('disk',row['error'].lower())
        self.assertEqual([json.loads(line)['phase'] for line in self.trace.read_text().splitlines()],['dequantize'])
        self.assert_clean(tools)

    def test_source_is_rechecked_after_lease_acquisition_and_after_cli_validation(self):
        self.source_config()
        tools=self.make_tools()
        acquire=tools._quantize_lease
        def changed_acquire(*args,**kwargs):
            lease=acquire(*args,**kwargs)
            (self.model/'model.safetensors').write_bytes(b'changed while obtaining lease')
            return lease
        with patch.object(tools,'_quantize_lease',side_effect=changed_acquire):
            row=fixtures.wait_job(self.jobs,self.start(tools)['id'])
        self.assertEqual(row['status'],'failed',row)
        self.assertFalse(self.capture.exists())
        self.assert_clean(tools)
        with tools.resources.acquire_quantize(str(self.model),{}):pass
        inspect=self.engine.inspect_model
        def changed_inspect(*args):
            result=inspect(*args)
            (self.model/'model.safetensors').write_bytes(b'changed during CLI validation')
            return result
        with patch.object(self.engine,'inspect_model',side_effect=changed_inspect):
            row=fixtures.wait_job(self.jobs,self.start(tools)['id'])
        self.assertEqual(row['status'],'failed',row)
        self.assertIn('source changed',row['error'].lower())
        self.assert_clean(tools)

    def test_conflicting_quantization_alias_is_rejected(self):
        self.source_config()
        tools=self.make_tools()
        original=tools._run
        def inconsistent(*args,**kwargs):
            result=original(*args,**kwargs)
            argv=[str(item) for item in args[0]]
            if '--quantize' in argv:
                config_path=Path(argv[argv.index('--mlx-path')+1])/'config.json'
                config=json.loads(config_path.read_text())
                config['quantization_config']['bits']=4
                config_path.write_text(json.dumps(config))
            return result
        with patch.object(tools,'_run',side_effect=inconsistent):
            row=fixtures.wait_job(self.jobs,self.start(tools)['id'])
        self.assertEqual(row['status'],'failed',row)
        self.assertIn('quantization',row['error'].lower())
        self.assert_clean(tools)

import importlib.util
import pathlib
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class BundleSafetyTests(unittest.TestCase):
    def builder(self):
        spec = importlib.util.spec_from_file_location('build_app', ROOT / 'scripts/build-app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_release_version_rejects_paths_and_honors_tag(self):
        build = self.builder()
        self.assertEqual(build.get_version('v0.2.0-beta.3'), '0.2.0-beta.3')
        for value in ('../release', '0.1.0/../../file', '$(whoami)'):
            with self.assertRaises(ValueError):
                build.get_version(value)

    def test_missing_runtime_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(ValueError):
                self.builder().validate_runtime(pathlib.Path(name))

    def test_external_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            (root / 'bin').mkdir()
            (root / 'bin/python3').symlink_to('/usr/bin/python3')
            with self.assertRaises(ValueError):
                self.builder().validate_runtime(root)

    def test_resource_copy_omits_local_databases_credentials(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            source, dest = root / 'source', root / 'dest'
            source.mkdir()
            for filename in ('__init__.py', '.env', 'session.sqlite', 'data.log', 'model.safetensors'):
                (source / filename).write_text('not a real credential')
            self.builder().copy_source(source, dest)
            self.assertEqual([p.name for p in dest.iterdir()], ['__init__.py'])

if __name__ == '__main__': unittest.main()

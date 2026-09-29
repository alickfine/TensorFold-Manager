import importlib.util
import pathlib
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class BundleSafetyTests(unittest.TestCase):
    def test_runtime_manifest_tracks_library_changes_and_links(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            (root / 'library.py').write_text('first')
            (root / 'alias').symlink_to('library.py')
            build = self.builder()
            before = build.runtime_manifest(root)
            (root / 'library.py').write_text('patched')
            self.assertNotEqual(before, build.runtime_manifest(root))
            self.assertEqual(before['alias']['link'], 'library.py')

    def builder(self):
        spec = importlib.util.spec_from_file_location('build_app', ROOT / 'scripts/build-app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_sealed_runtime_namespace_preserves_legacy_prefix_and_is_deterministic(self):
        import hashlib
        build=self.builder();manifest=b'{}'
        new=build.runtime_fingerprint(manifest,'-')
        self.assertEqual(new,build.runtime_fingerprint(manifest,'-'))
        self.assertNotEqual(new,hashlib.sha256(manifest+b'-').hexdigest())
        self.assertNotEqual(new,build.runtime_fingerprint(b'{"changed":1}','-'))

    def test_release_version_rejects_paths_and_honors_tag(self):
        build = self.builder()
        self.assertEqual(build.get_version('v0.2.0-beta.3'), '0.2.0-beta.3')
        for value in ('../release', '0.1.0/../../file', '$(whoami)'):
            with self.assertRaises(ValueError):
                build.get_version(value)

    def test_runtime_bin_has_only_interpreter_aliases(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            binary = root / 'bin'
            binary.mkdir()
            for filename in ('python3.12', 'idle3.12', 'pip', 'python3.12-config'):
                (binary / filename).write_text('fixture')
            (binary / 'python3').symlink_to('python3.12')
            self.builder().trim_runtime_tools(root)
            self.assertEqual(sorted(p.name for p in binary.iterdir()), ['python3', 'python3.12'])
            self.assertTrue((binary / 'python3').resolve().is_file())

    def test_python_framework_is_a_signable_versioned_bundle(self):
        import plistlib
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            runtime = root / 'vendor'
            (runtime / 'bin').mkdir(parents=True)
            (runtime / 'lib').mkdir()
            (runtime / 'bin/python3.12').write_bytes(b'fixture interpreter')
            (runtime / 'bin/python3').symlink_to('python3.12')
            (runtime / 'lib/libpython3.12.dylib').write_bytes(b'fixture library')
            framework = self.builder().copy_runtime_framework(runtime, root / 'Frameworks')
            self.assertEqual(framework.name, 'PythonRuntime.framework')
            self.assertEqual((framework / 'Versions/Current').readlink(), pathlib.Path('A'))
            info = plistlib.loads((framework / 'Resources/Info.plist').read_bytes())
            self.assertEqual(info['CFBundlePackageType'], 'FMWK')
            self.assertEqual((framework / 'PythonRuntime').read_bytes(), b'fixture library')
            self.assertTrue((framework / 'Resources/runtime/bin/python3').resolve().is_file())

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

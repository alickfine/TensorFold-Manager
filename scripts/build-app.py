#!/usr/bin/env python3
"""Build a relocatable arm64 test App and DMG using Apple tools.

Pass a uv-managed python-build-standalone install, never a system framework.
Developer ID builds require SIGNING_IDENTITY; ad hoc is explicitly labelled.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import plistlib
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0-alpha.2'
ALLOWED = {'.py', '.js', '.mjs', '.css', '.html', '.json', '.toml', '.md'}


def get_version(value: str = VERSION) -> str:
    value = value.removeprefix('v')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?', value):
        raise ValueError('Invalid release version')
    return value


def validate_runtime(runtime: Path) -> Path:
    runtime = runtime.resolve()
    python = runtime / 'bin/python3'
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('Runtime must contain executable bin/python3')
    for path in runtime.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(runtime):
            raise ValueError('Runtime contains an external symlink: ' + str(path.relative_to(runtime)))
    if not python.resolve().is_relative_to(runtime):
        raise ValueError('Runtime python resolves outside the bundled runtime')
    result = subprocess.check_output([str(python), '-I', '-c', 'import sys; print(sys.version_info[:3])'], text=True).strip()
    if result != '(3, 12, 9)':
        raise ValueError('Expected standalone Python 3.12.9')
    return runtime


def trim_runtime_tools(runtime: Path) -> None:
    # Only the bundled interpreter is a supported launcher. Optional IDE/pip
    # shell entrypoints are not runtime dependencies and cannot remain unsigned
    # executable nested components in a signed Frameworks directory.
    for path in (runtime / 'bin').iterdir():
        if path.name not in {'python', 'python3', 'python3.12'}:
            if path.is_dir() and not path.is_symlink():
                raise ValueError('Unexpected runtime bin directory')
            path.unlink()


def copy_runtime_framework(runtime: Path, frameworks: Path) -> Path:
    framework = frameworks / 'PythonRuntime.framework'
    version = framework / 'Versions/A'
    resources = version / 'Resources'
    resources.mkdir(parents=True, exist_ok=True)
    standalone = resources / 'runtime'
    shutil.copytree(runtime, standalone, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    trim_runtime_tools(standalone)
    (resources / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'io.github.alickfine.tensorfold-manager.python',
        'CFBundleName': 'PythonRuntime', 'CFBundleExecutable': 'PythonRuntime',
        'CFBundlePackageType': 'FMWK', 'CFBundleVersion': '3.12.9',
    }))
    shutil.copy2(standalone / 'lib/libpython3.12.dylib', version / 'PythonRuntime')
    (framework / 'Versions/Current').symlink_to('A')
    (framework / 'Resources').symlink_to('Versions/Current/Resources')
    (framework / 'PythonRuntime').symlink_to('Versions/Current/PythonRuntime')
    return framework


def copy_source(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.name.startswith('.') or path.name == '__pycache__' or path.is_symlink():
            continue
        if path.is_dir():
            copy_source(path, target / path.name)
        elif path.suffix in ALLOWED and path.name not in {'credentials.json', 'settings.json', 'state.json'}:
            shutil.copy2(path, target / path.name)


def sha(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def runtime_manifest(runtime: Path) -> dict:
    result = {}
    for path in sorted(runtime.rglob('*')):
        name = path.relative_to(runtime).as_posix()
        if path.is_symlink():
            result[name] = {'link': os.readlink(path)}
        elif path.is_file():
            result[name] = {'sha256': sha(path), 'mode': path.stat().st_mode & 0o777}
    return result


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    with path.open('rb') as source:
        return source.read(4) in {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf'}


def build(runtime: Path, uv: Path, output: Path, dmg: bool = True, version: str = VERSION) -> Path:
    version = get_version(version)
    runtime = validate_runtime(runtime)
    if not uv.is_file(): raise ValueError('uv executable required')
    if subprocess.check_output([str(uv.resolve()), '--version'], text=True).split()[1] != '0.9.5':
        raise ValueError('Expected pinned uv 0.9.5')
    output.mkdir(parents=True, exist_ok=True)
    app = output / 'TensorFold Manager.app'
    if app.exists():
        raise ValueError('Output already exists; choose a fresh build directory')
    contents = app / 'Contents'
    resources = contents / 'Resources'
    frameworks = contents / 'Frameworks'
    helpers = contents / 'Helpers'
    (contents / 'MacOS').mkdir(parents=True)
    resources.mkdir()
    helpers.mkdir()
    frameworks.mkdir()
    python_framework = copy_runtime_framework(runtime, frameworks)
    shutil.copy2(uv, helpers / 'uv')
    shutil.copytree(ROOT / 'macos/licenses', resources / 'licenses')
    copy_source(ROOT / 'manager', resources / 'manager')
    copy_source(ROOT / 'web', resources / 'web')
    shutil.copy2(ROOT / 'scripts/sidecar-launch.py', resources / 'sidecar-launch.py')
    signing = os.environ.get('SIGNING_IDENTITY', '-')
    info = plistlib.loads((ROOT / 'macos/Info.plist').read_bytes())
    info['CFBundleShortVersionString'] = version
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    provenance = {
        'app_version': version, 'python_version': '3.12.9', 'uv_version': '0.9.5',
        'python_source': 'https://github.com/astral-sh/python-build-standalone',
        'uv_source': 'https://github.com/astral-sh/uv/releases/tag/0.9.5',
        'uv_source_archive_sha256': 'dc098ff224d78ed418e121fd374f655949d2c7031a70f6f6604eaf016a130433',
        'python_binary_sha256': sha(runtime / 'bin/python3'),
        'python_library_sha256': sha(runtime / 'lib/libpython3.12.dylib'),
        'uv_sha256': sha(uv),
        'signing': 'ad hoc / not notarized' if signing == '-' else 'Developer ID / notarization separate',
        'build_macos': platform.mac_ver()[0], 'deployment_target': '14.0',
    }
    (resources / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    run('/usr/bin/swiftc', '-swift-version', '5', '-target', 'arm64-apple-macosx14.0',
        '-O', '-framework', 'Cocoa', '-framework', 'WebKit', '-framework', 'Security',
        str(ROOT / 'macos/Bootstrap.swift'), str(ROOT / 'macos/main.swift'), '-o', str(contents / 'MacOS/TensorFoldManager'))
    run('/usr/bin/swiftc', '-swift-version', '5', '-target', 'arm64-apple-macosx14.0',
        '-O', '-framework', 'Security', str(ROOT / 'macos/CredentialRequest.swift'),
        str(ROOT / 'macos/CredentialHelper/main.swift'), '-o', str(helpers / 'CredentialStore'))
    for path in sorted(contents.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if macho(path) and path not in {contents / 'MacOS/TensorFoldManager', python_framework / 'Versions/A/PythonRuntime'}:
            args = ['/usr/bin/codesign', '--force', '--sign', signing]
            if signing != '-':
                args += ['--options', 'runtime', '--timestamp']
                if path.name.startswith('python3'):
                    args += ['--entitlements', str(ROOT / 'macos/python.entitlements')]
            run(*args, str(path))
    manifest = runtime_manifest(python_framework / 'Resources/runtime')
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    (resources / 'runtime-manifest.json').write_bytes(manifest_bytes)
    provenance['runtime_fingerprint'] = hashlib.sha256(manifest_bytes + signing.encode()).hexdigest()
    (resources / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    signing_options = ['--options', 'runtime', '--timestamp'] if signing != '-' else []
    run('/usr/bin/codesign', '--force', '--sign', signing, *signing_options, str(python_framework))
    run('/usr/bin/codesign', '--force', '--sign', signing, *signing_options, str(app))
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    if dmg:
        stage = output / 'dmg-content'
        stage.mkdir()
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / 'Applications').symlink_to('/Applications')
        (stage / 'README.txt').write_text('TensorFold Manager ' + version + '\n\nDrag the App to Applications.\n\n'
            + provenance['signing'] + '\nFirst engine installation requires internet access. Models are separate.\n')
        installer = output / f'TensorFold-Manager-{version}-macOS-arm64.dmg'
        run('/usr/bin/hdiutil', 'create', '-volname', 'TensorFold Manager', '-srcfolder', str(stage),
            '-ov', '-format', 'UDZO', str(installer))
        run('/usr/bin/codesign', '--force', '--sign', signing, str(installer))
        (output / 'SHA256SUMS.txt').write_text(f'{sha(installer)}  {installer.name}\n')
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / VERSION)
    parser.add_argument('--no-dmg', action='store_true')
    parser.add_argument('--version', default=os.environ.get('TFM_BUILD_VERSION', VERSION))
    args = parser.parse_args()
    print(build(args.runtime, args.uv, args.output, not args.no_dmg, args.version))

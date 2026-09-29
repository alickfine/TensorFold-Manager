import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manager"))

from tfmanager.jobs import Jobs
from tfmanager.models import Models
from tfmanager.state import APIError, Store


def wait_job(jobs, job_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = jobs.get(job_id)
        if row["status"] in ("completed", "failed", "cancelled"):
            return row
        time.sleep(0.02)
    raise AssertionError(jobs.get(job_id))


class FakeCredentials:
    def __init__(self, secret="upload-secret-value"):
        self.secret = secret

    def status(self, provider):
        return {"provider": provider, "configured": provider == "hf-upload"}

    def get(self, provider):
        if provider != "hf-upload":
            raise APIError("Credential is not configured")
        return self.secret


class FakeEngine:
    def __init__(self):
        self.lifecycle = threading.RLock()
        self.state = "stopped"
        self.inspected = []

    def status(self):
        return {"state": self.state}

    def executable(self):
        return [sys.executable, "engine-fixture.py"]

    def inspect_model(self, command, path):
        self.inspected.append((command, path))
        return "compatible"


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "data")
        self.addCleanup(self.store.close)
        self.jobs = Jobs(self.store)
        self.addCleanup(self.jobs.shutdown)
        self.models = Models(self.store)
        self.engine = FakeEngine()
        self.model = self.store.root / "models" / "source-model"
        self.model.mkdir(parents=True)
        (self.model / "config.json").write_text(
            json.dumps({"model_type": "qwen3_5", "_name_or_path": "Vontra/Qwen3.8-27B-MLX-4bit"})
        )
        (self.model / "model.safetensors").write_bytes(b"source weights")
        self.capture = self.root / "child-capture.json"
        self.trace = self.root / "conversion-trace.jsonl"
        self.tool_python = self.store.root / "tools" / "testing" / "bin" / "python"
        self.tool_python.parent.mkdir(parents=True)
        self.tool_python.write_text(
            "#!" + sys.executable + "\n"
            "import json,os,pathlib,shutil,sys,time\n"
            f"capture=pathlib.Path({str(self.capture)!r})\n"
            "args=sys.argv[1:]\n"
            "if '-m' in args and args[args.index('-m')+1]=='mlx_lm':\n"
            " source=pathlib.Path(args[args.index('--hf-path')+1]); output=pathlib.Path(args[args.index('--mlx-path')+1])\n"
            " config=json.loads((source/'config.json').read_text()); phase='dequantize' if '--dequantize' in args else 'quantize'\n"
            f" with pathlib.Path({str(self.trace)!r}).open('a') as trace: trace.write(json.dumps({{'args':args,'phase':phase,'pid':os.getpid()}})+'\\n')\n"
            " output.mkdir(); (output/'model.safetensors').write_bytes(b'partial')\n"
            " capture.write_text(json.dumps({'started':True,'pid':os.getpid(),'phase':phase}))\n"
            " if config.get('slow') or config.get('slow_phase')==phase: time.sleep(30)\n"
            " if config.get('fail_phase')==phase: raise SystemExit(9)\n"
            " if phase=='dequantize':\n"
            "  if not config.get('bad_dequantize'): config.pop('quantization',None); config.pop('quantization_config',None)\n"
            " else:\n"
            "  if 'quantization' not in config: config['quantization']={'bits':int(args[args.index('--q-bits')+1]),'group_size':int(args[args.index('--q-group-size')+1]),'mode':args[args.index('--q-mode')+1]}\n"
            "  if 'output_quantization' in config: config['quantization']=config['output_quantization']\n"
            "  if config.get('protected_router'): config['quantization']['model.layers.0.router.proj']={'bits':8,'group_size':64}\n"
            "  config['quantization_config']=config['quantization']\n"
            "  if config.get('mutate_source'): pathlib.Path(config['mutate_source']).write_bytes(b'changed during conversion')\n"
            " (output/'config.json').write_text(json.dumps(config)); (output/'model.safetensors').write_bytes(b'converted')\n"
            " capture.write_text(json.dumps({'args':args,'token':os.environ.get('TFM_HF_UPLOAD_TOKEN')}))\n"
            "elif '-c' in args:\n"
            " manifest=json.loads(pathlib.Path(args[-1]).read_text())\n"
            " capture.write_text(json.dumps({'args':args[:3]+['<script>']+args[-1:],'token_present':bool(os.environ.get('TFM_HF_UPLOAD_TOKEN')),'home':os.environ.get('HOME'),'hf_home':os.environ.get('HF_HOME'),'implicit':os.environ.get('HF_HUB_DISABLE_IMPLICIT_TOKEN'),'manifest':manifest}))\n"
            "else: raise SystemExit(7)\n"
        )
        self.tool_python.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self.store.put(
            "tools_active",
            {"python": str(self.tool_python), "packages": {"mlx-lm": "0.31.3", "huggingface-hub": "1.33.0"}},
        )

    def make_tools(self, resources=None):
        from tfmanager.tools import Tools

        from fixtures.resources import FixtureGate
        return Tools(self.store, self.jobs, self.engine, self.models, FakeCredentials(), resources=resources or FixtureGate(self.store))

    def test_quantize_validates_options_and_all_heavy_service_gates(self):
        tools = self.make_tools()
        for data in (
            {"model": str(self.model), "bits": 5, "group_size": 64, "mode": "affine"},
            {"model": str(self.model), "bits": 4, "group_size": 48, "mode": "affine"},
            {"model": str(self.model), "bits": 4, "group_size": 64, "mode": "mxfp4"},
        ):
            with self.assertRaises(APIError):
                tools.quantize(data)
        self.engine.state = "ready"
        with self.assertRaisesRegex(APIError, "running"):
            tools.quantize({"model": str(self.model), "bits": 4, "group_size": 64, "mode": "affine"})
        self.engine.state = "stopped"
        with patch.object(tools, "_external_service_running", return_value=True):
            with self.assertRaisesRegex(APIError, "external"):
                tools.quantize({"model": str(self.model), "bits": 4, "group_size": 64, "mode": "affine"})

    def test_quantize_uses_isolated_cli_validates_weights_and_publishes_new_owned_output(self):
        tools = self.make_tools()
        with patch.object(tools, "_external_service_running", return_value=False):
            row = tools.quantize(
                {"model": str(self.model), "name": "source-model-q4", "bits": 4, "group_size": 64, "mode": "affine"}
            )
            result = wait_job(self.jobs, row["id"])
        self.assertEqual(result["status"], "completed", result)
        output = Path(result["result"]["path"])
        self.assertTrue(output.is_relative_to(self.store.root / "converted"))
        self.assertEqual((output / "model.safetensors").read_bytes(), b"converted")
        manifest = json.loads((output / ".tfmanager-manifest.json").read_text())
        self.assertEqual(manifest["owner"], "tfmanager")
        self.assertEqual(manifest["quantization"], {"bits": 4, "group_size": 64, "mode": "affine"})
        child = json.loads(self.capture.read_text())
        self.assertEqual(child["args"][:4], ["-I", "-B", "-m", "mlx_lm"])
        self.assertNotIn("--trust-remote-code", child["args"])
        self.assertEqual(Path(self.engine.inspected[-1][1]), output.parent / (".staging-" + row["id"]))
        self.assertIn(str(self.store.root / "converted"), self.store.settings()["model_dirs"])
        with patch.object(tools, "_external_service_running", return_value=False):
            with self.assertRaisesRegex(APIError, "already exists"):
                tools.quantize(
                    {"model": str(self.model), "name": "source-model-q4", "bits": 4, "group_size": 64, "mode": "affine"}
                )

    def test_quantize_cancel_waits_for_owned_child_and_releases_os_lease(self):
        tools=self.make_tools()
        (self.model/'config.json').write_text(json.dumps({'model_type':'qwen3_5','_name_or_path':'Vontra/Qwen3.8-27B-MLX-4bit','slow':True}))
        row=tools.quantize({'model':str(self.model),'name':'cancelled-q4','bits':4,'group_size':64,'mode':'affine'})
        deadline=time.monotonic()+3
        while not self.capture.exists() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(self.capture.exists(),'controlled conversion did not start')
        child=json.loads(self.capture.read_text())['pid']
        with self.assertRaises(APIError):tools.resources.acquire_quantize(str(self.model),{})
        self.jobs.action(row['id'],'cancel');result=wait_job(self.jobs,row['id'])
        self.assertEqual(result['status'],'cancelled',result)
        with self.assertRaises(ProcessLookupError):os.kill(child,0)
        with tools.resources.acquire_quantize(str(self.model),{}):pass
        self.assertFalse((self.store.root/'converted'/'cancelled-q4').exists())

    def test_quantize_rejects_source_changed_after_job_creation(self):
        tools = self.make_tools()
        with patch.object(self.jobs,'_start',return_value=None):
            row=tools.quantize({"model":str(self.model),"name":"changed-q4","bits":4,"group_size":64,"mode":"affine"})
        (self.model / "model.safetensors").write_bytes(b"changed weights")
        self.jobs._start(self.jobs.get(row['id']))
        result = wait_job(self.jobs, row["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("source changed", result["error"].lower())
        self.assertFalse((self.store.root / "converted" / "changed-q4").exists())

    def test_tool_install_uses_exact_pins_and_records_complete_freeze(self):
        tools = self.make_tools()
        uv_capture = self.root / "uv-capture.jsonl"
        fake_uv = self.root / "uv"
        fake_uv.write_text(
            "#!" + sys.executable + "\n"
            "import json,pathlib,stat,sys\n"
            f"capture=pathlib.Path({str(uv_capture)!r}); capture.open('a').write(json.dumps(sys.argv[1:])+'\\n')\n"
            "if sys.argv[1]=='venv':\n"
            " slot=pathlib.Path(sys.argv[-1]); (slot/'bin').mkdir(parents=True); python=slot/'bin/python'; python.write_text('#!/bin/sh\\nexit 0\\n'); python.chmod(0o700)\n"
            "elif sys.argv[1:3]==['pip','freeze']: print('huggingface-hub==1.33.0\\nmlx-lm==0.31.3\\nsafetensors==0.6.2')\n"
        )
        fake_uv.chmod(0o700)
        with patch.dict(os.environ, {"TFM_UV": str(fake_uv), "TFM_RUNTIME_PYTHON": sys.executable}):
            result = wait_job(self.jobs, tools.install({})["id"])
        self.assertEqual(result["status"], "completed", result)
        active = self.store.get("tools_active")
        self.assertEqual(active["packages"], {"mlx-lm": "0.31.3", "huggingface-hub": "1.33.0"})
        self.assertEqual(
            active["freeze"],
            ["huggingface-hub==1.33.0", "mlx-lm==0.31.3", "safetensors==0.6.2"],
        )
        calls = [json.loads(line) for line in uv_capture.read_text().splitlines()]
        self.assertIn("mlx-lm==0.31.3", calls[1])
        self.assertIn("huggingface-hub==1.33.0", calls[1])
        self.assertEqual(calls[2][:2], ["pip", "freeze"])

    def test_quantize_integrates_with_real_resource_gate_contract(self):
        from tfmanager.resources import ResourceGate

        class Observer:
            def capture(self):
                gib = 1024**3
                return {
                    "at": time.time(),
                    "memory": {
                        "physical_bytes": 256 * gib,
                        "available_bytes": 200 * gib,
                        "pressure": "normal",
                        "swap_used_bytes": 0,
                        "missing": [],
                    },
                    "services": [],
                    "missing": [],
                }

        resources = ResourceGate(self.store, observer=Observer(), lock_dir=self.root / "resource-locks")
        tools = self.make_tools(resources)
        with patch.object(tools, "_external_service_running", return_value=False):
            row = tools.quantize(
                {"model": str(self.model), "name": "resource-gated-q4", "bits": 4, "group_size": 64, "mode": "affine"}
            )
            result = wait_job(self.jobs, row["id"])
        self.assertEqual(result["status"], "completed", result)


class UploadTests(unittest.TestCase):
    setUp = ToolTests.setUp
    make_tools = ToolTests.make_tools
    def response(self, payload):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit=-1):
                return json.dumps(payload).encode()

        return Response()

    def test_prepare_reports_actual_existing_visibility_and_whitelisted_hashes(self):
        tools = self.make_tools()
        (self.model / "tokenizer.json").write_text("{}")
        (self.model / ".secret").write_text("must not upload")
        (self.model / "manager.log").write_text("must not upload")
        with patch("tfmanager.tools.Tools._open_hf", return_value=self.response({"id": "owner/model", "private": True})):
            plan = tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "private"})
        self.assertTrue(plan["existing"])
        self.assertEqual(plan["visibility"], "private")
        self.assertEqual([row["path"] for row in plan["files"]], ["config.json", "model.safetensors", "tokenizer.json"])
        self.assertTrue(all(len(row["sha256"]) == 64 for row in plan["files"]))
        with patch("tfmanager.tools.Tools._open_hf", return_value=self.response({"id": "owner/model", "private": True})):
            with self.assertRaisesRegex(APIError, "visibility"):
                tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "public"})

    def test_only_404_means_new_repo_and_new_visibility_is_required(self):
        tools = self.make_tools()
        request = urllib.request.Request("https://huggingface.co/api/models/owner/model")
        for status in (401, 403):
            error = urllib.error.HTTPError(request.full_url, status, "denied", {}, None)
            with patch("tfmanager.tools.Tools._open_hf", side_effect=error):
                with self.assertRaisesRegex(APIError, "access"):
                    tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "private"})
        missing = urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        with patch("tfmanager.tools.Tools._open_hf", side_effect=missing):
            with self.assertRaisesRegex(APIError, "visibility"):
                tools.upload_prepare({"model": str(self.model), "repo": "owner/model"})
            plan = tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "public"})
        self.assertFalse(plan["existing"])
        self.assertEqual(plan["visibility"], "public")

    def test_confirm_rechecks_hash_and_upload_child_never_persists_or_logs_token(self):
        tools = self.make_tools()
        missing = urllib.error.HTTPError("https://huggingface.co/api/models/owner/model", 404, "missing", {}, None)
        with patch("tfmanager.tools.Tools._open_hf", side_effect=missing):
            plan = tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "private"})
        (self.model / "config.json").write_text("{}")
        with self.assertRaisesRegex(APIError, "changed"):
            tools.upload_confirm({"plan_id": plan["plan_id"], "confirm": True})
        (self.model / "config.json").write_text(
            json.dumps({"model_type": "qwen3_5", "_name_or_path": "Vontra/Qwen3.8-27B-MLX-4bit"})
        )
        with patch("tfmanager.tools.Tools._open_hf", side_effect=missing):
            plan = tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "private"})
        with patch("tfmanager.tools.Tools._open_hf", side_effect=missing):
            result = wait_job(self.jobs, tools.upload_confirm({"plan_id": plan["plan_id"], "confirm": True})["id"])
        self.assertEqual(result["status"], "completed", result)
        capture = json.loads(self.capture.read_text())
        self.assertEqual(capture["args"][:2], ["-I", "-B"])
        self.assertTrue(capture["token_present"])
        self.assertEqual(capture["implicit"], "1")
        self.assertTrue(Path(capture["hf_home"]).is_relative_to(self.store.root))
        self.assertTrue(Path(capture["home"]).is_relative_to(self.store.root))
        secret = "upload-secret-value"
        persisted = json.dumps(self.jobs.list()) + json.dumps(self.store.logs())
        persisted += "".join(path.read_text(errors="ignore") for path in (self.store.root / "uploads").rglob("*") if path.is_file())
        self.assertNotIn(secret, persisted)

    def test_upload_source_rejects_symlinks_and_non_owned_converted_directory(self):
        tools = self.make_tools()
        target = self.root / "outside.safetensors"
        target.write_bytes(b"outside")
        (self.model / "linked.safetensors").symlink_to(target)
        with self.assertRaisesRegex(APIError, "symbolic"):
            tools.upload_prepare({"model": str(self.model), "repo": "owner/model", "visibility": "private"})
        converted = self.store.root / "converted" / "unowned"
        converted.mkdir(parents=True)
        (converted / "config.json").write_text("{}")
        (converted / "model.safetensors").write_bytes(b"x")
        with self.assertRaises(APIError):
            tools.upload_prepare({"model": str(converted), "repo": "owner/model", "visibility": "private"})

    def test_repository_metadata_request_never_follows_authorization_redirect(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from tfmanager.tools import Tools

        received = []

        class Downstream(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        downstream = ThreadingHTTPServer(("127.0.0.1", 0), Downstream)
        self.addCleanup(downstream.server_close)
        threading.Thread(target=downstream.serve_forever, daemon=True).start()
        self.addCleanup(downstream.shutdown)

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{downstream.server_port}/stolen")
                self.end_headers()

            def log_message(self, *_):
                pass

        origin = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        self.addCleanup(origin.server_close)
        threading.Thread(target=origin.serve_forever, daemon=True).start()
        self.addCleanup(origin.shutdown)
        request = urllib.request.Request(
            f"http://127.0.0.1:{origin.server_port}/repo", headers={"Authorization": "Bearer private"}
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            Tools._open_hf(request)
        self.assertEqual(caught.exception.code, 302)
        self.assertEqual(received, [])

    def test_upload_child_rechecks_hash_on_the_open_file_before_network_write(self):
        from tfmanager.tools import UPLOAD_SCRIPT

        source = self.root / "upload-script-source"
        source.mkdir()
        file = source / "config.json"
        file.write_bytes(b"planned")
        import hashlib

        manifest = self.root / "upload-script-plan.json"
        manifest.write_text(
            json.dumps(
                {
                    "repo": "owner/model",
                    "visibility": "private",
                    "existing": True,
                    "source": str(source),
                    "files": [
                        {"path": "config.json", "size_bytes": 7, "sha256": hashlib.sha256(b"planned").hexdigest()}
                    ],
                }
            )
        )
        uploads = []

        class HfApi:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def upload_file(self, **kwargs):
                uploads.append(kwargs["path_or_fileobj"].read())

        module = types.ModuleType("huggingface_hub")
        module.HfApi = HfApi
        with patch.dict(sys.modules, {"huggingface_hub": module}), patch.object(sys, "argv", ["upload", str(manifest)]), patch.dict(
            os.environ, {"TFM_HF_UPLOAD_TOKEN": "script-secret"}
        ):
            exec(compile(UPLOAD_SCRIPT, "<upload-script>", "exec"), {"__name__": "__main__"})
        self.assertEqual(uploads, [b"planned"])
        file.write_bytes(b"changed")
        with patch.dict(sys.modules, {"huggingface_hub": module}), patch.object(sys, "argv", ["upload", str(manifest)]), patch.dict(
            os.environ, {"TFM_HF_UPLOAD_TOKEN": "script-secret"}
        ):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                exec(compile(UPLOAD_SCRIPT, "<upload-script>", "exec"), {"__name__": "__main__"})
        self.assertEqual(uploads, [b"planned"])


if __name__ == "__main__":
    unittest.main()

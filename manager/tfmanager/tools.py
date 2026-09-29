"""Isolated MLX conversion tools and explicit two-phase Hugging Face uploads."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .state import APIError, clean_env, identifier, repo_id


MLX_LM_VERSION = "0.31.3"
HUGGINGFACE_HUB_VERSION = "2.0.0"
PLAN_LIFETIME_SECONDS = 15 * 60
MAX_CHILD_OUTPUT = 4 * 1024 * 1024

UPLOAD_NAMES = frozenset(
    (
        "README.md",
        "LICENSE",
        "LICENSE.md",
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "preprocessor_config.json",
        "processor_config.json",
        "chat_template.json",
        "chat_template.jinja",
        "model.safetensors.index.json",
        "tokenizer.model",
        "spiece.model",
        "vocab.json",
        "merges.txt",
    )
)

UPLOAD_SCRIPT = r"""
import hashlib, json, os, pathlib, sys
from huggingface_hub import HfApi

manifest_path = pathlib.Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text())
token = os.environ.pop("TFM_HF_UPLOAD_TOKEN")
api = HfApi(endpoint="https://huggingface.co", token=token, library_name="tensorfold-manager")
if not manifest["existing"]:
    api.create_repo(
        repo_id=manifest["repo"],
        repo_type="model",
        private=manifest["visibility"] == "private",
        exist_ok=False,
    )
source = pathlib.Path(manifest["source"])
for item in manifest["files"]:
    candidate = source / item["path"]
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(source.resolve()):
        raise RuntimeError("Upload source changed after confirmation")
    with candidate.open("rb") as stream:
        digest = hashlib.sha256()
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if os.fstat(stream.fileno()).st_size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
            raise RuntimeError("Upload source changed after confirmation")
        stream.seek(0)
        api.upload_file(
            path_or_fileobj=stream,
            path_in_repo=item["path"],
            repo_id=manifest["repo"],
            repo_type="model",
            commit_message="Upload from TensorFold Manager",
        )
"""


class Tools:
    def __init__(self, store, jobs, engine, models, credentials, resources=None):
        self.store = store
        self.jobs = jobs
        self.engine = engine
        self.models = models
        self.credentials = credentials
        self.resources = resources if resources is not None else getattr(engine, "resources", None)
        self.install_lock = threading.Lock()
        self.tools_root = store.root / "tools"
        self.converted_root = store.root / "converted"
        self.upload_root = store.root / "uploads"
        for root in (self.tools_root, self.converted_root, self.upload_root):
            root.mkdir(exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
        jobs.register("tool_install", self.run_install)
        jobs.register("quantize", self.run_quantize)
        jobs.register("upload", self.run_upload)

    def status(self):
        return {
            "active": self.store.get("tools_active"),
            "pins": {"mlx-lm": MLX_LM_VERSION, "huggingface-hub": HUGGINGFACE_HUB_VERSION},
        }

    def install(self, data=None):
        if data not in (None, {}):
            raise APIError("Tool installation does not accept custom packages")
        return self.jobs.create("tool_install", {})

    @staticmethod
    def _runtime_paths():
        uv = Path(os.environ.get("TFM_UV", ""))
        runtime = Path(os.environ.get("TFM_RUNTIME_PYTHON", ""))
        if not uv.is_absolute() or not uv.is_file() or not runtime.is_absolute() or not runtime.is_file():
            raise APIError("Bundled uv and stable runtime Python are required", "runtime_unavailable", 409)
        return uv.resolve(), runtime.resolve()

    def _run(self, argv, job, env=None, secrets=(), log_output=True):
        output = []
        output_size = 0
        output_overflow = False
        output_lock = threading.Lock()
        process = subprocess.Popen(
            [str(item) for item in argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=env or clean_env(),
            start_new_session=True,
        )

        def read_output():
            nonlocal output_size, output_overflow
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    return
                with output_lock:
                    encoded_size = len(chunk.encode("utf-8", errors="replace"))
                    if output_size + encoded_size <= MAX_CHILD_OUTPUT:
                        output.append(chunk)
                        output_size += encoded_size
                    else:
                        output_overflow = True

        reader = threading.Thread(target=read_output, daemon=True, name="tool-output-" + job.id)
        reader.start()
        try:
            while process.poll() is None:
                job.checkpoint()
                time.sleep(0.1)
            reader.join(timeout=5)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            reader.join(timeout=5)
            if process.stdout:
                process.stdout.close()
        text = "".join(output)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        if output_overflow:
            raise APIError("Tool output exceeded the safe capture limit", "tool_failed", 409)
        if log_output and text:
            self.store.log("info", text[-16000:])
        if process.returncode:
            raise APIError(f"Tool process exited with code {process.returncode}", "tool_failed", 409)
        return text

    def run_install(self, job):
        if not self.install_lock.acquire(blocking=False):
            raise APIError("Another tools installation is running", "update_busy", 409)
        try:
            uv, runtime = self._runtime_paths()
            slot = self.tools_root / (
                f"mlx-lm-{MLX_LM_VERSION}-hub-{HUGGINGFACE_HUB_VERSION}-{uuid.uuid4().hex[:8]}"
            )
            env = clean_env()
            home = self.store.root / "tools-installer-home"
            home.mkdir(exist_ok=True, mode=0o700)
            env.update(
                HOME=str(home),
                UV_CACHE_DIR=str(self.store.root / "uv-cache"),
                UV_NO_CONFIG="1",
                UV_NO_PYTHON_DOWNLOADS="1",
                HF_HOME=str(self.store.root / "tools-hf-home"),
                HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
            )
            job.progress(phase="create_environment")
            self._run([uv, "venv", "--no-python-downloads", "--python", runtime, slot], job, env)
            python = slot / "bin/python"
            job.progress(phase="install_pinned_packages")
            self._run(
                [
                    uv,
                    "pip",
                    "install",
                    "--no-python-downloads",
                    "--python",
                    python,
                    f"mlx-lm=={MLX_LM_VERSION}",
                    f"huggingface-hub=={HUGGINGFACE_HUB_VERSION}",
                ],
                job,
                env,
            )
            job.progress(phase="record_provenance")
            freeze_text = self._run([uv, "pip", "freeze", "--python", python], job, env)
            freeze = sorted(line.strip() for line in freeze_text.splitlines() if line.strip())
            normalized = {line.lower() for line in freeze}
            if f"mlx-lm=={MLX_LM_VERSION}" not in normalized or f"huggingface-hub=={HUGGINGFACE_HUB_VERSION}" not in normalized:
                raise APIError("Pinned tool versions were not installed", "tool_install_failed", 409)
            provenance = {
                "python": str(python),
                "slot": str(slot),
                "installed_at": time.time(),
                "packages": {"mlx-lm": MLX_LM_VERSION, "huggingface-hub": HUGGINGFACE_HUB_VERSION},
                "sources": [
                    {"name": "mlx-lm", "version": MLX_LM_VERSION, "index": "https://pypi.org/simple"},
                    {
                        "name": "huggingface-hub",
                        "version": HUGGINGFACE_HUB_VERSION,
                        "index": "https://pypi.org/simple",
                    },
                ],
                "freeze": freeze,
            }
            provenance_path = slot / "tfmanager-provenance.json"
            provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True))
            os.chmod(provenance_path, 0o600)
            self.store.put("tools_active", provenance)
            return provenance
        finally:
            self.install_lock.release()

    def _active_python(self):
        pointer = self.store.get("tools_active")
        if not isinstance(pointer, dict) or not isinstance(pointer.get("python"), str):
            raise APIError("Install the model tools first", "tools_not_installed", 409)
        python = Path(pointer["python"])
        if not python.is_absolute() or not python.is_relative_to(self.tools_root) or not python.is_file():
            raise APIError("The active model tools environment is invalid", "tools_not_installed", 409)
        return python

    def _external_service_running(self):
        checker = getattr(self.resources, "external_services", None)
        if callable(checker):
            return bool(checker())
        try:
            with socket.create_connection(("127.0.0.1", 8089), timeout=0.2):
                return True
        except OSError:
            return False

    def _ensure_heavy_available(self, source=None, options=None):
        self._ensure_engine_stopped()
        preflight = getattr(self.resources, "preflight_quantize", None)
        if callable(preflight):
            report = preflight(source, options=options or {})
            if isinstance(report, dict) and not report.get("allowed"):
                from .resources import ResourceBlocked

                raise ResourceBlocked(report)
        self._ensure_no_external_service()

    def _ensure_engine_stopped(self):
        state = self.engine.status().get("state")
        if state != "stopped":
            raise APIError("Stop the running TensorFold engine before quantizing", "resource_blocked", 409)

    def _ensure_no_external_service(self):
        if self._external_service_running():
            raise APIError("Stop the external TensorFold service before quantizing", "resource_blocked", 409)

    def _quantize_lease(self, source, options):
        acquire = getattr(self.resources, "acquire_quantize", None)
        if callable(acquire):
            return acquire(source, options=options)
        return self.engine.lifecycle

    def quantize(self, data):
        if not isinstance(data, dict):
            raise APIError("Quantization request must be an object")
        bits = data.get("bits")
        group_size = data.get("group_size")
        mode = data.get("mode")
        if type(bits) is not int or bits not in (2, 3, 4, 6, 8):
            raise APIError("bits must be one of 2,3,4,6,8")
        if type(group_size) is not int or group_size not in (32, 64, 128):
            raise APIError("group_size must be one of 32,64,128")
        if mode != "affine":
            raise APIError("Only affine quantization is supported")
        model = self.models.resolve(data.get("model"))
        name = data.get("name") or f"{model['name']}-q{bits}-g{group_size}"
        name = identifier(name, "output name")
        output = self.converted_root / name
        if output.exists():
            raise APIError("The converted output already exists", "output_exists", 409)
        options = {"bits": bits, "group_size": group_size}
        self._ensure_heavy_available(model["path"], options)
        return self.jobs.create(
            "quantize",
            {
                "source": model["path"],
                "source_id": model["id"],
                "source_fingerprint": self.models.fingerprint(Path(model["path"])),
                "output": str(output),
                "bits": bits,
                "group_size": group_size,
                "mode": mode,
            },
        )

    @staticmethod
    def _validate_weights(path):
        path = Path(path)
        if path.is_symlink() or not path.is_dir():
            raise APIError("Converted model directory is invalid", "conversion_failed", 409)
        try:
            config = json.loads((path / "config.json").read_text())
        except (OSError, ValueError):
            raise APIError("Converted model config is missing or invalid", "conversion_failed", 409)
        if not isinstance(config, dict):
            raise APIError("Converted model config is invalid", "conversion_failed", 409)
        weights = sorted(path.glob("*.safetensors"))
        if any(item.is_symlink() for item in weights):
            raise APIError("Upload or conversion source contains a symbolic link", "unsafe_model_source", 409)
        if not weights or any(not item.is_file() or item.stat().st_size == 0 for item in weights):
            raise APIError("Converted model weights are incomplete", "conversion_failed", 409)
        index = path / "model.safetensors.index.json"
        if index.exists():
            try:
                names = set(json.loads(index.read_text())["weight_map"].values())
            except (OSError, ValueError, KeyError, TypeError):
                raise APIError("Converted model weight index is invalid", "conversion_failed", 409)
            if not names or any(
                not isinstance(name, str)
                or Path(name).is_absolute()
                or ".." in Path(name).parts
                or not (path / name).is_file()
                for name in names
            ):
                raise APIError("Converted model weight index is incomplete", "conversion_failed", 409)
        shards = [re.fullmatch(r"model-(\d+)-of-(\d+)\.safetensors", item.name) for item in weights if item.name.startswith("model-")]
        if shards:
            if not all(shards):
                raise APIError("Converted model shards are malformed", "conversion_failed", 409)
            totals = {int(match.group(2)) for match in shards}
            if len(totals) != 1 or {int(match.group(1)) for match in shards} != set(range(1, next(iter(totals)) + 1)):
                raise APIError("Converted model shards are incomplete", "conversion_failed", 409)
        return config, weights

    def run_quantize(self, job):
        params = job.params
        source = Path(params["source"])
        output = Path(params["output"])
        if not source.is_absolute() or not output.is_relative_to(self.converted_root) or output.name.startswith("."):
            raise APIError("Invalid quantization paths")
        model = self.models.resolve(str(source))
        if model["id"] != params["source_id"] or self.models.fingerprint(source) != params["source_fingerprint"]:
            raise APIError("Quantization source changed", "source_changed", 409)
        options = {"bits": params["bits"], "group_size": params["group_size"]}
        stage = self.converted_root / (".staging-" + job.id)
        if stage.exists() or output.exists():
            raise APIError("The converted output already exists", "output_exists", 409)
        lease = self._quantize_lease(str(source), options)
        with lease:
            # The resource coordinator already validated its own lease. Recheck only
            # independently changing processes after the lease is held.
            self._ensure_engine_stopped()
            self._ensure_no_external_service()
            python = self._active_python()
            env = clean_env()
            home = self.store.root / "tools-runtime-home"
            home.mkdir(exist_ok=True, mode=0o700)
            env.update(
                HOME=str(home),
                HF_HOME=str(self.store.root / "tools-hf-home"),
                HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
            )
            job.progress(phase="quantize", source=str(source), output=str(output))
            try:
                self._run(
                    [
                        python,
                        "-I",
                        "-B",
                        "-m",
                        "mlx_lm",
                        "convert",
                        "--hf-path",
                        source,
                        "--mlx-path",
                        stage,
                        "--quantize",
                        "--q-bits",
                        params["bits"],
                        "--q-group-size",
                        params["group_size"],
                        "--q-mode",
                        "affine",
                    ],
                    job,
                    env,
                )
                job.checkpoint()
                self._validate_weights(stage)
                cli_info = self.engine.inspect_model(self.engine.executable(), str(stage))
                manifest = {
                    "owner": "tfmanager",
                    "kind": "converted-model",
                    "source": str(source),
                    "source_fingerprint": self.models.fingerprint(source),
                    "created_at": time.time(),
                    "quantization": {
                        "bits": params["bits"],
                        "group_size": params["group_size"],
                        "mode": "affine",
                    },
                    "cli_info": cli_info,
                }
                manifest_path = stage / ".tfmanager-manifest.json"
                manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
                os.chmod(manifest_path, 0o600)
                if output.exists():
                    raise APIError("The converted output already exists", "output_exists", 409)
                stage.rename(output)
            except BaseException:
                if stage.exists():
                    shutil.rmtree(stage)
                raise
        settings = self.store.settings()
        converted = str(self.converted_root)
        if converted not in settings["model_dirs"]:
            self.store.settings_update({"model_dirs": settings["model_dirs"] + [converted]})
        return {"path": str(output), "quantization": manifest["quantization"], "cli_info": cli_info}

    @staticmethod
    def _allowed_upload_file(relative):
        relative = Path(relative)
        if relative.is_absolute() or not relative.parts or any(part.startswith(".") or part in ("", "..") for part in relative.parts):
            return False
        name = relative.name
        return name in UPLOAD_NAMES or name.endswith(".safetensors")

    def _upload_source(self, value):
        if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
            raise APIError("An absolute local model path is required")
        source = Path(value).expanduser().resolve()
        if source.is_relative_to(self.converted_root):
            manifest = source / ".tfmanager-manifest.json"
            try:
                owned = json.loads(manifest.read_text())
            except (OSError, ValueError):
                owned = None
            if not isinstance(owned, dict) or owned.get("owner") != "tfmanager" or owned.get("kind") != "converted-model":
                raise APIError("Only Manager-owned converted outputs can be uploaded", "forbidden", 403)
        else:
            row = self.models.describe(source)
            if not row or not row["installed"]:
                raise APIError("Upload source is not a complete scanned model", "model_missing", 409)
        self._validate_weights(source)
        return source

    @staticmethod
    def _hash_file(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)

    def _upload_files(self, source):
        rows = []
        for base, directories, filenames in os.walk(source, followlinks=False):
            base_path = Path(base)
            for directory in directories:
                if (base_path / directory).is_symlink():
                    raise APIError("Upload source contains a symbolic link", "unsafe_upload_source", 409)
            for filename in filenames:
                file = base_path / filename
                if file.is_symlink():
                    raise APIError("Upload source contains a symbolic link", "unsafe_upload_source", 409)
                relative = file.relative_to(source)
                if not self._allowed_upload_file(relative):
                    continue
                stat = file.stat()
                rows.append({"path": relative.as_posix(), "size_bytes": stat.st_size, "sha256": self._hash_file(file)})
        rows.sort(key=lambda row: row["path"])
        if not rows or "config.json" not in {row["path"] for row in rows} or not any(row["path"].endswith(".safetensors") for row in rows):
            raise APIError("Upload source has no complete whitelisted model payload", "model_missing", 409)
        return rows

    @staticmethod
    def _files_fingerprint(rows):
        digest = hashlib.sha256()
        for row in rows:
            digest.update(f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\n".encode())
        return digest.hexdigest()

    @staticmethod
    def _open_hf(request):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, new_url):
                return None

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        return opener.open(request, timeout=15)

    @staticmethod
    def _repo_info(repo, token):
        request = urllib.request.Request(
            "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/"),
            headers={"Authorization": "Bearer " + token, "User-Agent": "TensorFold-Manager"},
        )
        try:
            with Tools._open_hf(request) as response:
                if response.status != 200:
                    raise APIError("Hugging Face repository lookup failed", "remote_error", 502)
                payload = json.loads(response.read(1024 * 1024))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (401, 403):
                raise APIError("Hugging Face repository access was denied", "credential_denied", 403)
            raise APIError("Hugging Face repository lookup failed", "remote_error", 502)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise APIError("Hugging Face repository lookup failed", "remote_error", 502)
        if not isinstance(payload, dict) or not isinstance(payload.get("private"), bool):
            raise APIError("Hugging Face repository returned invalid metadata", "remote_error", 502)
        return {"visibility": "private" if payload["private"] else "public"}

    def upload_prepare(self, data):
        if not isinstance(data, dict):
            raise APIError("Upload request must be an object")
        repo = repo_id(data.get("repo"))
        visibility = data.get("visibility")
        if visibility is not None and visibility not in ("public", "private"):
            raise APIError("visibility must be public or private")
        source = self._upload_source(data.get("model"))
        token = self.credentials.get("hf-upload")
        remote = self._repo_info(repo, token)
        if remote is None:
            if visibility not in ("public", "private"):
                raise APIError("A new repository requires explicit public or private visibility")
            existing = False
            actual_visibility = visibility
        else:
            existing = True
            actual_visibility = remote["visibility"]
            if visibility is not None and visibility != actual_visibility:
                raise APIError("Requested visibility does not match the existing repository visibility", "visibility_mismatch", 409)
        files = self._upload_files(source)
        plan_id = uuid.uuid4().hex
        now = time.time()
        plan = {
            "plan_id": plan_id,
            "repo": repo,
            "visibility": actual_visibility,
            "remote_visibility": actual_visibility if existing else None,
            "existing": existing,
            "source": str(source),
            "files": files,
            "size_bytes": sum(row["size_bytes"] for row in files),
            "source_hash": self._files_fingerprint(files),
            "created_at": now,
            "expires_at": now + PLAN_LIFETIME_SECONDS,
        }
        self.store.put("upload_plan", plan, plan_id)
        return plan

    def _validated_plan(self, plan_id):
        plan_id = identifier(plan_id, "plan id")
        plan = self.store.get("upload_plan", plan_id)
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            raise APIError("Upload plan was not found", "not_found", 404)
        if not isinstance(plan.get("expires_at"), (int, float)) or plan["expires_at"] < time.time():
            raise APIError("Upload plan expired; prepare it again", "plan_expired", 409)
        source = self._upload_source(plan.get("source"))
        files = self._upload_files(source)
        if files != plan.get("files") or self._files_fingerprint(files) != plan.get("source_hash"):
            raise APIError("Upload source changed after the plan was prepared", "source_changed", 409)
        return plan

    def upload_confirm(self, data):
        if not isinstance(data, dict) or data.get("confirm") is not True:
            raise APIError("Explicit upload confirmation is required")
        plan = self._validated_plan(data.get("plan_id"))
        if not self.credentials.status("hf-upload")["configured"]:
            raise APIError("Hugging Face upload credential is not configured", "credential_missing", 409)
        return self.jobs.create("upload", {"plan_id": plan["plan_id"]})

    def run_upload(self, job):
        plan = self._validated_plan(job.params["plan_id"])
        token = self.credentials.get("hf-upload")
        remote = self._repo_info(plan["repo"], token)
        if plan["existing"]:
            if remote is None or remote["visibility"] != plan["visibility"]:
                raise APIError("Repository visibility or existence changed; prepare again", "remote_changed", 409)
        elif remote is not None:
            raise APIError("Repository was created after preparation; prepare again", "remote_changed", 409)
        python = self._active_python()
        manifest = {key: plan[key] for key in ("repo", "visibility", "existing", "source", "files")}
        manifest_path = self.upload_root / (job.id + ".json")
        manifest_path.write_text(json.dumps(manifest, sort_keys=True))
        os.chmod(manifest_path, 0o600)
        env = clean_env()
        home = self.store.root / "upload-home"
        home.mkdir(exist_ok=True, mode=0o700)
        hf_home = self.store.root / "upload-hf-home"
        hf_home.mkdir(exist_ok=True, mode=0o700)
        env.update(
            HOME=str(home),
            HF_HOME=str(hf_home),
            HF_TOKEN_PATH=str(hf_home / "token"),
            HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
            TFM_HF_UPLOAD_TOKEN=token,
        )
        job.progress(phase="upload", repo=plan["repo"], files=len(plan["files"]))
        self._run(
            [python, "-I", "-B", "-c", UPLOAD_SCRIPT, manifest_path],
            job,
            env,
            secrets=(token,),
            log_output=False,
        )
        return {
            "repo": plan["repo"],
            "visibility": plan["visibility"],
            "files": len(plan["files"]),
            "size_bytes": plan["size_bytes"],
            "partial_remote_changes_possible": True,
        }

"""暴露给前端 JS 的 API 面（v2：多实例池 + 每模型设置 + 更新检查）。

WKScriptMessageHandler 桥与 pywebview js_api 都直接映射本类方法，方法名即桥方法名。
"""
from __future__ import annotations

import json
import os
import shutil

from . import engine as engine_mod
from .chat import ChatStore

DEFAULT_APP_SETTINGS = {
    "default_context": 32768,
    "parallel": 4,
    "prompt_cache_gib": 16,
    "default_model": "",
    "autostart_engine": False,
    "auto_update_check": True,
    "menubar": True,
    "close_to_menubar": True,
    "theme": "system",  # system|light|dark
}


class Api:
    def __init__(self, pool, download, monitor, chat_proxy, store: ChatStore, updater=None,
                 app_settings_path: str | None = None):
        self.pool = pool
        self.engine = pool  # 兼容 v1 命名
        self.download = download
        self.monitor = monitor
        self.proxy = chat_proxy
        self.store = store
        self.updater = updater
        self._app_settings_path = app_settings_path or os.path.expanduser(
            "~/.tensorfold-manager/app_settings.json")
        try:
            import psutil
            self.psutil = psutil
        except ImportError:
            self.psutil = None

    # ---------- 总览 ----------
    def overview(self) -> dict:
        st = self.pool.status_all()
        mon = self.monitor.snapshot()
        free = 0.0
        total = 0.0
        if self.psutil:
            try:
                vm = self.psutil.virtual_memory()
                total = round(vm.total / 1024**3, 1)
                free = round(vm.available / 1024**3, 1)
            except Exception:
                pass
        disk = shutil.disk_usage(os.path.expanduser("~"))
        return {
            "instances": st["instances"],
            "metrics_latest": mon["latest"],
            "per": mon["per"],
            "series": mon["series"],
            "mem_total": total, "mem_free": free,
            "cpu_cores": (self.psutil.cpu_count() if self.psutil else None),
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "proxy_port": self.proxy.server_address[1] if self.proxy else 0,
        }

    # ---------- 引擎 ----------
    def engine_start(self, model: str, **overrides) -> dict:
        clean = {}
        for k in ("port", "context", "max_tokens", "temperature", "top_p", "top_k",
                  "mtp_drafts", "mtp_confidence", "prompt_cache_gib", "parallel", "alias"):
            if k in overrides and overrides[k] not in (None, ""):
                clean[k] = float(overrides[k]) if k in ("temperature", "top_p", "mtp_confidence", "prompt_cache_gib") \
                    else (int(overrides[k]) if k != "alias" else overrides[k])
        for k in ("thinking", "drafts", "vision"):
            if k in overrides:
                clean[k] = bool(overrides[k])
        for k in ("kv_dtype", "backend", "reasoning_effort"):
            if overrides.get(k):
                clean[k] = overrides[k]
        # 全局设置兜底：仅当「本次未传且该模型也没保存」时才用设置页的值
        # （优先级：本次参数 > 每模型已存 > 全局默认；pool 里 load_for(model).update(overrides)，
        #  所以这里绝不能把全局值塞进 overrides 覆盖每模型已存值）
        g = self.app_settings_get()
        saved = self.pool.settings.raw_for(model)
        for k, gk in (("parallel", "parallel"),
                      ("prompt_cache_gib", "prompt_cache_gib"),
                      ("context", "default_context")):
            if clean.get(k) is None and saved.get(k) is None:
                clean[k] = g[gk]
        return self.pool.start(model, **clean)

    def engine_stop(self, model: str | None = None) -> dict:
        r = self.pool.stop(model or None)
        if model:
            self.monitor.reset_model(model)
        else:
            self.monitor.reset()
        return r

    def engine_status(self) -> dict:
        return self.pool.status_all()

    def engine_log(self, model: str | None = None) -> list[str]:
        return self.pool.log_for(model) if model else self.pool.get_log()

    # ---------- 模型 ----------
    def models_installed(self) -> list[dict]:
        return engine_mod.cached_models()

    def families(self) -> list[dict]:
        return engine_mod.FAMILIES

    def model_delete(self, repo_id: str) -> dict:
        return self.pool.delete_model(repo_id)

    def model_pull(self, repo_id: str) -> dict:
        repo_id = repo_id.strip()
        if not repo_id or "/" not in repo_id:
            return {"ok": False, "error": "输入完整的 Hugging Face repo id，如 TensorFold/Qwen3.8-27B-MLX-4bit"}
        return self.download.start(repo_id)

    def pull_status(self) -> dict:
        return self.download.active()

    def pull_cancel(self, repo_id: str) -> dict:
        return self.download.cancel(repo_id)

    # ---------- 每模型设置 ----------
    def model_settings_get(self, model: str) -> dict:
        return self.pool.settings.load_for(model)

    def model_settings_save(self, model: str, params: dict) -> dict:
        params = params or {}
        self.pool.settings.save_for(model, params)
        return {"ok": True}

    # ---------- 聊天 ----------
    def chat_list(self) -> list[dict]:
        return self.store.list_chats()

    def chat_create(self, chat: dict | None = None) -> dict:
        return self.store.create(chat or {})

    def chat_get(self, chat_id: str) -> dict | None:
        return self.store.get_chat(chat_id)

    def chat_save(self, chat: dict) -> dict:
        return self.store.save_chat(chat)

    def chat_rename(self, chat_id: str, title: str) -> dict:
        return {"ok": self.store.rename_chat(chat_id, title)}

    def chat_delete(self, chat_id: str) -> dict:
        return {"ok": self.store.delete_chat(chat_id)}

    # ---------- 更新 ----------
    def update_check(self) -> dict:
        if not self.updater:
            return {"error": "更新检查未启用"}
        self.updater.engine_version = self.pool.detect().get("version", "")
        return self.updater.check_all()

    def update_status(self) -> dict:
        return self.updater.cached() if self.updater else {}

    def update_apply_engine(self) -> dict:
        if not self.updater:
            return {"ok": False, "error": "更新检查未启用"}
        return self.updater.apply_engine(self.pool.python_bin, log=self.pool.log)

    def update_open_app(self) -> dict:
        if not self.updater:
            return {"ok": False, "error": "更新检查未启用"}
        from .update import apply_app_open
        app = (self.updater.cached().get("app") or {})
        return apply_app_open(app.get("url", ""))

    # ---------- 设置 ----------
    def settings(self) -> dict:
        base = self.pool.detect()
        if self.updater:
            self.updater.engine_version = base.get("version", "")
        return {"installed": base["installed"], "cli": base["path"], "version": base["version"],
                "app_version": self.updater.app_version if self.updater else "",
                "proxy_port": self.proxy.server_address[1] if self.proxy else 0}

    def app_settings_get(self) -> dict:
        try:
            with open(self._app_settings_path, encoding="utf-8") as f:
                return {**DEFAULT_APP_SETTINGS, **json.load(f)}
        except (OSError, ValueError):
            return dict(DEFAULT_APP_SETTINGS)

    def app_settings_save(self, **kwargs) -> dict:
        cur = self.app_settings_get()
        cur.update({k: v for k, v in kwargs.items() if k in DEFAULT_APP_SETTINGS})
        try:
            os.makedirs(os.path.dirname(self._app_settings_path), exist_ok=True)
            tmp = self._app_settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False)
            os.replace(tmp, self._app_settings_path)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **cur}

    def open_hf_cache(self) -> dict:
        import subprocess
        d = engine_mod.hf_cache_dir()
        if not os.path.isdir(d):
            return {"ok": False, "error": "缓存目录还不存在"}
        subprocess.run(["open", d], check=False, timeout=10)
        return {"ok": True}

    def copy_text(self, text: str) -> dict:
        try:
            import subprocess
            p = subprocess.run(["pbcopy"], input=(text or "").encode(), timeout=5)
            return {"ok": p.returncode == 0}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

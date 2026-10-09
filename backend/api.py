"""暴露给前端 JS 的 API 面（v2：多实例池 + 每模型设置 + 更新检查）。

WKScriptMessageHandler 桥与 pywebview js_api 都直接映射本类方法，方法名即桥方法名。
"""
from __future__ import annotations

import json
import os
import shutil

from . import engine as engine_mod
from . import hostinfo
from .chat import ChatStore

DEFAULT_APP_SETTINGS = {
    "default_context": 32768,
    "parallel": 4,
    "prompt_cache_gib": 16,
    "default_model": "",
    # 监听范围：local = 只对本机广播（127.0.0.1）；lan = 对局域网广播（0.0.0.0）
    "listen": "local",
    "autostart_engine": False,
    "auto_update_check": True,
    "menubar": True,
    "close_to_menubar": True,
    "theme": "system",  # system|light|dark
    "model_dirs": [],   # 自定义模型扫描目录（绝对路径；HF 缓存与 oMLX/MTPLX 已内置）
}

LISTEN_HOSTS = {"local": "127.0.0.1", "lan": "0.0.0.0"}


def lan_ip() -> str:
    """本机在局域网里的地址（取默认路由出口的本地地址），取不到返回 ''。

    只是拿来给用户照着填；用 UDP connect 探测，不发包。
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


class Api:
    def __init__(self, pool, download, monitor, chat_proxy, store: ChatStore, updater=None,
                 app_settings_path: str | None = None, ledger=None):
        self.pool = pool
        self.engine = pool  # 兼容 v1 命名
        self.download = download
        self.monitor = monitor
        self.proxy = chat_proxy
        self.store = store
        self.updater = updater
        # 累计用量账本（跨引擎重启持续）；缺省从 monitor 上取
        self.ledger = ledger if ledger is not None else getattr(monitor, "ledger", None)
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
        appset = self.app_settings_get()
        listen = appset.get("listen") or "local"
        cpu = hostinfo.cpu_info()
        gpu = hostinfo.gpu_info()
        try:
            load = [round(v, 2) for v in os.getloadavg()]
        except OSError:
            load = []
        return {
            "instances": st["instances"],
            "metrics_latest": mon["latest"],
            "per": mon["per"],
            "series": mon["series"],
            "mem_total": total, "mem_free": free,
            # CPU / GPU 真实构成（取不到就是 None / ""，不猜数）
            "cpu_cores": cpu["logical"],
            "cpu_physical": cpu["physical"],
            "cpu_p": cpu["p"], "cpu_e": cpu["e"],
            "cpu_model": cpu["model"],
            "cpu_label": hostinfo.cpu_core_label(),
            "gpu_name": gpu["name"], "gpu_cores": gpu["cores"],
            "gpu_label": hostinfo.gpu_core_label(),
            "load": load,
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "proxy_port": self.proxy.server_address[1] if self.proxy else 0,
            "listen": listen,
            "bind_host": LISTEN_HOSTS.get(listen, "127.0.0.1"),
            "lan_ip": lan_ip() if listen == "lan" else "",
            # 累计用量（Manager 侧账本，跨引擎重启持续）
            "usage": self.ledger.summary() if self.ledger else {"totals": {}, "models": [], "since": 0},
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
        for k in ("kv_dtype", "backend", "reasoning_effort", "host"):
            if overrides.get(k):
                clean[k] = overrides[k]
        # 全局设置兜底：仅当「本次未传且该模型也没保存」时才用设置页的值
        # （优先级：本次参数 > 每模型已存 > 全局默认；pool 里 load_for(model).update(overrides)，
        #  所以这里绝不能把全局值塞进 overrides 覆盖每模型已存值）
        # context 不在此列：2026-10-09 起"初始设置 = 模型自身默认配置"，
        # 不显式传就由引擎按模型 config 自决（不传 --context 即模型默认）。
        g = self.app_settings_get()
        saved = self.pool.settings.raw_for(model)
        for k, gk in (("parallel", "parallel"),
                      ("prompt_cache_gib", "prompt_cache_gib")):
            if clean.get(k) is None and saved.get(k) is None:
                clean[k] = g[gk]
        # 监听范围是全局策略（不是每模型偏好）：除非该模型显式存过 host，否则跟随设置页
        if clean.get("host") is None and saved.get("host") is None:
            clean["host"] = LISTEN_HOSTS.get(g.get("listen") or "local", "127.0.0.1")
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
    def _sync_model_dirs(self):
        """把设置里的自定义扫描目录同步给池（扫描唯一入口）。"""
        dirs = [str(d) for d in (self.app_settings_get().get("model_dirs") or [])
                if str(d or "").strip()]
        if dirs != getattr(self.pool, "model_dirs", None):
            self.pool.model_dirs = dirs

    def models_installed(self) -> list[dict]:
        self._sync_model_dirs()
        return self.pool.cached()

    # ---------- 模型扫描目录 ----------
    def scan_dirs(self) -> dict:
        self._sync_model_dirs()
        return {"roots": engine_mod.scan_summary(self.pool.model_dirs),
                "extra": list(self.pool.model_dirs),
                "found": len(self.pool.cached())}

    def scan_dir_add(self, path: str) -> dict:
        p = os.path.expanduser((path or "").strip())
        if not p:
            return {"ok": False, "error": "请输入目录路径"}
        if not os.path.isdir(p):
            return {"ok": False, "error": f"目录不存在: {p}"}
        if os.path.realpath(p) == os.path.realpath(os.path.expanduser("~")):
            return {"ok": False, "error": "整个用户目录太大，请选具体的模型目录"}
        cur = list(self.app_settings_get().get("model_dirs") or [])
        if p in cur:
            return {"ok": True, "added": False, **self.scan_dirs()}
        cur.append(p)
        self.app_settings_save(model_dirs=cur)
        self._sync_model_dirs()
        return {"ok": True, "added": True, **self.scan_dirs()}

    def scan_dir_remove(self, path: str) -> dict:
        cur = [d for d in (self.app_settings_get().get("model_dirs") or []) if d != path]
        self.app_settings_save(model_dirs=cur)
        self._sync_model_dirs()
        return {"ok": True, **self.scan_dirs()}

    def pick_dir(self) -> dict:
        """弹系统目录选择框。WKWebView 桥回调在主线程，可直接 runModal。"""
        try:
            from AppKit import NSOpenPanel
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(False)
            panel.setCanChooseDirectories_(True)
            panel.setAllowsMultipleSelection_(False)
            panel.setPrompt_("选择模型目录")
            if panel.runModal() != 1:
                return {"ok": False, "cancelled": True}
            urls = panel.URLs()
            if not urls:
                return {"ok": False, "cancelled": True}
            return {"ok": True, "path": urls[0].path()}
        except Exception as exc:
            return {"ok": False, "error": f"无法打开选择框: {exc}"}

    def families(self) -> list[dict]:
        # 每张卡片带上自己的加速配套（草稿模型有没有下载、多大），模型页直接显示，
        # 点一下就能进设置里配置 —— 不用先去「本机缓存」列表里自己找。
        return [{**f, "accel": engine_mod.draft_status(f["id"])} for f in engine_mod.FAMILIES]

    def model_info(self, ref: str) -> dict:
        """模型元信息：默认配置/能力/加速配套（设置弹窗初值与属性区用）。"""
        return engine_mod.model_meta(ref)

    def model_delete(self, repo_id: str) -> dict:
        return self.pool.delete_model(repo_id)

    def model_pull(self, repo_id: str) -> dict:
        repo_id = repo_id.strip()
        if not repo_id or "/" not in repo_id:
            return {"ok": False, "error": "输入完整的 Hugging Face repo id，如 TensorFold/Qwen3.8-27B-MLX-4bit"}
        # 官方模型能给出预期体积 → 进度条可以给百分比；未知 repo（如草稿模型）
        # 就只报真实已落盘字节数，不编一个分母。
        fam = next((f for f in engine_mod.FAMILIES if f["id"] == repo_id), None)
        return self.download.start(repo_id, total_gb=(fam or {}).get("size_gb"))

    def pull_status(self) -> dict:
        return self.download.active()

    def pull_cancel(self, repo_id: str) -> dict:
        return self.download.cancel(repo_id)

    # ---------- 每模型设置 ----------
    def model_settings_get(self, model: str) -> dict:
        """合并默认值后的有效参数 + _raw（用户显式存过的键，UI 用来区分默认与用户值）。"""
        eff = self.pool.settings.load_for(model)
        eff["_raw"] = self.pool.settings.raw_for(model)
        return eff

    def model_settings_save(self, model: str, params: dict) -> dict:
        params = params or {}
        self.pool.settings.save_for(model, params)
        return {"ok": True}

    def model_settings_reset(self, model: str) -> dict:
        """清除该模型的覆盖项 → 回到模型自身默认配置（设置弹窗「恢复默认」）。"""
        self.pool.settings.delete_for(model)
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
        # 记下升级前在跑的模型（含各自参数），升级完原样拉回来——
        # 只"停掉等用户手动重载"会让升级看起来像失败（用户点了升级，回来模型没了）。
        before: list[tuple[str, dict]] = []
        for inst in self.pool.instances():
            try:
                if inst.alive() or inst.state in ("starting", "ready"):
                    before.append((inst.model, dict(inst.params)))
            except Exception:
                pass
        r = self.updater.apply_engine(log=self.pool.log)
        if not r.get("ok"):
            return r
        # 升级落盘后：新版本二进制已在 engines/ 下，find_launcher 现在就会选中它。
        # 1) 停掉运行中实例（旧引擎进程不会自动换血），释放端口与显存；
        # 2) 热刷新池与下载器的启动器引用；
        # 3) 把升级前在跑的模型用新引擎重新拉起。
        try:
            stopped = self.pool.stop()
            if stopped.get("stopped"):
                self.monitor.reset()
        except Exception as exc:
            self.pool.log(f"升级后停止旧实例异常: {exc}")
        launcher = engine_mod.find_launcher(os.path.dirname(
            os.path.dirname(os.path.abspath(engine_mod.__file__))))
        if launcher:
            self.pool.python_bin = launcher
            if self.download is not None:
                self.download.python_bin = launcher
        restarted, failed = [], []
        for model, params in before:
            params.pop("port", None)   # 重新分配端口，避开旧端口的 TIME_WAIT
            rr = self.pool.start(model, **params)
            (restarted if rr.get("ok") else failed).append(model)
        r["restarted"] = restarted
        r["restart_failed"] = failed
        if restarted:
            r["restarted_hint"] = "已用新引擎重新加载: " + "、".join(
                m.split("/")[-1] for m in restarted)
        elif failed:
            r["restarted_hint"] = "旧实例已停止，但用新引擎重载失败: " + "、".join(
                m.split("/")[-1] for m in failed)
        else:
            r["restarted_hint"] = "下次加载模型即用新引擎"
        return r

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

    # ---------- 用量（累计账本） ----------
    def usage_status(self) -> dict:
        return self.ledger.summary() if self.ledger else {"totals": {}, "models": [], "since": 0}

    def usage_reset(self) -> dict:
        if not self.ledger:
            return {"ok": False, "error": "用量账本未启用"}
        return self.ledger.reset()

    # ---------- 网络（监听范围） ----------
    def network(self) -> dict:
        """监听范围现状 + 本机地址（设置页用）。"""
        listen = self.app_settings_get().get("listen") or "local"
        port = self.proxy.server_address[1] if self.proxy else 0
        ip = lan_ip()
        running = [i["model"] for i in self.pool.status_all()["instances"]
                   if i.get("state") in ("ready", "starting")]
        return {
            "listen": listen,
            "bind_host": LISTEN_HOSTS.get(listen, "127.0.0.1"),
            "proxy_port": port,
            "proxy_host": getattr(self.proxy, "bind_host", "127.0.0.1") if self.proxy else "",
            "lan_ip": ip,
            "local_url": f"http://127.0.0.1:{port}/v1",
            "lan_url": (f"http://{ip}:{port}/v1" if ip else ""),
            "running": running,
        }

    def set_listen(self, listen: str) -> dict:
        """切监听范围。对话代理立刻重绑（不用重启 App）；引擎是 --host 真绑定，
        运行中的实例要重启才换地址 —— 这一步由 restart_instances 单独触发。"""
        listen = "lan" if str(listen) == "lan" else "local"
        self.app_settings_save(listen=listen)
        host = LISTEN_HOSTS[listen]
        if self.proxy is not None:
            r = self.proxy.relisten(host)
            if not r.get("ok"):
                # 代理没绑上就别把设置留着，否则 UI 显示"已对局域网"，实际没开
                self.app_settings_save(listen="local")
                return {**r, **self.network()}
        return {"ok": True, **self.network()}

    def restart_instances(self) -> dict:
        """按当前设置重启全部运行中实例（换监听地址后让它真生效）。"""
        before = [(i.model, dict(i.params)) for i in self.pool.instances()
                  if getattr(i, "state", "") in ("ready", "starting")]
        if not before:
            return {"ok": True, "restarted": [], "failed": []}
        self.pool.stop()
        self.monitor.reset()
        host = LISTEN_HOSTS.get(self.app_settings_get().get("listen") or "local", "127.0.0.1")
        ok, failed = [], []
        for model, params in before:
            params.pop("port", None)      # 重新分配端口，避开旧端口的 TIME_WAIT
            params["host"] = host
            r = self.pool.start(model, **params)
            (ok if r.get("ok") else failed).append(model)
        return {"ok": True, "restarted": ok, "failed": failed}

    def open_hf_cache(self) -> dict:
        import subprocess
        d = engine_mod.hf_cache_dir()
        if not os.path.isdir(d):
            return {"ok": False, "error": "缓存目录还不存在"}
        subprocess.run(["open", d], check=False, timeout=10, close_fds=False)  # posix_spawn，勿 fork
        return {"ok": True}

    def copy_text(self, text: str) -> dict:
        try:
            import subprocess
            p = subprocess.run(["pbcopy"], input=(text or "").encode(), timeout=5, close_fds=False)
            return {"ok": p.returncode == 0}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

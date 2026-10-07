"""TensorFold Manager v2 — 本地 TensorFold 推理引擎的 Mac 管理端。

双形态：主窗（NSWindow+WKWebView）+ 菜单栏（NSStatusItem）。
入口：python main.py（打包版由 .app launcher 以自包含运行时启动）。
"""
from __future__ import annotations

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 本机代理会劫持 127.0.0.1 与 HF/GitHub 流量，主进程层面先清掉（子进程再各自清）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

import AppKit  # noqa: E402
from AppKit import NSApplication, NSApplicationActivationPolicyRegular  # noqa: E402
from Foundation import NSObject, NSTimer  # noqa: E402

from backend.api import Api  # noqa: E402
from backend.chat import ChatProxy, ChatStore  # noqa: E402
from backend.download import DownloadManager  # noqa: E402
from backend.engine import EnginePool, ModelSettings, find_launcher  # noqa: E402
from backend.monitor import Monitor  # noqa: E402
from backend.shell import Shell  # noqa: E402
from backend.tray import Tray  # noqa: E402
from backend.update import UpdateChecker  # noqa: E402

try:
    import psutil
except ImportError:
    psutil = None

DATA_DIR = os.path.expanduser("~/.tensorfold-manager")
LAUNCHER = os.environ.get("TFM_CLI") or find_launcher(HERE)

POOL = EnginePool(python_bin=LAUNCHER, settings=ModelSettings(
    os.path.join(DATA_DIR, "model_settings.json")))
DOWNLOAD = DownloadManager(LAUNCHER) if LAUNCHER else None
MONITOR = Monitor()
UPDATER = UpdateChecker()
PROXY: ChatProxy | None = None
SHELL: Shell | None = None
TRAY: Tray | None = None
STOP = threading.Event()


def background_loop():
    """1Hz：健康探活 + 监控采样 + 每日更新检查（重活全在后台线程）。"""
    while not STOP.is_set():
        try:
            POOL.health_tick()
            MONITOR.tick(POOL, psutil)
            UPDATER.maybe_background(86400.0)
        except Exception as exc:
            POOL.log(f"后台循环异常: {exc}")
        STOP.wait(1.0)


class MainLoopTimer(NSObject):
    """主线程 2s 定时器：刷新菜单栏（AppKit 必须主线程）。"""

    def tick_(self, timer):
        try:
            if TRAY is not None:
                TRAY.refresh()
        except Exception as exc:
            print(f"[tray] refresh 异常: {exc}")


class AppDelegate(NSObject):
    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False  # 关主窗 = 隐藏，菜单栏常驻

    def applicationShouldTerminate_(self, sender):
        # 退出前优雅停掉全部引擎
        try:
            POOL.stop()
        except Exception:
            pass
        STOP.set()
        return AppKit.NSTerminateNow

    def applicationSupportsSecureRestorableState_(self, app):
        return True


def migrate_legacy_chat(store: ChatStore):
    """v1 单文件 history.json → archive/（清空重开）。"""
    legacy = os.path.expanduser("~/Library/Application Support/TensorFold Manager/history.json")
    if store.migrate_legacy(legacy, os.path.join(DATA_DIR, "archive")):
        POOL.log(f"已归档 v1 对话记录: {legacy}")


def main():
    global PROXY, SHELL, TRAY
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    os.makedirs(DATA_DIR, exist_ok=True)
    store = ChatStore(os.path.join(DATA_DIR, "chats"))
    migrate_legacy_chat(store)

    PROXY = ChatProxy(POOL)
    PROXY.start()
    api = Api(POOL, DOWNLOAD, MONITOR, PROXY, store, UPDATER)

    threading.Thread(target=background_loop, daemon=True, name="monitor-loop").start()

    SHELL = Shell(api, "TensorFold Manager")
    SHELL.on_loaded = build_tray
    SHELL.build(os.path.join(HERE, "ui", "index.html"))

    timer = MainLoopTimer.alloc().init()
    timer.refs = {}
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        2.0, timer, b"tick:", None, True)
    _keep = [timer]  # 保活

    app.activateIgnoringOtherApps_(True)
    app.run()


def build_tray():
    """主窗加载完成后挂菜单栏（壳先于托盘，菜单动作引用 shell）。"""
    global TRAY
    TRAY = Tray.alloc().init()
    TRAY.refs = {"pool": POOL, "monitor": MONITOR, "shell": SHELL,
                 "on_stop_all": lambda: (POOL.stop(), MONITOR.reset()),
                 "on_stop_model": lambda m: (POOL.stop(m), MONITOR.reset_model(m))}
    TRAY.build()
    globals()["_tray_keep"] = TRAY


if __name__ == "__main__":
    main()

"""C0 Spike（硬闸门）：pyobjc 原生壳最小可行性验证。

验证四件事，缺一条即判 FAIL、停下重议路线：
  1) NSApplication 起主窗（Regular 策略）
  2) WKWebView 加载本地 HTML 并渲染
  3) JS 桥双向闭环：JS postMessage → Python 收到 → Python evaluateJavaScript →
     JS 回调 → JS 再 postMessage 确认
  4) NSStatusItem 菜单栏图标出现

通过标准：控制台依次打出 SPIKE_WINDOW_OK / SPIKE_TRAY_OK / SPIKE_JS_TO_PY /
SPIKE_BRIDGE_ROUNDTRIP_OK / SPIKE_OK，exit 0；8 秒未闭环 → SPIKE_TIMEOUT exit 1。
"""
from __future__ import annotations

import sys

import AppKit
from AppKit import (NSApplication, NSStatusBar, NSVariableStatusItemLength,
                    NSWindow, NSMakeRect, NSApp, NSApplicationActivationPolicyRegular)
from Foundation import NSObject, NSTimer
from WebKit import WKWebView, WKWebViewConfiguration

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>spike</title>
<style>body{font:14px -apple-system;background:#1d1d20;color:#efefef;padding:2em}</style></head>
<body>
<h3 id="t">WKWebView spike</h3>
<script>
function send(kind, extra) {
  window.webkit.messageHandlers.bridge.postMessage(JSON.stringify(Object.assign({kind}, extra)));
}
window.onPythonReply = function (payload) {
  document.getElementById('t').textContent = 'python 说: ' + payload.hello;
  send('roundtrip-ok', {echo: payload.hello});
};
send('js-to-py', {msg: 'hello from webkit'});
</script>
</body></html>"""

_STATE = {"roundtrip": False, "app": None, "refs": []}


class Bridge(NSObject):
    """WKScriptMessageHandler：JS 侧 window.webkit.messageHandlers.bridge.postMessage(...)"""

    def userContentController_didReceiveScriptMessage_(self, ucc, message):
        try:
            import json
            body = json.loads(message.body())
        except Exception as exc:
            print(f"SPIKE_BAD_MSG {exc}")
            return
        kind = body.get("kind")
        if kind == "js-to-py":
            print(f"SPIKE_JS_TO_PY {body.get('msg')}")
            wv = _STATE["refs"][0]
            wv.evaluateJavaScript_completionHandler_(
                "window.onPythonReply({hello:'pong-from-python'})", None)
        elif kind == "roundtrip-ok":
            print(f"SPIKE_BRIDGE_ROUNDTRIP_OK echo={body.get('echo')}")
            _STATE["roundtrip"] = True
            # 停 1s 让人看到窗口内容，再收尾
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, Watchdog.alloc().init(), b"fireSuccess:", None, False)

    def retainForSpike(self):
        pass


class Watchdog(NSObject):
    """超时器：到点未闭环判失败；roundtrip 成功路径也走这里收尾。"""

    def fireTimeout_(self, timer):
        if _STATE["roundtrip"]:
            self.fireSuccess_(timer)
        else:
            print("SPIKE_TIMEOUT (桥未闭环)")
            import os
            os._exit(1)

    def fireSuccess_(self, timer):
        print("SPIKE_OK")
        _STATE["app"].terminate_(None)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    _STATE["app"] = app

    # --- 主窗 + WKWebView ---
    cfg = WKWebViewConfiguration.alloc().init()
    bridge = Bridge.alloc().init()
    cfg.userContentController().addScriptMessageHandler_name_(bridge, "bridge")
    frame = NSMakeRect(0, 0, 640, 420)
    style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
             | AppKit.NSWindowStyleMaskMiniaturizable | AppKit.NSWindowStyleMaskResizable)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(frame, style, 2, False)
    win.setTitle_("TensorFold Spike (C0)")
    webview = WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
    win.setContentView_(webview)
    webview.loadHTMLString_baseURL_(HTML, None)
    win.center()
    win.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)
    print("SPIKE_WINDOW_OK")

    # --- 菜单栏图标 ---
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    item.setTitle_("TF")
    print("SPIKE_TRAY_OK")

    _STATE["refs"] = [webview, win, item, bridge]  # 保活引用

    # --- 超时兜底（8s 未闭环 = FAIL） ---
    wd = Watchdog.alloc().init()
    _STATE["refs"].append(wd)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        8.0, wd, b"fireTimeout:", None, False)

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

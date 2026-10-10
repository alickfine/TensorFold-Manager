"""C1 主窗壳：NSWindow(1100×720) + WKWebView + JS 桥（WKScriptMessageHandler）。

JS 侧约定（DocumentStart 注入桥脚本，页面可用）：
    window.bridge.call('engine_start', {model: '...', ...}) → Promise<result>
    window.bridge.on('engine-status', fn)                    ← Python 推送事件
Python → JS 投递：evaluateJavaScript("window.bridge._resolve(<id>, <ok>, <json>)")

线程模型：
  - Api 方法可能慢（detect ~20s / update ~8s）→ worker 线程执行；
  - evaluateJavaScript 必须回主线程 → performSelectorOnMainThread 到 _ReplyTarget。

pyobjc 约束：NSObject 子类里每个方法都按选择器校验参数个数，因此 NSObject 子类
保持极薄（只放严格匹配选择器的方法），业务逻辑一律放模块函数或纯 Python 类。
关主窗 = 隐藏不退出（菜单栏可再唤出）。
"""
from __future__ import annotations

import json
import threading
import traceback

import AppKit
from AppKit import NSWindow, NSMakeRect
from Foundation import NSObject, NSURL
from WebKit import WKWebView, WKWebViewConfiguration, WKUserScript

BRIDGE_NAME = "bridge"

# DocumentStart 注入：window.bridge.call / on / _push
BRIDGE_JS = """
(() => {
  const pending = new Map();
  let seq = 0;
  window.bridge = window.bridge || {};
  window.bridge.call = function (method, args) {
    return new Promise((resolve, reject) => {
      const id = 'b' + (++seq);
      pending.set(id, {resolve, reject});
      try {
        window.webkit.messageHandlers.bridge.postMessage(
          JSON.stringify({id, method, args: args || {}}));
      } catch (e) {
        pending.delete(id);
        reject(String(e));
      }
      setTimeout(() => {
        if (pending.has(id)) { pending.delete(id); reject('bridge timeout: ' + method); }
      }, 120000);
    });
  };
  window.bridge._resolve = function (id, envelope) {
    const p = pending.get(id);
    if (!p) return;
    pending.delete(id);
    envelope.ok ? p.resolve(envelope.result) : p.reject(envelope.error);
  };
  window.bridge._handlers = window.bridge._handlers || {};
  window.bridge.on = function (evt, fn) { (window.bridge._handlers[evt] ||= []).push(fn); };
  window.bridge._push = function (evt, data) {
    (window.bridge._handlers[evt] || []).forEach(fn => { try { fn(data); } catch (e) { console.error(e); } });
  };
})();
"""


def _dispatch(api, reply_target, mid, method, args):
    """worker 线程：执行 Api 方法，结果（json 字符串）投回主线程。"""
    try:
        fn = getattr(api, method, None)
        if fn is None or method.startswith("_"):
            raise LookupError(f"unknown method: {method}")
        result = fn(**args) if isinstance(args, dict) else fn(args)
        payload = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
    except Exception as exc:
        traceback.print_exc()
        payload = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False)
    reply_target.performSelectorOnMainThread_withObject_waitUntilDone_(
        b"didBuildReply:", {"id": mid, "payload": payload}, False)


class _Bridge(NSObject):
    """WKScriptMessageHandler（薄壳）。refs: dict(api=..., reply=...)"""

    def userContentController_didReceiveScriptMessage_(self, ucc, message):
        try:
            msg = json.loads(message.body())
        except Exception as exc:
            print(f"[bridge] bad message: {exc}")
            return
        threading.Thread(
            target=_dispatch,
            args=(self.refs["api"], self.refs["reply"],
                  msg.get("id"), msg.get("method"), msg.get("args") or {}),
            daemon=True, name=f"bridge-{msg.get('method')}").start()


class _ReplyTarget(NSObject):
    """主线程投递器：把预序列化 payload 交给 webview 执行。"""

    def didBuildReply_(self, d):
        wv = self.refs["webview"]
        if wv is not None:
            wv.evaluateJavaScript_completionHandler_(
                f"window.bridge._resolve({json.dumps(d['id'])},{d['payload']})", None)


class _NavDelegate(NSObject):
    def webView_didFinishNavigation_(self, webview, navigation):
        h = self.refs.get("on_loaded")
        if h:
            try:
                h()
            except Exception:
                traceback.print_exc()

    def webView_didFailProvisionalNavigation_withError_(self, webview, navigation, error):
        print(f"[shell] 页面加载失败: {error.localizedDescription()}")


def _default_alert(message, info, style, buttons):
    """构造一个 NSAlert。**模块函数**：NSObject 子类里任何自定义方法都会被
    pyobjc 按选择器校验参数个数（`_panel` 带 4 参直接抛 BadPrototypeError，
    App 会在 import 阶段就起不来），所以面板构造一律留在类外。"""
    a = AppKit.NSAlert.alloc().init()
    a.setMessageText_(message or "")
    if info:
        a.setInformativeText_(info)
    a.setAlertStyle_(style)
    for b in buttons:
        a.addButtonWithTitle_(b)
    return a


# 面板工厂：模块级可替换（测试打桩用它，避免真的弹模态窗阻塞）
_alert = _default_alert


class _UIDelegate(NSObject):
    """WKWebView 的 alert / confirm / prompt 面板（原生 NSAlert）。

    不设 UI delegate 时 WebKit 走默认行为：confirm() 立刻返回 false、
    alert() 静默丢弃、prompt() 返回 null。裸 WKWebView 实测（2026-10-10）：
        confirm('x') -> 'false'   alert('x') -> 'undefined'   prompt('x','d') -> 'null'
    页面上 `if (!confirm(...)) return;` 于是**永远**走"用户取消"分支——
    按钮点了既不弹窗也不报错，看起来就是"按钮坏了"（升级引擎按钮即此因）。

    两条硬约束：
      1. 每个回调**必须**调用 completionHandler，否则该次 JS 调用永久挂起；
      2. WKWebView.uiDelegate 是 **weak** 引用，实例必须由 Shell 侧强引用持有
         （build() 里存进 self._refs）。
    """

    def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
            self, webview, message, frame, handler):
        try:
            _alert("TensorFold Manager", message,
                   AppKit.NSAlertStyleInformational, ["好"]).runModal()
        except Exception:
            traceback.print_exc()
        finally:
            handler()

    def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
            self, webview, message, frame, handler):
        ok = False
        try:
            a = _alert("TensorFold Manager", message,
                       AppKit.NSAlertStyleWarning, ["好", "取消"])
            ok = (a.runModal() == AppKit.NSAlertFirstButtonReturn)
        except Exception:
            traceback.print_exc()
        finally:
            handler(ok)

    def webView_runJavaScriptTextInputPanelWithPrompt_defaultText_initiatedByFrame_completionHandler_(
            self, webview, prompt, default_text, frame, handler):
        text = None
        try:
            a = _alert("TensorFold Manager", prompt,
                       AppKit.NSAlertStyleInformational, ["好", "取消"])
            field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 24))
            field.setStringValue_(default_text or "")
            a.setAccessoryView_(field)
            a.window().setInitialFirstResponder_(field)
            if a.runModal() == AppKit.NSAlertFirstButtonReturn:
                text = str(field.stringValue())
        except Exception:
            traceback.print_exc()
        finally:
            handler(text)


class Shell:
    """主窗装配（纯 Python；app.run() 前调用 build()）。"""

    def __init__(self, api, title="TensorFold Manager"):
        self.api = api
        self.title = title
        self.window = None
        self.webview = None
        self.on_loaded = None  # fn() 首次加载完成回调（菜单栏挂这）
        self._refs = {}

    def build(self, url: str):
        cfg = WKWebViewConfiguration.alloc().init()
        script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            BRIDGE_JS, 0, False)  # 0 = WKUserScriptInjectionTimeAtDocumentStart
        cfg.userContentController().addUserScript_(script)

        self._refs["webview"] = None  # 先占位，build 完成后填
        reply = _ReplyTarget.alloc().init()
        reply.refs = self._refs
        self._refs["api"] = self.api
        self._refs["reply"] = reply

        bridge = _Bridge.alloc().init()
        bridge.refs = self._refs
        cfg.userContentController().addScriptMessageHandler_name_(bridge, BRIDGE_NAME)

        frame = NSMakeRect(0, 0, 1100, 720)
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
                 | AppKit.NSWindowStyleMaskMiniaturizable | AppKit.NSWindowStyleMaskResizable)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, 2, False)
        self.window.setTitle_(self.title)
        self.window.setMinSize_(AppKit.NSMakeSize(900, 600))

        self.webview = WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
        self._refs["webview"] = self.webview
        self.window.setContentView_(self.webview)

        nav = _NavDelegate.alloc().init()
        nav.refs = {"shell": self}
        # on_loaded 回调经 dict 传递（build 后才设置，用 lambda 间接取）
        nav_on = {"get": lambda: self.on_loaded}

        class _Nav2(_NavDelegate):
            def webView_didFinishNavigation_(self2, webview2, navigation):
                fn = nav_on["get"]()
                if fn:
                    try:
                        fn()
                    except Exception:
                        traceback.print_exc()
        nav2 = _Nav2.alloc().init()
        self.webview.setNavigationDelegate_(nav2)
        # uiDelegate 是 weak 引用：实例必须由 _refs 强持有，否则被回收后
        # 又退化成「confirm() 恒返 false、alert() 静默丢弃」的 WebKit 默认行为。
        ui = _UIDelegate.alloc().init()
        self.webview.setUIDelegate_(ui)
        self._refs.update({"bridge": bridge, "reply": reply, "nav": nav2, "win": self.window, "ui": ui})

        nsurl = NSURL.fileURLWithPath_(url)
        self.webview.loadFileURL_allowingReadAccessToURL_(
            nsurl, nsurl.URLByDeletingLastPathComponent())
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        # 默认铺满工作区（非原生全屏：保留菜单栏/Dock；用户仍可缩放）
        screen = AppKit.NSScreen.mainScreen()
        if screen is not None:
            self.window.setFrame_display_(screen.visibleFrame(), True)
        return self

    # ---------- 动作 ----------
    def show_window(self):
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        if self.window:
            self.window.makeKeyAndOrderFront_(None)

    def toggle_window(self):
        if self.window and self.window.isVisible() and self.window.isKeyWindow():
            self.window.orderOut_(None)
        else:
            self.show_window()

    def evaluate(self, js: str):
        if self.webview:
            self.webview.evaluateJavaScript_completionHandler_(js, None)

    def push_event(self, name: str, data):
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = "null"
        self.evaluate(f"window.bridge._push({json.dumps(name)},{payload})")

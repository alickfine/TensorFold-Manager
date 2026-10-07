"""C2 菜单栏：NSStatusItem（文字标题含模型数/tok/s）+ NSMenu 动作表 + 实例列表。

pyobjc 命名铁律：NSObject 子类方法名中间不能带下划线（会映射成多冒号选择器）；
带参 ObjC 动作 = 驼峰 + 单尾下划线（openMain: 等）。
"""
from __future__ import annotations

import AppKit
from AppKit import NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem
import objc
from Foundation import NSObject


class Tray(NSObject):
    """NSStatusItem + 菜单。refs: dict(pool=, monitor=, shell=, on_stop_all=, on_stop_model=)。"""

    @objc.python_method
    def build(self):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.item.setTitle_("TF")
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        self.addEntry(menu, "打开 TensorFold Manager", self.openMain_, self, "o")
        menu.addItem_(NSMenuItem.separatorItem())
        self.modelsSection = self.addEntry(menu, "运行中的模型", None, None, "")
        self.modelsAnchor = menu.numberOfItems()
        menu.addItem_(NSMenuItem.separatorItem())
        self.addEntry(menu, "停止全部引擎", self.stopAll_, self, "s")
        menu.addItem_(NSMenuItem.separatorItem())
        self.addEntry(menu, "退出", self.quitApp_, self, "q")
        self.item.setMenu_(menu)
        self.modelItems = []
        self.refresh()
        return self

    @objc.python_method
    def addEntry(self, menu, title, action, target, key):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            it.setTarget_(target)
        menu.addItem_(it)
        return it

    # ---------- 动作 ----------
    def openMain_(self, sender):
        shell = self.refs.get("shell")
        if shell:
            shell.show_window()

    def stopAll_(self, sender):
        fn = self.refs.get("on_stop_all")
        if fn:
            fn()

    def quitApp_(self, sender):
        # AppDelegate.applicationShouldTerminate_ 会先优雅停引擎
        AppKit.NSApplication.sharedApplication().terminate_(None)

    def toggleModel_(self, sender):
        model = sender.representedObject()
        fn = self.refs.get("on_stop_model")
        if fn and model:
            fn(model)

    # ---------- 刷新（主线程定时器调用） ----------
    @objc.python_method
    def refresh(self):
        pool = self.refs.get("pool")
        mon = self.refs.get("monitor")
        if pool is None:
            return
        ready = pool.ready_instances()
        parts = ["TF"]
        if ready:
            parts.append(f"{len(ready)}·{ready[0].model.split('/')[-1][:14]}")
            tps = (mon.snapshot()["latest"].get("tps") if mon else None)
            if tps:
                parts.append(f"{tps:.0f}tok/s")
        elif pool.instances():
            parts.append("启动中")
        self.item.setTitle_(" ".join(parts))

        # 模型子菜单重建
        menu = self.item.menu()
        for it in self.modelItems:
            menu.removeItem_(it)
        self.modelItems = []
        idx = self.modelsAnchor
        for inst in pool.instances():
            label = f"{inst.name}  ({inst.state} :{inst.port})"
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, self.toggleModel_, "")
            it.setTarget_(self)
            it.setRepresentedObject_(inst.model)
            it.setEnabled_(inst.state in ("ready", "starting"))
            menu.insertItem_atIndex_(it, idx)
            self.modelItems.append(it)
            idx += 1
        self.modelsSection.setTitle_("运行中的模型" if pool.instances() else "无运行中的模型")

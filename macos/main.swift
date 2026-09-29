import Cocoa
import WebKit
import Security

final class ManagerApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var worker: Process?
    private var parentPipe: Pipe?
    private var port: Int?
    private var instance: String?
    private var token = ""
    private var nonce = UUID().uuidString
    private var stdoutBuffer = Data()
    private var stderrTail = ""
    private var quitting = false
    private var readyAccepted = false
    private var failed = false
    private let queue = DispatchQueue(label: "io.github.alickfine.tensorfold-manager.bootstrap")
    private let languagePreference = NativeLanguagePreference()

    private var localized: NativeCopy { NativeCopy(language: languagePreference.current) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMenus()
        let config = WKWebViewConfiguration()
        config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "bootstrap")
        config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "exportFile")
        config.userContentController.addScriptMessageHandler(self, contentWorld: .page, name: "language")
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 960),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "TensorFold Manager"
        window.minSize = NSSize(width: 1000, height: 700)
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        queue.async { self.launchManager() }
    }

    private func buildMenus() {
        let copy = localized
        let bar = NSMenu()
        let appMenu = NSMenu()
        let appItem = NSMenuItem()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: copy.aboutMenu, action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: copy.quitMenu, action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        bar.addItem(appItem)
        let edit = NSMenu(title: copy.editMenu)
        for (title, selector, key) in [(copy.undoMenu, "undo:", "z"), (copy.cutMenu, "cut:", "x"),
                                       (copy.copyMenu, "copy:", "c"), (copy.pasteMenu, "paste:", "v"),
                                       (copy.selectAllMenu, "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let editItem = NSMenuItem(title: copy.editMenu, action: nil, keyEquivalent: "")
        editItem.submenu = edit
        bar.addItem(editItem)
        NSApp.mainMenu = bar
    }

    private func launchManager() {
        do {
            guard let resources = Bundle.main.resourceURL else { throw failure(localized.resourceDirectoryMissing) }
            let contents = resources.deletingLastPathComponent()
            guard let provenance = try JSONSerialization.jsonObject(
                with: Data(contentsOf: resources.appendingPathComponent("provenance.json"))) as? [String: Any]
            else { throw failure(localized.invalidProvenance) }
            guard let fingerprint = provenance["runtime_fingerprint"] as? String,
                  fingerprint.count == 64, fingerprint.allSatisfy({ $0.isHexDigit }) else {
                throw failure(localized.invalidRuntimeFingerprint)
            }
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("TensorFold Manager", isDirectory: true)
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let runtimes = support.appendingPathComponent("runtimes", isDirectory: true)
            try FileManager.default.createDirectory(at: runtimes, withIntermediateDirectories: true)
            let runtime = runtimes.appendingPathComponent(fingerprint, isDirectory: true)
            if !FileManager.default.fileExists(atPath: runtime.appendingPathComponent("bin/python3").path) {
                let stage = runtimes.appendingPathComponent("staging-" + UUID().uuidString)
                try FileManager.default.copyItem(at: contents.appendingPathComponent("Frameworks/PythonRuntime.framework/Resources/runtime"), to: stage)
                try RuntimeIntegrity.sealDirectories(stage)
                do { try FileManager.default.moveItem(at: stage, to: runtime) }
                catch { try? FileManager.default.removeItem(at: stage); if !FileManager.default.fileExists(atPath: runtime.path) { throw error } }
            }
            do { try RuntimeIntegrity.verify(runtime, manifest: Data(contentsOf: resources.appendingPathComponent("runtime-manifest.json"))) }
            catch { throw failure(localized.runtimeIntegrityFailed) }
            var bytes = [UInt8](repeating: 0, count: 32)
            guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
                throw failure(localized.secureSessionFailed)
            }
            token = Data(bytes).base64EncodedString()
            let process = Process()
            let input = Pipe(), output = Pipe(), errors = Pipe()
            process.executableURL = runtime.appendingPathComponent("bin/python3")
            process.arguments = ["-I", "-B", resources.appendingPathComponent("sidecar-launch.py").path,
                                 "--data-dir", support.appendingPathComponent("data").path,
                                 "--web-dir", resources.appendingPathComponent("web").path, "--port", "0", "--parent-pipe"]
            process.currentDirectoryURL = support
            process.environment = ["HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": NSTemporaryDirectory(), "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1",
                "TFM_ADMIN_TOKEN": token, "TFM_BOOTSTRAP_NONCE": nonce,
                "TFM_RUNTIME_PYTHON": runtime.appendingPathComponent("bin/python3").path,
                "TFM_UV": contents.appendingPathComponent("Helpers/uv").path,
                "TFM_KEYCHAIN_HELPER": contents.appendingPathComponent("Helpers/CredentialStore").path,
                "TFM_APP_VERSION": provenance["app_version"] as? String ?? "0.1.0-alpha.3"]
            process.standardInput = input
            process.standardOutput = output
            process.standardError = errors
            parentPipe = input
            worker = process
            process.terminationHandler = { proc in
                DispatchQueue.main.async {
                    if !self.quitting { self.showFailure(self.localized.workerExited(status: proc.terminationStatus)) }
                }
            }
            output.fileHandleForReading.readabilityHandler = { handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                self.queue.async { self.consumeReady(bytes) }
            }
            errors.fileHandleForReading.readabilityHandler = { handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                self.queue.async {
                    let line = (String(data: bytes, encoding: .utf8) ?? "").replacingOccurrences(of: self.token, with: "[redacted]")
                    self.stderrTail = String((self.stderrTail + line).suffix(4000))
                }
            }
            try process.run()
            queue.asyncAfter(deadline: .now() + 30) {
                if !self.readyAccepted {
                    DispatchQueue.main.async { self.showFailure(self.localized.readinessTimeout) }
                    self.parentPipe?.fileHandleForWriting.closeFile()
                    process.terminate()
                }
            }
        } catch {
            let nsError = error as NSError
            let detail = nsError.domain == "TensorFoldManager" ? error.localizedDescription : localized.unexpectedStartupFailure(error.localizedDescription)
            DispatchQueue.main.async { self.showFailure(detail) }
        }
    }

    private func consumeReady(_ bytes: Data) {
        stdoutBuffer.append(bytes)
        guard stdoutBuffer.count <= 8192 else {
            DispatchQueue.main.async { self.showFailure(self.localized.handshakeTooLong) }; return
        }
        guard let index = stdoutBuffer.firstIndex(of: 10) else { return }
        let line = stdoutBuffer.subdata(in: 0..<index)
        stdoutBuffer.removeSubrange(0...index)
        guard !readyAccepted, let process = worker else {
            DispatchQueue.main.async { self.showFailure(self.localized.duplicateHandshake) }
            return
        }
        do {
            let value = try Handshake.parse(line, expectedPID: process.processIdentifier, nonce: nonce)
            readyAccepted = true
            var request = URLRequest(url: URL(string: "http://127.0.0.1:\(value.port)/api/state")!)
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            request.timeoutInterval = 10
            URLSession.shared.dataTask(with: request) { data, response, error in
                let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
                guard error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
                      object?["instance_id"] as? String == value.instance_id else {
                    DispatchQueue.main.async { self.showFailure(self.localized.identityValidationFailed) }; return
                }
                DispatchQueue.main.async {
                    self.port = value.port; self.instance = value.instance_id
                    self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(value.port)/")!))
                }
            }.resume()
        } catch { DispatchQueue.main.async { self.showFailure(self.localized.invalidHandshake) } }
    }

    private func failure(_ text: String) -> NSError {
        NSError(domain: "TensorFoldManager", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }

    private func showFailure(_ text: String) {
        guard !failed, !quitting else { return }
        failed = true
        let copy = localized
        let alert = NSAlert()
        alert.messageText = copy.startupFailureTitle
        alert.informativeText = text + "\n\n" + stderrTail
        alert.addButton(withTitle: copy.quitButton)
        alert.runModal()
        NSApp.terminate(nil)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let origin = message.frameInfo.securityOrigin
        guard NativeBridgeOrigin.permits(isMainFrame: message.frameInfo.isMainFrame,
                                         scheme: origin.protocol, host: origin.host, originPort: origin.port,
                                         managementPort: port, instanceReady: instance != nil, quitting: quitting)
        else { replyHandler(nil, "Unauthorized frame"); return }
        if message.name == "bootstrap" {
            replyHandler(["token": token, "instance_id": instance!, "language": languagePreference.current.rawValue], nil)
        } else if message.name == "language" {
            guard let language = try? NativeLanguageMessage.parse(message.body) else {
                replyHandler(nil, "Invalid language"); return
            }
            languagePreference.set(language)
            buildMenus()
            replyHandler(["language": language.rawValue], nil)
        } else if message.name == "exportFile" {
            guard let body = message.body as? [String: Any], let file = try? ExportDocument.parse(body) else {
                replyHandler(nil, "Invalid export request"); return
            }
            let panel = NSSavePanel()
            let copy = localized
            panel.title = copy.exportTitle
            panel.prompt = copy.saveButton
            panel.nameFieldStringValue = file.name
            panel.canCreateDirectories = true
            panel.beginSheetModal(for: window) { response in
                guard response == .OK, let url = panel.url else { replyHandler(["saved": false], nil); return }
                do { try file.bytes.write(to: url, options: .atomic); replyHandler(["saved": true], nil) }
                catch { replyHandler(nil, "Export write failed") }
            }
        } else { replyHandler(nil, "Unknown native operation") }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url, let allowedPort = port,
              navigationAction.targetFrame?.isMainFrame == true else { decisionHandler(.cancel); return }
        if Handshake.permits(url, port: allowedPort) { decisionHandler(.allow); return }
        if navigationAction.navigationType == .linkActivated, ["http", "https"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? { nil }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard frame.isMainFrame, let url = frame.request.url, let currentPort = port,
              Handshake.permits(url, port: currentPort) else { completionHandler(false); return }
        let copy = localized
        let alert = NSAlert()
        alert.messageText = copy.confirmTitle
        alert.informativeText = String(message.prefix(4000))
        alert.addButton(withTitle: copy.confirmButton)
        alert.addButton(withTitle: copy.cancelButton)
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !quitting else { return .terminateLater }
        quitting = true
        guard let process = worker, process.isRunning else { return .terminateNow }
        // The dedicated pipe is held by the App only. EOF also handles App crash / Force Quit.
        parentPipe?.fileHandleForWriting.closeFile()
        if let currentPort = port {
            var request = URLRequest(url: URL(string: "http://127.0.0.1:\(currentPort)/api/admin/shutdown")!)
            request.httpMethod = "POST"
            request.httpBody = Data(#"{"grace_seconds":120}"#.utf8)
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            URLSession.shared.dataTask(with: request).resume()
        }
        DispatchQueue.global().async {
            process.waitUntilExit()
            DispatchQueue.main.async { sender.reply(toApplicationShouldTerminate: true) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 125) { self.checkShutdown(process, sender: sender) }
        return .terminateLater
    }

    private func checkShutdown(_ process: Process, sender: NSApplication) {
        guard process.isRunning else { return }
        let copy = localized
        let alert = NSAlert()
        alert.messageText = copy.shutdownTimeoutTitle
        alert.informativeText = copy.shutdownTimeoutDetail
        alert.addButton(withTitle: copy.continueWaitingButton)
        alert.addButton(withTitle: copy.forceQuitButton)
        alert.beginSheetModal(for: window) { response in
            if response == .alertSecondButtonReturn, process.isRunning { kill(process.processIdentifier, SIGKILL) }
            else { DispatchQueue.main.asyncAfter(deadline: .now() + 30) { self.checkShutdown(process, sender: sender) } }
        }
    }
}

let application = NSApplication.shared
let delegate = ManagerApp()
application.delegate = delegate
application.run()

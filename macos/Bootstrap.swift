import Foundation
import CryptoKit

enum NativeLanguage: String, Equatable {
    case zhCN = "zh-CN"
    case english = "en"
}

struct NativeLanguagePreference {
    static let key = "TensorFoldManager.language"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var current: NativeLanguage {
        guard let value = defaults.string(forKey: Self.key), let language = NativeLanguage(rawValue: value) else {
            return .zhCN
        }
        return language
    }

    func set(_ language: NativeLanguage) {
        defaults.set(language.rawValue, forKey: Self.key)
    }
}

enum NativeLanguageMessage {
    static func parse(_ body: Any) throws -> NativeLanguage {
        guard let value = body as? String, let language = NativeLanguage(rawValue: value) else {
            throw NSError(domain: "TensorFoldManager.Language", code: 1)
        }
        return language
    }
}

enum NativeBridgeOrigin {
    static func permits(isMainFrame: Bool, scheme: String, host: String, originPort: Int,
                        managementPort: Int?, instanceReady: Bool, quitting: Bool) -> Bool {
        isMainFrame && scheme == "http" && host == "127.0.0.1" && originPort == managementPort &&
            instanceReady && !quitting
    }
}

struct NativeCopy {
    let language: NativeLanguage

    private func value(_ chinese: String, _ english: String) -> String {
        language == .zhCN ? chinese : english
    }

    var aboutMenu: String { value("关于 TensorFold Manager", "About TensorFold Manager") }
    var quitMenu: String { value("退出 TensorFold Manager", "Quit TensorFold Manager") }
    var editMenu: String { value("编辑", "Edit") }
    var undoMenu: String { value("撤销", "Undo") }
    var cutMenu: String { value("剪切", "Cut") }
    var copyMenu: String { value("复制", "Copy") }
    var pasteMenu: String { value("粘贴", "Paste") }
    var selectAllMenu: String { value("全选", "Select All") }

    var startupFailureTitle: String { value("TensorFold Manager 启动失败", "TensorFold Manager Failed to Start") }
    var quitButton: String { value("退出", "Quit") }
    var confirmTitle: String { value("确认操作", "Confirm Action") }
    var confirmButton: String { value("确认", "Confirm") }
    var cancelButton: String { value("取消", "Cancel") }
    var exportTitle: String { value("导出文件", "Export File") }
    var saveButton: String { value("存储", "Save") }
    var shutdownTimeoutTitle: String { value("服务尚未退出", "Service Has Not Quit") }
    var shutdownTimeoutDetail: String {
        value("已等待超过 120 秒。可以继续等待，或强制结束本 App 创建的管理进程；推理监督器会在连接断开后清理所属引擎。",
              "The service has taken more than 120 seconds to quit. You can keep waiting or force quit the management process created by this app. The inference supervisor will clean up its engines after the connection closes.")
    }
    var continueWaitingButton: String { value("继续等待", "Keep Waiting") }
    var forceQuitButton: String { value("强制退出", "Force Quit") }

    var resourceDirectoryMissing: String { value("App资源目录缺失", "App resources directory is missing") }
    var invalidProvenance: String { value("App 来源信息无效", "App provenance information is invalid") }
    var invalidRuntimeFingerprint: String { value("运行时指纹无效", "Runtime fingerprint is invalid") }
    var runtimeIntegrityFailed: String {
        value("运行时完整性验证失败。保留现有环境，请重新安装完整的 App 后重试。",
              "Runtime integrity verification failed. The existing environment was preserved. Reinstall the complete app and try again.")
    }
    var secureSessionFailed: String { value("无法创建安全管理会话", "Could not create a secure management session") }
    var readinessTimeout: String { value("管理服务30秒内未就绪", "Management service was not ready within 30 seconds") }
    var handshakeTooLong: String { value("管理服务握手长度异常", "Management service handshake is too long") }
    var invalidHandshake: String { value("管理服务启动握手无效", "Management service startup handshake is invalid") }
    var duplicateHandshake: String { value("重复或异常启动握手", "Duplicate or unexpected startup handshake") }
    var identityValidationFailed: String { value("管理服务身份校验失败", "Management service identity verification failed") }

    func unexpectedStartupFailure(_ detail: String) -> String {
        value("启动管理服务时发生错误：\(detail)", "An error occurred while starting the management service: \(detail)")
    }

    func workerExited(status: Int32) -> String {
        value("管理服务退出，代码 \(status)", "Management service exited with code \(status)")
    }
}

struct RuntimeIntegrity {
    static func sealDirectories(_ root: URL) throws {
        let fm = FileManager.default
        let walk = fm.enumerator(at: root, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey])!
        var directories = [root]
        for case let path as URL in walk {
            let values = try path.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            if values.isDirectory == true && values.isSymbolicLink != true { directories.append(path) }
        }
        for path in directories.reversed() {
            let attributes = try fm.attributesOfItem(atPath: path.path)
            let mode = (attributes[.posixPermissions] as! NSNumber).intValue
            try fm.setAttributes([.posixPermissions: mode & ~0o222], ofItemAtPath: path.path)
        }
    }
    static func verify(_ root: URL, manifest: Data) throws {
        let root = root.resolvingSymlinksInPath().standardizedFileURL
        guard let entries = try JSONSerialization.jsonObject(with: manifest) as? [String: [String: Any]] else {
            throw NSError(domain: "TensorFoldManager", code: 3)
        }
        let fm = FileManager.default
        for (name, record) in entries {
            guard !name.hasPrefix("/"), !name.split(separator: "/").contains("..") else { throw NSError(domain: "TensorFoldManager", code: 3) }
            let path = root.appendingPathComponent(name)
            if let target = record["link"] as? String {
                guard try fm.destinationOfSymbolicLink(atPath: path.path) == target,
                      path.resolvingSymlinksInPath().path.hasPrefix(root.path + "/") else { throw NSError(domain: "TensorFoldManager", code: 3) }
            } else {
                let attributes = try fm.attributesOfItem(atPath: path.path)
                guard attributes[.type] as? FileAttributeType == .typeRegular,
                      (attributes[.posixPermissions] as? NSNumber)?.intValue == (record["mode"] as? NSNumber)?.intValue else { throw NSError(domain: "TensorFoldManager", code: 31) }
                let file = try FileHandle(forReadingFrom: path)
                defer { try? file.close() }
                var digest = SHA256()
                while let bytes = try file.read(upToCount: 65536), !bytes.isEmpty { digest.update(data: bytes) }
                let hash = digest.finalize().map { String(format: "%02x", $0) }.joined()
                guard hash == record["sha256"] as? String else { throw NSError(domain: "TensorFoldManager", code: 32) }
            }
        }
        let walk = fm.enumerator(at: root, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey])!
        for case let path as URL in walk {
            let values = try path.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            if values.isDirectory != true || values.isSymbolicLink == true {
                let canonical = path.deletingLastPathComponent().resolvingSymlinksInPath().appendingPathComponent(path.lastPathComponent)
                let name = String(canonical.path.dropFirst(root.path.count + 1))
                guard entries[name] != nil else { throw NSError(domain: "TensorFoldManager", code: 33) }
            }
        }
    }
}

struct Handshake: Decodable {
    let `protocol`: Int
    let event: String
    let port: Int
    let pid: Int32
    let instance_id: String
    let bootstrap_nonce: String

    static func parse(_ bytes: Data, expectedPID: Int32, nonce: String) throws -> Handshake {
        let value = try JSONDecoder().decode(Handshake.self, from: bytes)
        guard value.protocol == 1, value.event == "ready", value.pid == expectedPID,
              value.bootstrap_nonce == nonce, (1...65535).contains(value.port),
              !value.instance_id.isEmpty, value.instance_id.count <= 100 else {
            throw NSError(domain: "TensorFoldManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid management startup handshake"])
        }
        return value
    }

    static func permits(_ url: URL, port: Int) -> Bool {
        url.scheme == "http" && url.host == "127.0.0.1" && url.port == port && url.user == nil && url.password == nil
    }
}

struct ExportDocument {
    let name: String
    let bytes: Data

    static func parse(_ value: [String: Any]) throws -> ExportDocument {
        guard let name = value["name"] as? String, let content = value["content"] as? String,
              !name.isEmpty, name.utf8.count <= 200, !name.hasPrefix("."),
              !name.contains("/"), !name.contains("\\"), !name.contains(".."),
              name.rangeOfCharacter(from: .controlCharacters) == nil,
              ["csv", "json", "txt", "md"].contains(URL(fileURLWithPath: name).pathExtension.lowercased()),
              content.utf8.count <= 10 * 1024 * 1024 else {
            throw NSError(domain: "TensorFoldManager", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid export document"])
        }
        return ExportDocument(name: name, bytes: Data(content.utf8))
    }
}

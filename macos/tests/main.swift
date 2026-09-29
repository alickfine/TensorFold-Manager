import Foundation
import CryptoKit
func XCTAssertThrowsError<T>(_ expression: @autoclosure () throws -> T) {
    do { _ = try expression(); fatalError("Expected thrown error") } catch {}
}
func XCTAssertEqual<T: Equatable>(_ left: T, _ right: T) { precondition(left == right) }
func XCTAssertTrue(_ value: Bool) { precondition(value) }
func XCTAssertFalse(_ value: Bool) { precondition(!value) }

final class BootstrapTests {
    func testRejectsForeignPID() throws {
        let line = Data(#"{"protocol":1,"event":"ready","port":45678,"pid":99,"instance_id":"instance","bootstrap_nonce":"nonce"}"#.utf8)
        XCTAssertThrowsError(try Handshake.parse(line, expectedPID: 100, nonce: "nonce"))
    }
    func testRejectsNonceAndInvalidPorts() throws {
        for port in [0, 70000] {
            let line = Data("{\"protocol\":1,\"event\":\"ready\",\"port\":\(port),\"pid\":100,\"instance_id\":\"instance\",\"bootstrap_nonce\":\"nonce\"}".utf8)
            XCTAssertThrowsError(try Handshake.parse(line, expectedPID: 100, nonce: "nonce"))
        }
        let line = Data(#"{"protocol":1,"event":"ready","port":45678,"pid":100,"instance_id":"instance","bootstrap_nonce":"bad"}"#.utf8)
        XCTAssertThrowsError(try Handshake.parse(line, expectedPID: 100, nonce: "nonce"))
    }
    func testAcceptsMatchingHandshake() throws {
        let line = Data(#"{"protocol":1,"event":"ready","port":45678,"pid":100,"instance_id":"instance","bootstrap_nonce":"nonce"}"#.utf8)
        let ready = try Handshake.parse(line, expectedPID: 100, nonce: "nonce")
        XCTAssertEqual(ready.port, 45678)
        XCTAssertEqual(ready.instance_id, "instance")
    }
    func testNavigationExactOrigin() {
        XCTAssertTrue(Handshake.permits(URL(string: "http://127.0.0.1:45678/chat")!, port: 45678))
        for url in ["http://127.0.0.1:45679/", "http://localhost:45678/", "https://127.0.0.1:45678/", "http://127.0.0.1:45678@evil.example/", "file:///tmp/local.html"] {
            XCTAssertFalse(Handshake.permits(URL(string: url)!, port: 45678))
        }
    }
    func testExportRejectsPathsAndUnsupportedTypes() throws {
        for name in ["../data.json", "a/b.csv", "a\\b.csv", "program.sh", "nul\0.csv", ".hidden.json"] {
            XCTAssertThrowsError(try ExportDocument.parse(["name": name, "content": "text"]))
        }
        XCTAssertThrowsError(try ExportDocument.parse(["name": "safe.csv", "content": String(repeating: "x", count: 10 * 1024 * 1024 + 1)]))
        let file = try ExportDocument.parse(["name": "usage.csv", "content": "model,tokens\nqwen,42"])
        XCTAssertEqual(file.name, "usage.csv")
        XCTAssertEqual(String(data: file.bytes, encoding: .utf8), "model,tokens\nqwen,42")
    }
    func testLanguagePreferenceDefaultsToChineseAndPersistsStrictEnum() throws {
        let suiteName = "TensorFoldManagerNativeTests-" + UUID().uuidString
        guard let defaults = UserDefaults(suiteName: suiteName) else { fatalError("Could not create test defaults") }
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let preference = NativeLanguagePreference(defaults: defaults)
        XCTAssertEqual(preference.current, .zhCN)
        preference.set(.english)
        XCTAssertEqual(preference.current, .english)
        XCTAssertEqual(defaults.string(forKey: NativeLanguagePreference.key), "en")
        defaults.set("fr", forKey: NativeLanguagePreference.key)
        XCTAssertEqual(preference.current, .zhCN)
    }
    func testLanguageBridgeAcceptsOnlyExactEnums() throws {
        XCTAssertEqual(try NativeLanguageMessage.parse("zh-CN"), .zhCN)
        XCTAssertEqual(try NativeLanguageMessage.parse("en"), .english)
        for body: Any in ["zh", "en-US", "EN", " zh-CN", 1, ["language": "en"]] {
            XCTAssertThrowsError(try NativeLanguageMessage.parse(body))
        }
    }
    func testNativeBridgeRequiresMainFrameAndExactManagementOrigin() {
        XCTAssertTrue(NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "127.0.0.1", originPort: 45678,
                                                 managementPort: 45678, instanceReady: true, quitting: false))
        let rejected = [
            NativeBridgeOrigin.permits(isMainFrame: false, scheme: "http", host: "127.0.0.1", originPort: 45678, managementPort: 45678, instanceReady: true, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "https", host: "127.0.0.1", originPort: 45678, managementPort: 45678, instanceReady: true, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "localhost", originPort: 45678, managementPort: 45678, instanceReady: true, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "127.0.0.1", originPort: 45679, managementPort: 45678, instanceReady: true, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "127.0.0.1", originPort: 45678, managementPort: nil, instanceReady: true, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "127.0.0.1", originPort: 45678, managementPort: 45678, instanceReady: false, quitting: false),
            NativeBridgeOrigin.permits(isMainFrame: true, scheme: "http", host: "127.0.0.1", originPort: 45678, managementPort: 45678, instanceReady: true, quitting: true),
        ]
        rejected.forEach { XCTAssertFalse($0) }
    }
    func testNativeCopyCoversChineseDefaultAndEnglishDialogs() {
        let zh = NativeCopy(language: .zhCN)
        XCTAssertEqual(zh.editMenu, "编辑")
        XCTAssertEqual(zh.startupFailureTitle, "TensorFold Manager 启动失败")
        XCTAssertEqual(zh.confirmTitle, "确认操作")
        XCTAssertEqual(zh.shutdownTimeoutTitle, "服务尚未退出")
        XCTAssertEqual(zh.quitButton, "退出")
        XCTAssertEqual(zh.resourceDirectoryMissing, "App资源目录缺失")
        XCTAssertEqual(zh.readinessTimeout, "管理服务30秒内未就绪")
        XCTAssertEqual(zh.unexpectedStartupFailure("disk error"), "启动管理服务时发生错误：disk error")
        let en = NativeCopy(language: .english)
        XCTAssertEqual(en.editMenu, "Edit")
        XCTAssertEqual(en.startupFailureTitle, "TensorFold Manager Failed to Start")
        XCTAssertEqual(en.confirmTitle, "Confirm Action")
        XCTAssertEqual(en.shutdownTimeoutTitle, "Service Has Not Quit")
        XCTAssertEqual(en.quitButton, "Quit")
        XCTAssertEqual(en.resourceDirectoryMissing, "App resources directory is missing")
        XCTAssertEqual(en.unexpectedStartupFailure("disk error"), "An error occurred while starting the management service: disk error")
        XCTAssertEqual(en.workerExited(status: 9), "Management service exited with code 9")
    }
    static var allTests = [("testRejectsForeignPID", testRejectsForeignPID), ("testRejectsNonceAndInvalidPorts", testRejectsNonceAndInvalidPorts), ("testAcceptsMatchingHandshake", testAcceptsMatchingHandshake), ("testNavigationExactOrigin", testNavigationExactOrigin)]
}
let suite = BootstrapTests()
try suite.testRejectsForeignPID()
try suite.testRejectsNonceAndInvalidPorts()
try suite.testAcceptsMatchingHandshake()
suite.testNavigationExactOrigin()
try suite.testExportRejectsPathsAndUnsupportedTypes()
try suite.testLanguagePreferenceDefaultsToChineseAndPersistsStrictEnum()
try suite.testLanguageBridgeAcceptsOnlyExactEnums()
suite.testNativeBridgeRequiresMainFrameAndExactManagementOrigin()
suite.testNativeCopyCoversChineseDefaultAndEnglishDialogs()
print("PASS: 9 native bootstrap, origin, export and bilingual language checks")
let credential = try CredentialRequest.parse(Data(#"{"operation":"set","provider":"hf-upload","token":"fixture-secret"}"#.utf8))
XCTAssertEqual(credential.provider, "hf-upload")
for input in [#"{"operation":"get","provider":"existing-omlx"}"#, #"{"operation":"status","provider":"hf-upload","token":"secret"}"#, #"{"operation":"set","provider":"hf-upload","token":""}"#] {
    XCTAssertThrowsError(try CredentialRequest.parse(Data(input.utf8)))
}
let fixtureRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at: fixtureRoot, withIntermediateDirectories: true)
defer { try? FileManager.default.removeItem(at: fixtureRoot) }
let data = Data("stdlib fixture".utf8)
let path = fixtureRoot.appendingPathComponent("library.py")
try data.write(to: path)
try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: path.path)
let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
let manifest = try JSONSerialization.data(withJSONObject: ["library.py": ["sha256": digest, "mode": 420]])
try RuntimeIntegrity.verify(fixtureRoot, manifest: manifest)
try Data("changed".utf8).write(to: path)
XCTAssertThrowsError(try RuntimeIntegrity.verify(fixtureRoot, manifest: manifest))
try data.write(to: path)
try data.write(to: fixtureRoot.appendingPathComponent("unlisted.py"))
XCTAssertThrowsError(try RuntimeIntegrity.verify(fixtureRoot, manifest: manifest))
print("PASS: credential scope and full runtime integrity checks")

let sealedRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
let sealedChild = sealedRoot.appendingPathComponent("lib")
try FileManager.default.createDirectory(at: sealedChild, withIntermediateDirectories: true)
let sealedFile = sealedChild.appendingPathComponent("library.py")
try data.write(to: sealedFile)
try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: sealedFile.path)
try RuntimeIntegrity.sealDirectories(sealedRoot)
for directory in [sealedRoot, sealedChild] {
    let mode = (try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions] as! NSNumber).intValue
    XCTAssertEqual(mode & 0o222, 0)
}
XCTAssertThrowsError(try FileManager.default.createDirectory(at: sealedChild.appendingPathComponent("__pycache__"), withIntermediateDirectories: false))
let sealedManifest = try JSONSerialization.data(withJSONObject: ["lib/library.py": ["sha256": digest, "mode": 420]])
try RuntimeIntegrity.verify(sealedRoot, manifest: sealedManifest)
for directory in [sealedRoot, sealedChild] { try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path) }
try FileManager.default.removeItem(at: sealedRoot)
print("PASS: runtime directories reject bytecode cache writes without weakening manifest verification")

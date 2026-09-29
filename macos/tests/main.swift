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
    static var allTests = [("testRejectsForeignPID", testRejectsForeignPID), ("testRejectsNonceAndInvalidPorts", testRejectsNonceAndInvalidPorts), ("testAcceptsMatchingHandshake", testAcceptsMatchingHandshake), ("testNavigationExactOrigin", testNavigationExactOrigin)]
}
let suite = BootstrapTests()
try suite.testRejectsForeignPID()
try suite.testRejectsNonceAndInvalidPorts()
try suite.testAcceptsMatchingHandshake()
suite.testNavigationExactOrigin()
try suite.testExportRejectsPathsAndUnsupportedTypes()
print("PASS: 5 native bootstrap, exact-origin and export checks")
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

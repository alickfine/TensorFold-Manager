import Foundation
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
    static var allTests = [("testRejectsForeignPID", testRejectsForeignPID), ("testRejectsNonceAndInvalidPorts", testRejectsNonceAndInvalidPorts), ("testAcceptsMatchingHandshake", testAcceptsMatchingHandshake), ("testNavigationExactOrigin", testNavigationExactOrigin)]
}
let suite = BootstrapTests()
try suite.testRejectsForeignPID()
try suite.testRejectsNonceAndInvalidPorts()
try suite.testAcceptsMatchingHandshake()
suite.testNavigationExactOrigin()
print("PASS: 4 native bootstrap and exact-origin checks")

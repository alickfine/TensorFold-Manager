import Foundation

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

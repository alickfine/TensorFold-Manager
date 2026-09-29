import Foundation
import CryptoKit

struct RuntimeIntegrity {
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

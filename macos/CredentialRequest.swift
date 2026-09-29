import Foundation

struct CredentialRequest {
    let operation: String
    let provider: String
    let token: String?
    static func parse(_ bytes: Data) throws -> CredentialRequest {
        guard bytes.count <= 16384,
              let object = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              Set(object.keys).isSubset(of: ["operation", "provider", "token"]),
              let operation = object["operation"] as? String,
              ["get", "set", "status", "delete"].contains(operation),
              let provider = object["provider"] as? String,
              ["hf-download", "hf-upload", "modelscope-download"].contains(provider) else { throw NSError(domain: "CredentialRequest", code: 1) }
        let token = object["token"] as? String
        if operation == "set" {
            guard let token = token, !token.isEmpty, token.utf8.count <= 8192,
                  token.rangeOfCharacter(from: .controlCharacters) == nil else { throw NSError(domain: "CredentialRequest", code: 1) }
        } else if object["token"] != nil { throw NSError(domain: "CredentialRequest", code: 1) }
        return CredentialRequest(operation: operation, provider: provider, token: token)
    }
}

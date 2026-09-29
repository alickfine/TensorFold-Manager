import Foundation
import Security

func emit(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
}

do {
    // A fixed service and account allow-list keep this helper separate from all
    // existing oMLX, Hugging Face and ModelScope credentials.
    var input = Data()
    while let bytes = try FileHandle.standardInput.read(upToCount: min(4096, 16385 - input.count)), !bytes.isEmpty {
        input.append(bytes)
        if input.count > 16384 { break }
    }
    let request = try CredentialRequest.parse(input)
    let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "io.github.alickfine.tensorfold-manager.providers",
        kSecAttrAccount as String: request.provider,
        kSecAttrSynchronizable as String: false]
    var status: OSStatus = errSecSuccess
    switch request.operation {
    case "set":
        let attributes: [String: Any] = [kSecValueData as String: Data(request.token!.utf8)]
        status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd((query.merging(attributes) { _, new in new }.merging(
                [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]) { _, new in new }) as CFDictionary, nil)
        }
        if status == errSecSuccess { emit(["configured": true]) }
    case "delete":
        status = SecItemDelete(query as CFDictionary)
        if status == errSecItemNotFound { status = errSecSuccess }
        if status == errSecSuccess { emit(["configured": false]) }
    case "status":
        // Attributes only; this operation never asks Keychain for secret data.
        let lookup = query.merging([kSecReturnAttributes as String: true, kSecMatchLimit as String: kSecMatchLimitOne]) { _, new in new }
        status = SecItemCopyMatching(lookup as CFDictionary, nil)
        if status == errSecSuccess || status == errSecItemNotFound {
            emit(["configured": status == errSecSuccess]); status = errSecSuccess
        }
    default:
        var result: CFTypeRef?
        let lookup = query.merging([kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]) { _, new in new }
        status = SecItemCopyMatching(lookup as CFDictionary, &result)
        if status == errSecItemNotFound { emit(["configured": false]); status = errSecSuccess }
        else if status == errSecSuccess, let bytes = result as? Data, let secret = String(data: bytes, encoding: .utf8) {
            emit(["configured": true, "token": secret])
        } else if status == errSecSuccess { status = errSecDecode }
    }
    if status != errSecSuccess { emit(["error": "keychain_failed", "status": Int(status)]); exit(1) }
} catch { emit(["error": "invalid_request"]); exit(1) }

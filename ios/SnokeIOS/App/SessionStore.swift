import Combine
import Foundation

@MainActor
final class SessionStore: ObservableObject {
    @Published private(set) var token: String?
    @Published private(set) var deviceID: String?

    private let tokenKey = "snoke.auth.token"
    private let deviceIDKey = "snoke.device.id"

    init() {
        self.token = UserDefaults.standard.string(forKey: tokenKey)
        self.deviceID = UserDefaults.standard.string(forKey: deviceIDKey)
    }

    var isAuthenticated: Bool {
        guard let token, !token.isEmpty else {
            return false
        }
        return true
    }

    func ensureDeviceID() -> String {
        if let existing = deviceID, !existing.isEmpty {
            return existing
        }
        let generated = UUID().uuidString.lowercased()
        deviceID = generated
        UserDefaults.standard.set(generated, forKey: deviceIDKey)
        return generated
    }

    func save(token: String) {
        self.token = token
        UserDefaults.standard.set(token, forKey: tokenKey)
    }

    func logout() {
        token = nil
        UserDefaults.standard.removeObject(forKey: tokenKey)
    }
}

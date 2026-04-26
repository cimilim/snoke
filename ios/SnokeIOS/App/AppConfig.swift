import Combine
import Foundation

@MainActor
final class AppConfig: ObservableObject {
    static let backendURLKey = "snoke.backend.url"
    static let defaultBackendURL = "https://api.odali.al"

    @Published private(set) var backendURL: String

    init() {
        let saved = UserDefaults.standard.string(forKey: Self.backendURLKey)
        let value = (saved?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false)
            ? saved!
            : Self.defaultBackendURL
        self.backendURL = value
    }

    func setBackendURL(_ newValue: String) {
        let cleaned = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        backendURL = cleaned
        UserDefaults.standard.set(cleaned, forKey: Self.backendURLKey)
    }

    static func currentBackendURL() -> String {
        let saved = UserDefaults.standard.string(forKey: backendURLKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let saved, !saved.isEmpty {
            return saved
        }
        return defaultBackendURL
    }
}

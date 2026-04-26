import SwiftUI

struct SnokeApp: App {
    @StateObject private var session = SessionStore()
    @StateObject private var config = AppConfig()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(session)
                .environmentObject(config)
        }
    }
}

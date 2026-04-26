import SwiftUI

struct RootView: View {
    @EnvironmentObject private var session: SessionStore

    var body: some View {
        NavigationStack {
            if session.isAuthenticated {
                MainTabView()
            } else {
                OnboardingView()
            }
        }
    }
}

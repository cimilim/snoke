//
//  snokeIOSApp.swift
//  snokeIOS
//
//  Created by limqe on 23.04.26.
//

import SwiftUI

@main
struct snokeIOSApp: App {
    @StateObject private var session = SessionStore()
    @StateObject private var config = AppConfig()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(session)
                .environmentObject(config)
        }
    }
}

//
//  ContentView.swift
//  snokeIOS
//
//  Created by limqe on 23.04.26.
//

import SwiftUI

struct ContentView: View {
    var body: some View {
        RootView()
    }
}

#Preview {
    ContentView()
        .environmentObject(SessionStore())
        .environmentObject(AppConfig())
}

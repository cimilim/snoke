import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var viewModel = DashboardViewModel()
    @State private var showCravingSheet = false
    @State private var cravingIntensity = 7.0
    @State private var cravingResisted = true

    var body: some View {
        List {
            if viewModel.summary == nil && viewModel.probability == nil && viewModel.recommendation == nil && !viewModel.isLoading {
                Section("Welcome") {
                    Text("No synced data yet. Pull to refresh or log your first event.")
                        .foregroundStyle(.secondary)
                }
            }

            if let today = viewModel.summary?.today {
                Section("Today") {
                    metricRow("Cigarettes", "\(today.cigarettes)")
                    metricRow("Cravings", "\(today.cravings)")
                    metricRow("Resisted", "\(today.cravingsResisted)")
                }
            }

            if let probability = viewModel.probability {
                Section("Risk") {
                    metricRow("Current craving risk", percent(probability.pNow), tint: riskColor(probability.pNow))
                    metricRow("Next hour risk", percent(probability.pNextHour), tint: riskColor(probability.pNextHour))
                    metricRow("Confidence", probability.confidenceLevel)
                    if let peak = probability.nextPeakAt {
                        metricRow("Next peak", peak)
                    }
                }
            }

            if let rec = viewModel.recommendation {
                Section("Plan") {
                    metricRow("Target today", "\(rec.weaning.targetToday)")
                    metricRow("Smoked today", "\(rec.weaning.smokedToday)")
                    metricRow("Remaining", "\(rec.weaning.remaining)")
                    metricRow("State", rec.weaning.state)
                }

                if let nudge = rec.nudge {
                    Section("Recommended nudge") {
                        Text(nudge.title).font(.headline)
                        Text(nudge.body)
                    }
                }
            }

            Section("Actions") {
                Button("Log cigarette") {
                    Task { await withToken { token in await viewModel.logCigarette(token: token) } }
                }
                .disabled(viewModel.isSubmittingEvent)

                Button("Log craving") {
                    showCravingSheet = true
                }
                .disabled(viewModel.isSubmittingEvent)
            }

            if let error = viewModel.errorMessage {
                Section {
                    Text(error)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Snoke")
        .toolbar {
            ToolbarItemGroup(placement: .automatic) {
                Button("Refresh") {
                    Task { await load() }
                }
                Button("Logout") {
                    session.logout()
                }
            }
        }
        .task {
            await load()
        }
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
        .sheet(isPresented: $showCravingSheet) {
            NavigationStack {
                Form {
                    Section("Craving details") {
                        VStack(alignment: .leading) {
                            HStack {
                                Text("Intensity")
                                Spacer()
                                Text("\(Int(cravingIntensity)) / 10")
                                    .foregroundStyle(.secondary)
                            }
                            Slider(value: $cravingIntensity, in: 1...10, step: 1)
                        }
                        Toggle("I resisted this craving", isOn: $cravingResisted)
                    }
                }
                .navigationTitle("Log Craving")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { showCravingSheet = false }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Save") {
                            Task {
                                await withToken { token in
                                    await viewModel.logCraving(
                                        token: token,
                                        intensity: Int(cravingIntensity),
                                        resisted: cravingResisted
                                    )
                                }
                                showCravingSheet = false
                            }
                        }
                        .disabled(viewModel.isSubmittingEvent)
                    }
                }
            }
        }
    }

    private func load() async {
        await withToken { token in
            await viewModel.refresh(token: token)
        }
    }

    private func withToken(_ action: (String) async -> Void) async {
        guard let token = session.token else {
            viewModel.errorMessage = APIError.missingToken.localizedDescription
            return
        }
        await action(token)
    }

    private func metricRow(_ label: String, _ value: String, tint: Color = .secondary) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text(value).foregroundStyle(tint)
        }
    }

    private func percent(_ value: Double) -> String {
        let p = Int((value * 100.0).rounded())
        return "\(p)%"
    }

    private func riskColor(_ value: Double) -> Color {
        switch value {
        case ..<0.30:
            return .green
        case ..<0.60:
            return .orange
        default:
            return .red
        }
    }
}

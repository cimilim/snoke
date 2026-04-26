import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var viewModel = OnboardingViewModel()

    var body: some View {
        Form {
            Section("Basics") {
                TextField("Baseline cigarettes/day (optional)", text: $viewModel.baselineCigarettesPerDay)
                TextField("Weaning rate %", text: $viewModel.weaningRatePct)
                TextField("Age", text: $viewModel.ageYears)
            }

            Section("Body") {
                TextField("Weight kg", text: $viewModel.weightKg)
                TextField("Height cm", text: $viewModel.heightCm)
                TextField("Body fat (0.05 - 0.60)", text: $viewModel.bodyFat)
                TextField("Weekly weight loss kg", text: $viewModel.weeklyWeightLossKg)
            }

            if let error = viewModel.errorMessage {
                Section {
                    Text(error)
                        .foregroundStyle(.red)
                }
            }

            Section {
                Button {
                    Task { await viewModel.register(session: session) }
                } label: {
                    if viewModel.isSubmitting {
                        ProgressView()
                    } else {
                        Text("Create account")
                    }
                }
                .disabled(viewModel.isSubmitting)
            }
        }
        .navigationTitle("Snoke Setup")
    }
}

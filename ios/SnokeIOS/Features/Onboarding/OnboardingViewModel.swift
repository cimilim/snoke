import Combine
import Foundation

@MainActor
final class OnboardingViewModel: ObservableObject {
    @Published var baselineCigarettesPerDay = ""
    @Published var weaningRatePct = "5"
    @Published var ageYears = "30"
    @Published var weightKg = "75"
    @Published var heightCm = "175"
    @Published var bodyFat = "0.20"
    @Published var weeklyWeightLossKg = "0.40"
    @Published var isSubmitting = false
    @Published var errorMessage: String?

    private let api = SnokeAPI()

    func register(session: SessionStore) async {
        errorMessage = nil
        isSubmitting = true
        defer { isSubmitting = false }

        let deviceID = session.ensureDeviceID()
        let payload = RegisterRequest(
            deviceID: deviceID,
            baselineCigarettesPerDay: Int(baselineCigarettesPerDay),
            weaningRatePct: Int(weaningRatePct) ?? 5,
            weightKg: Double(weightKg) ?? 75,
            heightCm: Double(heightCm) ?? 175,
            bodyFat: Double(bodyFat) ?? 0.20,
            ageYears: Int(ageYears) ?? 30,
            weeklyWeightLossKg: Double(weeklyWeightLossKg) ?? 0.40
        )

        do {
            let token = try await api.register(payload)
            session.save(token: token.accessToken)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

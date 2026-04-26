import Combine
import Foundation

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var summary: SummaryResponse?
    @Published var probability: ProbabilityResponse?
    @Published var recommendation: RecommendationResponse?
    @Published var isLoading = false
    @Published var isSubmittingEvent = false
    @Published var errorMessage: String?

    private let api = SnokeAPI()
    private let cache = CacheStore()
    private let summaryKey = "snoke.cache.summary"
    private let probabilityKey = "snoke.cache.probability"
    private let recommendationKey = "snoke.cache.recommendation"

    func refresh(token: String) async {
        errorMessage = nil
        isLoading = true
        defer { isLoading = false }

        async let summaryResult = api.fetchSummary(token: token)
        async let probabilityResult = api.fetchProbability(token: token)
        async let recommendationResult = api.fetchRecommendation(token: token)

        do {
            let loadedSummary = try await summaryResult
            let loadedProbability = try await probabilityResult
            let loadedRecommendation = try await recommendationResult

            summary = loadedSummary
            probability = loadedProbability
            recommendation = loadedRecommendation

            cache.save(loadedSummary, key: summaryKey)
            cache.save(loadedProbability, key: probabilityKey)
            cache.save(loadedRecommendation, key: recommendationKey)
        } catch {
            let cachedSummary = cache.load(SummaryResponse.self, key: summaryKey)
            let cachedProbability = cache.load(ProbabilityResponse.self, key: probabilityKey)
            let cachedRecommendation = cache.load(RecommendationResponse.self, key: recommendationKey)

            if cachedSummary != nil || cachedProbability != nil || cachedRecommendation != nil {
                summary = cachedSummary
                probability = cachedProbability
                recommendation = cachedRecommendation
                errorMessage = "Offline mode: showing last synced data."
            } else {
                errorMessage = error.localizedDescription
            }
        }
    }

    func logCigarette(token: String) async {
        await sendSingleEvent(
            token: token,
            kind: "cigarette",
            payload: ["trigger": .string("manual_ios")]
        )
    }

    func logCraving(token: String, intensity: Int, resisted: Bool) async {
        await sendSingleEvent(
            token: token,
            kind: "craving",
            payload: [
                "intensity": .int(intensity),
                "resisted": .bool(resisted),
                "trigger": .string("manual_ios")
            ]
        )
    }

    private func sendSingleEvent(token: String, kind: String, payload: [String: EventPayload]) async {
        errorMessage = nil
        isSubmittingEvent = true
        defer { isSubmittingEvent = false }

        let event = EventRequest(
            clientUUID: UUID().uuidString.lowercased(),
            kind: kind,
            occurredAt: ISO8601.withFractionalSeconds.string(from: Date()),
            payload: payload
        )

        do {
            try await api.sendEvents(token: token, events: [event])
            await refresh(token: token)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

import Combine
import Foundation

@MainActor
final class HistoryViewModel: ObservableObject {
    @Published var summary: SummaryResponse?
    @Published var chartPoints: [HistoryChartPoint] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api = SnokeAPI()
    private let cache = CacheStore()
    private let summaryKey = "snoke.cache.summary"

    func load(token: String) async {
        errorMessage = nil
        isLoading = true
        defer { isLoading = false }

        do {
            let latest = try await api.fetchSummary(token: token)
            summary = latest
            cache.save(latest, key: summaryKey)
            rebuildChart()
        } catch {
            if let cached = cache.load(SummaryResponse.self, key: summaryKey) {
                summary = cached
                rebuildChart()
                errorMessage = "Offline mode: showing last synced data."
            } else {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func rebuildChart() {
        guard let summary else {
            chartPoints = []
            return
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone(secondsFromGMT: 0)

        chartPoints = summary.last7Days.compactMap { day in
            guard let date = formatter.date(from: day.day) else { return nil }
            return HistoryChartPoint(
                dayLabel: day.day,
                date: date,
                cigarettes: day.cigarettes,
                cravings: day.cravings
            )
        }
        .sorted { $0.date < $1.date }
    }
}

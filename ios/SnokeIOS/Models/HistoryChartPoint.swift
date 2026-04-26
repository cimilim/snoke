import Foundation

struct HistoryChartPoint: Identifiable {
    let dayLabel: String
    let date: Date
    let cigarettes: Int
    let cravings: Int

    var id: String { dayLabel }
}

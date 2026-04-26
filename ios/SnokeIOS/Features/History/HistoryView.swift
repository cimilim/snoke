import SwiftUI
import Charts

struct HistoryView: View {
    @EnvironmentObject private var session: SessionStore
    @StateObject private var viewModel = HistoryViewModel()

    var body: some View {
        NavigationStack {
            List {
                if viewModel.summary == nil && !viewModel.isLoading {
                    Section("History") {
                        Text("No historical entries yet. Log events from Dashboard to populate this view.")
                            .foregroundStyle(.secondary)
                    }
                }

                if let summary = viewModel.summary {
                    Section("Cigarettes trend") {
                        if viewModel.chartPoints.isEmpty {
                            Text("No chart data available yet.")
                                .foregroundStyle(.secondary)
                        } else {
                            Chart(viewModel.chartPoints) { point in
                                LineMark(
                                    x: .value("Day", point.date),
                                    y: .value("Cigarettes", point.cigarettes)
                                )
                                .interpolationMethod(.catmullRom)
                                .foregroundStyle(.blue)

                                PointMark(
                                    x: .value("Day", point.date),
                                    y: .value("Cigarettes", point.cigarettes)
                                )
                                .foregroundStyle(.blue)
                            }
                            .chartYAxis {
                                AxisMarks(position: .leading)
                            }
                            .chartXAxis {
                                AxisMarks(values: .stride(by: .day)) {
                                    AxisGridLine()
                                    AxisTick()
                                    AxisValueLabel(format: .dateTime.day().month(.abbreviated))
                                }
                            }
                            .frame(height: 220)
                        }
                    }

                    Section("Last 7 days") {
                        ForEach(summary.last7Days) { day in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(day.day).font(.headline)
                                Text("Cigarettes: \(day.cigarettes), Cravings: \(day.cravings), Resisted: \(day.cravingsResisted)")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }

                    Section("Rolling average") {
                        Text(String(format: "%.2f cigarettes/day", summary.rollingAvg7d))
                    }
                }

                if let error = viewModel.errorMessage {
                    Section {
                        Text(error).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("History")
            .toolbar {
                ToolbarItem(placement: .automatic) {
                    Button("Refresh") {
                        Task { await refresh() }
                    }
                }
            }
            .task {
                await refresh()
            }
            .overlay {
                if viewModel.isLoading {
                    ProgressView()
                }
            }
        }
    }

    private func refresh() async {
        guard let token = session.token else {
            viewModel.errorMessage = APIError.missingToken.localizedDescription
            return
        }
        await viewModel.load(token: token)
    }
}

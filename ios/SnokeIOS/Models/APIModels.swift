import Foundation

struct RegisterRequest: Encodable {
    let deviceID: String
    let baselineCigarettesPerDay: Int?
    let weaningRatePct: Int
    let weightKg: Double
    let heightCm: Double
    let bodyFat: Double
    let ageYears: Int
    let weeklyWeightLossKg: Double

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case baselineCigarettesPerDay = "baseline_cigarettes_per_day"
        case weaningRatePct = "weaning_rate_pct"
        case weightKg = "weight_kg"
        case heightCm = "height_cm"
        case bodyFat = "body_fat"
        case ageYears = "age_years"
        case weeklyWeightLossKg = "weekly_weight_loss_kg"
    }
}

struct TokenResponse: Codable {
    let accessToken: String
    let tokenType: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
    }
}

struct DailySummary: Codable, Identifiable {
    let day: String
    let cigarettes: Int
    let cravings: Int
    let cravingsResisted: Int

    var id: String { day }

    enum CodingKeys: String, CodingKey {
        case day
        case cigarettes
        case cravings
        case cravingsResisted = "cravings_resisted"
    }
}

struct SummaryResponse: Codable {
    let today: DailySummary
    let last7Days: [DailySummary]
    let rollingAvg7d: Double

    enum CodingKeys: String, CodingKey {
        case today
        case last7Days = "last_7_days"
        case rollingAvg7d = "rolling_avg_7d"
    }
}

struct TriggerResponse: Codable, Identifiable {
    let label: String
    let bucketKey: String
    let mean: Double
    let samples: Int

    var id: String { bucketKey + label }

    enum CodingKeys: String, CodingKey {
        case label
        case bucketKey = "bucket_key"
        case mean
        case samples
    }
}

struct ProbabilityResponse: Codable {
    let pNow: Double
    let pNextHour: Double
    let confidenceLevel: String
    let nextPeakAt: String?
    let topTriggers: [TriggerResponse]

    enum CodingKeys: String, CodingKey {
        case pNow = "p_now"
        case pNextHour = "p_next_hour"
        case confidenceLevel = "confidence_level"
        case nextPeakAt = "next_peak_at"
        case topTriggers = "top_triggers"
    }
}

struct NudgeResponse: Codable {
    let id: String
    let title: String
    let body: String
    let durationSeconds: Int
    let kind: String

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case body
        case durationSeconds = "duration_seconds"
        case kind
    }
}

struct WeaningResponse: Codable {
    let targetToday: Int
    let smokedToday: Int
    let remaining: Int
    let rollingAvg7d: Double
    let state: String
    let streakDaysOnTarget: Int

    enum CodingKeys: String, CodingKey {
        case targetToday = "target_today"
        case smokedToday = "smoked_today"
        case remaining
        case rollingAvg7d = "rolling_avg_7d"
        case state
        case streakDaysOnTarget = "streak_days_on_target"
    }
}

struct RecommendationResponse: Codable {
    let probability: ProbabilityResponse
    let weaning: WeaningResponse
    let nudge: NudgeResponse?
}

struct EventBatchRequest: Encodable {
    let events: [EventRequest]
}

struct EventRequest: Encodable {
    let clientUUID: String
    let kind: String
    let occurredAt: String
    let payload: [String: EventPayload]

    enum CodingKeys: String, CodingKey {
        case clientUUID = "client_uuid"
        case kind
        case occurredAt = "occurred_at"
        case payload
    }
}

enum EventPayload: Encodable {
    case string(String)
    case int(Int)
    case bool(Bool)
    case double(Double)

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        }
    }
}

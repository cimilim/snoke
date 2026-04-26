import Foundation

struct SnokeAPI {
    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .useDefaultKeys
        return decoder
    }()

    func register(_ request: RegisterRequest) async throws -> TokenResponse {
        try await perform(
            path: "/users/register",
            method: "POST",
            token: nil,
            body: request,
            responseType: TokenResponse.self
        )
    }

    func fetchSummary(token: String) async throws -> SummaryResponse {
        try await perform(
            path: "/me/summary",
            method: "GET",
            token: token,
            body: Optional<String>.none,
            responseType: SummaryResponse.self
        )
    }

    func fetchProbability(token: String) async throws -> ProbabilityResponse {
        try await perform(
            path: "/me/probability",
            method: "GET",
            token: token,
            body: Optional<String>.none,
            responseType: ProbabilityResponse.self
        )
    }

    func fetchRecommendation(token: String) async throws -> RecommendationResponse {
        try await perform(
            path: "/me/recommendation",
            method: "GET",
            token: token,
            body: Optional<String>.none,
            responseType: RecommendationResponse.self
        )
    }

    func sendEvents(token: String, events: [EventRequest]) async throws {
        let request = EventBatchRequest(events: events)
        _ = try await perform(
            path: "/events/batch",
            method: "POST",
            token: token,
            body: request,
            responseType: EmptyResponse.self
        )
    }

    private func perform<Body: Encodable, Response: Decodable>(
        path: String,
        method: String,
        token: String?,
        body: Body?,
        responseType: Response.Type
    ) async throws -> Response {
        guard let url = URL(string: AppConfig.currentBackendURL() + path) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            do {
                request.httpBody = try JSONEncoder().encode(body)
            } catch {
                throw APIError.encodingFailed
            }
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw APIError.transport(error)
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.requestFailed(statusCode: -1, message: "No HTTP response")
        }
        guard (200...299).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown server error"
            throw APIError.requestFailed(statusCode: http.statusCode, message: message)
        }

        if Response.self == EmptyResponse.self, let empty = EmptyResponse() as? Response {
            return empty
        }

        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.decodingFailed
        }
    }
}

private struct EmptyResponse: Decodable {}

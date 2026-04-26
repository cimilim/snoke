import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case requestFailed(statusCode: Int, message: String)
    case decodingFailed
    case encodingFailed
    case missingToken
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid backend URL."
        case .requestFailed(let statusCode, let message):
            return "Request failed (\(statusCode)): \(message)"
        case .decodingFailed:
            return "Could not decode server response."
        case .encodingFailed:
            return "Could not encode request body."
        case .missingToken:
            return "Missing auth token. Please re-register."
        case .transport(let error):
            return error.localizedDescription
        }
    }
}

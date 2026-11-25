import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case server(status: Int, detail: String?)
    case decodingFailed

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "The server URL in Settings is invalid."
        case .server(let status, let detail): return detail.map { "\($0) (HTTP \(status))" } ?? "Server returned HTTP \(status)."
        case .decodingFailed: return "Unexpected response from the server."
        }
    }
}

struct RemediationResponse: Codable {
    let diagnosisId: Int
    let status: String
    let detail: String

    enum CodingKeys: String, CodingKey {
        case status, detail
        case diagnosisId = "diagnosis_id"
    }
}

private struct ErrorBody: Codable { let detail: String? }

final class APIClient {
    static let shared = APIClient()
    static let tokenAccount = "apiToken"
    private init() {}

    private var baseURL: String {
        UserDefaults.standard.string(forKey: "baseURL") ?? "http://127.0.0.1:8000"
    }

    func fetchIncidents() async throws -> [Incident] {
        try await send(path: "/incidents", method: "GET")
    }

    func approveRemediation(diagnosisId: Int) async throws -> RemediationResponse {
        try await send(path: "/remediate/\(diagnosisId)", method: "POST")
    }

    private func send<T: Decodable>(path: String, method: String) async throws -> T {
        guard let url = URL(string: baseURL + path) else { throw APIError.invalidURL }
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = method
        if let token = Keychain.read(Self.tokenAccount), !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200...299).contains(status) else {
            throw APIError.server(status: status, detail: try? JSONDecoder().decode(ErrorBody.self, from: data).detail)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decodingFailed
        }
    }
}

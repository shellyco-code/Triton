import Foundation

enum APIError: Error {
    case invalidURL
    case requestFailed
    case decodingFailed
}

struct RemediationResponse: Codable {
    let status: String
    let diagnosisId: Int

    enum CodingKeys: String, CodingKey {
        case status
        case diagnosisId = "diagnosis_id"
    }
}

class APIClient {
    static let shared = APIClient()
    private init() {}

    private var baseURL: String {
        UserDefaults.standard.string(forKey: "baseURL") ?? "http://127.0.0.1:8000"
    }
    private var groqApiKey: String {
        UserDefaults.standard.string(forKey: "groqApiKey") ?? ""
    }

    func fetchIncidents() async throws -> [Incident] {
        guard let url = URL(string: "\(baseURL)/incidents") else { throw APIError.invalidURL }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else { throw APIError.requestFailed }
        do {
            return try JSONDecoder().decode([Incident].self, from: data)
        } catch {
            print("Decoding error: \(error)")
            throw APIError.decodingFailed
        }
    }

    func executeRemediation(diagnosisId: Int) async throws -> (status: String, diagnosisId: Int) {
        guard let url = URL(string: "\(baseURL)/remediate/\(diagnosisId)") else { throw APIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        if !groqApiKey.isEmpty {
            request.setValue(groqApiKey, forHTTPHeaderField: "X-Groq-Key")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else { throw APIError.requestFailed }
        do {
            let resp = try JSONDecoder().decode(RemediationResponse.self, from: data)
            return (status: resp.status, diagnosisId: resp.diagnosisId)
        } catch {
            throw APIError.decodingFailed
        }
    }
}

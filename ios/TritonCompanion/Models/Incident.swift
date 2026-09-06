import Foundation

struct Incident: Codable, Identifiable {
    let id: Int
    let podName: String
    let issues: [String]
    let detectedAt: String
    let diagnosis: String?
    let toolTrace: String?
    let proposedActionType: String?
    let actionStatus: String?
    let executedAt: String?
    let diagnosisId: Int?
    
    enum CodingKeys: String, CodingKey {
        case id
        case podName = "pod_name"
        case issues
        case detectedAt = "detected_at"
        case diagnosis
        case toolTrace = "tool_trace"
        case proposedActionType = "proposed_action_type"
        case actionStatus = "action_status"
        case executedAt = "executed_at"
        case diagnosisId = "diagnosis_id"
    }
    
    func decodeToolTrace() -> [ToolCall] {
        guard let traceString = toolTrace,
              let data = traceString.data(using: .utf8) else {
            return []
        }
        
        do {
            return try JSONDecoder().decode([ToolCall].self, from: data)
        } catch {
            print("Failed to decode tool trace: \(error)")
            return []
        }
    }
}

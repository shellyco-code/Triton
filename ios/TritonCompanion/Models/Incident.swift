import Foundation

struct Incident: Codable, Identifiable, Hashable {
    let id: Int
    let podName: String
    let namespace: String
    let workload: String?
    let issues: [String]
    let detectedAt: String
    let diagnosisId: Int?
    let diagnosis: String?
    let toolTrace: [ToolCall]
    let proposedActionType: String?
    let proposedTarget: String?
    let proposalReason: String?
    let actionStatus: String?
    let statusDetail: String?
    let executedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, namespace, workload, issues, diagnosis
        case podName = "pod_name"
        case detectedAt = "detected_at"
        case diagnosisId = "diagnosis_id"
        case toolTrace = "tool_trace"
        case proposedActionType = "proposed_action_type"
        case proposedTarget = "proposed_target"
        case proposalReason = "proposal_reason"
        case actionStatus = "action_status"
        case statusDetail = "status_detail"
        case executedAt = "executed_at"
    }

    var canApproveRestart: Bool {
        actionStatus == "pending_approval" && proposedActionType == "restart_pod" && diagnosisId != nil
    }

    /// Backend emits ISO-8601 with an explicit UTC offset, e.g. 2026-08-25T14:46:10+00:00.
    var detectedDate: Date? { Incident.isoFormatter.date(from: detectedAt) }
    var executedDate: Date? { executedAt.flatMap { Incident.isoFormatter.date(from: $0) } }

    private static let isoFormatter = ISO8601DateFormatter()
}

extension Incident {
    static let mockCrashloop = Incident(
        id: 1,
        podName: "chaos-crashloop-6c9d8-x7k2p",
        namespace: "triton-chaos",
        workload: "ReplicaSet/chaos-crashloop-6c9d8",
        issues: ["waiting_reason:CrashLoopBackOff", "high_restart_count:5"],
        detectedAt: "2026-08-25T14:46:10+00:00",
        diagnosisId: 1,
        diagnosis: "Root cause: worker exits 1 after losing its queue connection.\nEvidence: previous logs show 'FATAL: lost connection to queue'; 5 restarts.\nFix: restart; investigate queue availability.\nConfidence: high",
        toolTrace: [
            ToolCall(tool: "get_pod_events", input: [:], ok: true, error: nil, durationMs: 42),
            ToolCall(tool: "get_pod_logs", input: ["previous": .bool(true)], ok: true, error: nil, durationMs: 88),
        ],
        proposedActionType: "restart_pod",
        proposedTarget: "chaos-crashloop-6c9d8-x7k2p",
        proposalReason: "Transient crash; a fresh pod is likely to reconnect.",
        actionStatus: "pending_approval",
        statusDetail: nil,
        executedAt: nil
    )
}

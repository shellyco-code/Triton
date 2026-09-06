import SwiftUI

struct IncidentListView: View {
    @State private var viewModel: IncidentListViewModel

    init(viewModel: IncidentListViewModel = IncidentListViewModel()) {
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            List(viewModel.incidents) { incident in
                NavigationLink(destination: IncidentDetailView(viewModel: viewModel, incident: incident)) {
                    IncidentRowView(incident: incident)
                }
            }
            .navigationTitle("Incidents")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: SettingsView()) {
                        Image(systemName: "gear")
                    }
                }
            }
            .overlay {
                if viewModel.incidents.isEmpty && viewModel.isLoading {
                    ProgressView("Loading...")
                } else if viewModel.incidents.isEmpty {
                    Text("No incidents found. Cluster is healthy.")
                        .foregroundColor(.secondary)
                }
            }
            .alert("Error", isPresented: Binding(
                get: { viewModel.errorMessage != nil },
                set: { if !$0 { viewModel.errorMessage = nil } }
            ), presenting: viewModel.errorMessage) { _ in
                Button("OK") { viewModel.errorMessage = nil }
            } message: { msg in
                Text(msg)
            }
        }
        .onAppear {
            viewModel.startPolling()
        }
        .onDisappear {
            viewModel.stopPolling()
        }
    }
}

struct IncidentRowView: View {
    let incident: Incident

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(incident.podName)
                .font(.headline)

            HStack {
                Text(relativeTime(from: incident.detectedAt))
                    .font(.caption)
                    .foregroundColor(.secondary)

                Spacer()

                StatusPillView(status: incident.actionStatus)
            }
        }
        .padding(.vertical, 4)
    }

    private func relativeTime(from isoString: String) -> String {
        // Backend timestamps (Python datetime.isoformat()) look like
        // "2026-08-25T14:46:10.432390" — no timezone suffix, microsecond precision.
        // ISO8601DateFormatter requires a timezone designator and fails to parse this silently,
        // so trim to whole-seconds precision and parse with an explicit UTC formatter instead.
        let trimmed = String(isoString.prefix(19)) // "yyyy-MM-dd'T'HH:mm:ss"
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.locale = Locale(identifier: "en_US_POSIX")
        guard let date = formatter.date(from: trimmed) else {
            return isoString
        }
        let relativeFormatter = RelativeDateTimeFormatter()
        relativeFormatter.unitsStyle = .abbreviated
        return relativeFormatter.localizedString(for: date, relativeTo: Date())
    }
}

struct StatusPillView: View {
    let status: String?

    var body: some View {
        Text(displayString)
            .font(.caption2)
            .fontWeight(.bold)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(backgroundColor.opacity(0.2))
            .foregroundColor(backgroundColor)
            .cornerRadius(8)
    }

    private var displayString: String {
        guard let status = status else { return "TRIAGING" }
        switch status {
        case "pending_approval": return "PENDING APPROVAL"
        case "executed": return "EXECUTED"
        case "skipped_by_safety": return "SKIPPED"
        case "parse_error": return "ERROR"
        default: return status.uppercased()
        }
    }

    private var backgroundColor: Color {
        switch status {
        case "pending_approval": return .orange
        case "executed": return .green
        default: return .gray
        }
    }
}

extension Incident {
    static let mockCrashloop = Incident(
        id: 1,
        podName: "chaos-crashloop",
        issues: ["waiting_reason:CrashLoopBackOff", "high_restart_count:5"],
        detectedAt: "2026-08-25T14:46:10.432390",
        diagnosis: "Root Cause: Container 'crasher' crashed repeatedly with exit code 1 ('simulated failure').\nEvidence: Log output shows process exited with status 1. Restart count is 5.\nRecommended Action: Fix exit error in container startup script.\nConfidence: 98%",
        toolTrace: "[{\"tool\": \"get_pod_logs\", \"input\": {\"pod_name\": \"chaos-crashloop\", \"namespace\": \"default\"}}, {\"tool\": \"get_pod_events\", \"input\": {\"pod_name\": \"chaos-crashloop\", \"namespace\": \"default\"}}, {\"tool\": \"describe_pod\", \"input\": {\"pod_name\": \"chaos-crashloop\", \"namespace\": \"default\"}}]",
        proposedActionType: "restart_pod",
        actionStatus: "pending_approval",
        executedAt: nil,
        diagnosisId: 1
    )
}

#Preview {
    let vm = IncidentListViewModel()
    vm.incidents = [.mockCrashloop]
    return IncidentListView(viewModel: vm)
}

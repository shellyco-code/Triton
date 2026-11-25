import SwiftUI

struct IncidentListView: View {
    @State private var viewModel: IncidentListViewModel

    init(viewModel: IncidentListViewModel = IncidentListViewModel()) {
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            List(viewModel.incidents) { incident in
                NavigationLink(value: incident.id) {
                    IncidentRowView(incident: incident)
                }
            }
            .navigationTitle("Incidents")
            .navigationDestination(for: Int.self) { id in
                // Look the incident up by id so the detail screen reflects live polling updates.
                IncidentDetailView(viewModel: viewModel, incidentId: id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink {
                        SettingsView()
                    } label: {
                        Image(systemName: "gear")
                    }
                }
            }
            .refreshable { await viewModel.refresh() }
            .overlay {
                if viewModel.incidents.isEmpty {
                    if viewModel.isLoading {
                        ProgressView("Loading…")
                    } else {
                        ContentUnavailableView(
                            "No incidents",
                            systemImage: "checkmark.shield",
                            description: Text("The cluster looks healthy.")
                        )
                    }
                }
            }
            .alert(
                "Error",
                isPresented: Binding(
                    get: { viewModel.errorMessage != nil },
                    set: { if !$0 { viewModel.errorMessage = nil } }
                ),
                presenting: viewModel.errorMessage
            ) { _ in
                Button("OK") { viewModel.errorMessage = nil }
            } message: { msg in
                Text(msg)
            }
        }
        .onAppear { viewModel.startPolling() }
        .onDisappear { viewModel.stopPolling() }
    }
}

struct IncidentRowView: View {
    let incident: Incident

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(incident.podName)
                .font(.headline)
                .lineLimit(1)
            HStack {
                if let date = incident.detectedDate {
                    Text(date, format: .relative(presentation: .named))
                } else {
                    Text(incident.detectedAt)
                }
                Text("· \(incident.namespace)")
                Spacer()
                StatusPillView(status: incident.actionStatus)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

struct StatusPillView: View {
    let status: String?

    var body: some View {
        Text(label)
            .font(.caption2)
            .fontWeight(.bold)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.2))
            .foregroundStyle(color)
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var label: String {
        switch status {
        case nil: return "TRIAGING"
        case "pending_approval": return "NEEDS APPROVAL"
        case "executed": return "RESTARTED"
        case "skipped_by_safety": return "BLOCKED"
        case "manual_intervention": return "NEEDS HUMAN"
        case "parse_error": return "PARSE ERROR"
        case let other?: return other.uppercased()
        }
    }

    private var color: Color {
        switch status {
        case "pending_approval": return .orange
        case "executed": return .green
        case "skipped_by_safety", "failed": return .red
        case "manual_intervention": return .blue
        default: return .gray
        }
    }
}

#Preview {
    let vm = IncidentListViewModel()
    vm.incidents = [.mockCrashloop]
    return IncidentListView(viewModel: vm)
}

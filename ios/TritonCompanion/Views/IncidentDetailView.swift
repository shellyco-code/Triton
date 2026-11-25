import SwiftUI

struct IncidentDetailView: View {
    @Bindable var viewModel: IncidentListViewModel
    let incidentId: Int
    @State private var isApproving = false
    @State private var confirmRestart = false

    var body: some View {
        if let incident = viewModel.incident(id: incidentId) {
            content(for: incident)
        } else {
            ContentUnavailableView("Incident not found", systemImage: "questionmark.circle")
        }
    }

    private func content(for incident: Incident) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(incident.podName).font(.title3).bold()
                    Text("\(incident.namespace) · \(incident.workload ?? "unknown workload")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    StatusPillView(status: incident.actionStatus)
                    if let executed = incident.executedDate {
                        Text("Restarted \(executed, format: .relative(presentation: .named))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                section("Detected issues", show: !incident.issues.isEmpty) {
                    ForEach(incident.issues, id: \.self) { Text("• \($0)").font(.subheadline) }
                }

                section("Diagnosis", show: incident.diagnosis != nil) {
                    Text(incident.diagnosis ?? "")
                        .font(.body)
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(.secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }

                section("Proposed action", show: incident.proposedActionType != nil) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(incident.proposedActionType ?? "") → \(incident.proposedTarget ?? "")")
                            .font(.subheadline.monospaced())
                        if let reason = incident.proposalReason { Text(reason).font(.subheadline) }
                        if let detail = incident.statusDetail {
                            Text("Outcome: \(detail)").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }

                section("Tool execution trace", show: !incident.toolTrace.isEmpty) {
                    ForEach(Array(incident.toolTrace.enumerated()), id: \.offset) { _, call in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text("› \(call.tool)").bold().foregroundStyle(call.ok == false ? .red : .orange)
                                Spacer()
                                if let ms = call.durationMs { Text("\(ms) ms").foregroundStyle(.secondary) }
                            }
                            .font(.subheadline)
                            if !call.inputDescription.isEmpty {
                                Text(call.inputDescription).font(.caption).foregroundStyle(.secondary)
                            }
                            if let error = call.error { Text(error).font(.caption).foregroundStyle(.red) }
                        }
                        .padding(.vertical, 2)
                    }
                }

                if incident.canApproveRestart {
                    Button {
                        confirmRestart = true
                    } label: {
                        Label(isApproving ? "Restarting…" : "Approve restart", systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(isApproving)
                    .confirmationDialog(
                        "Delete \(incident.podName) so its controller recreates it?",
                        isPresented: $confirmRestart,
                        titleVisibility: .visible
                    ) {
                        Button("Restart pod", role: .destructive) {
                            Task {
                                isApproving = true
                                await viewModel.approveRestart(for: incident)
                                isApproving = false
                            }
                        }
                    }
                }

                if let message = viewModel.lastActionMessage {
                    Text(message).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .padding()
        }
        .navigationTitle("Incident")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private func section<Content: View>(_ title: String, show: Bool, @ViewBuilder _ body: () -> Content) -> some View {
        if show {
            VStack(alignment: .leading, spacing: 8) {
                Text(title).font(.headline)
                body()
            }
            Divider()
        }
    }
}

#Preview {
    let vm = IncidentListViewModel()
    vm.incidents = [.mockCrashloop]
    return NavigationStack {
        IncidentDetailView(viewModel: vm, incidentId: 1)
    }
}

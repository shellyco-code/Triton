import SwiftUI

struct IncidentDetailView: View {
    @Bindable var viewModel: IncidentListViewModel
    let incident: Incident
    
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header section
                VStack(alignment: .leading, spacing: 8) {
                    Text(incident.podName)
                        .font(.title2)
                        .bold()
                    
                    StatusPillView(status: incident.actionStatus)
                    
                    if let executed = incident.executedAt {
                        Text("Executed At: \(executed)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                
                Divider()
                
                // Issues
                if !incident.issues.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Detected Issues")
                            .font(.headline)
                        
                        ForEach(incident.issues, id: \.self) { issue in
                            Text("• \(issue)")
                                .font(.subheadline)
                        }
                    }
                    Divider()
                }
                
                // Diagnosis
                if let diagnosis = incident.diagnosis {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Final Diagnosis")
                            .font(.headline)
                        
                        Text(diagnosis)
                            .font(.body)
                            .padding()
                            .background(Color(UIColor.secondarySystemBackground))
                            .cornerRadius(8)
                    }
                    Divider()
                }
                
                // Tool Trace
                let trace = incident.decodeToolTrace()
                if !trace.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Tool Execution Trace")
                            .font(.headline)
                        
                        ForEach(Array(trace.enumerated()), id: \.offset) { _, tool in
                            VStack(alignment: .leading, spacing: 4) {
                                Text("› \(tool.tool)")
                                    .font(.subheadline)
                                    .bold()
                                    .foregroundColor(.orange)
                                
                                Text(String(describing: tool.input))
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                            .padding(.vertical, 4)
                            Divider()
                        }
                    }
                }
                
                // Remediation Button
                if incident.actionStatus == "pending_approval" {
                    if let diagId = incident.diagnosisId {
                        Button(action: {
                            Task {
                                await viewModel.executeRemediation(for: diagId)
                            }
                        }) {
                            Text("Execute Remediation")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.blue)
                                .foregroundColor(.white)
                                .cornerRadius(10)
                                .font(.headline)
                        }
                        .padding(.top, 10)
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Incident Details")
        .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview {
    let vm = IncidentListViewModel()
    return NavigationStack {
        IncidentDetailView(viewModel: vm, incident: .mockCrashloop)
    }
}

import Foundation
import Observation

@MainActor
@Observable
final class IncidentListViewModel {
    var incidents: [Incident] = []
    var isLoading = false
    var errorMessage: String?
    var lastActionMessage: String?

    private var pollTask: Task<Void, Never>?

    func incident(id: Int) -> Incident? {
        incidents.first { $0.id == id }
    }

    func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            await refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled else { break }
                await refresh(silent: true)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refresh(silent: Bool = false) async {
        if !silent { isLoading = true }
        defer { isLoading = false }
        do {
            incidents = try await APIClient.shared.fetchIncidents()
            errorMessage = nil
        } catch {
            // Don't nag on every background poll once data is on screen.
            if !silent || incidents.isEmpty {
                errorMessage = error.localizedDescription
            }
        }
    }

    func approveRestart(for incident: Incident) async {
        guard let diagnosisId = incident.diagnosisId else { return }
        do {
            let result = try await APIClient.shared.approveRemediation(diagnosisId: diagnosisId)
            lastActionMessage = result.status == "executed" ? "Pod restarted." : result.detail
        } catch {
            errorMessage = error.localizedDescription
        }
        await refresh(silent: true)
    }
}

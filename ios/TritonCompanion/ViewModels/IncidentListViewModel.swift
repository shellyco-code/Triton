import Foundation
import Observation

@Observable
class IncidentListViewModel {
    var incidents: [Incident] = []
    var isLoading: Bool = false
    var errorMessage: String? = nil
    
    private var pollTask: Task<Void, Never>?
    
    func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            await refresh()
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                if !Task.isCancelled {
                    await refresh(silent: true)
                }
            }
        }
    }
    
    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }
    
    func refresh(silent: Bool = false) async {
        if !silent {
            await MainActor.run { isLoading = true }
        }
        
        do {
            let fetched = try await APIClient.shared.fetchIncidents()
            await MainActor.run {
                self.incidents = fetched
                self.errorMessage = nil
                self.isLoading = false
            }
        } catch {
            await MainActor.run {
                if !silent || self.incidents.isEmpty {
                    self.errorMessage = error.localizedDescription
                }
                self.isLoading = false
            }
        }
    }
    
    func executeRemediation(for diagnosisId: Int) async {
        do {
            let _ = try await APIClient.shared.executeRemediation(diagnosisId: diagnosisId)
            await refresh()
        } catch {
            await MainActor.run {
                self.errorMessage = "Failed to execute remediation: \(error.localizedDescription)"
            }
        }
    }
}

import Foundation
import Combine

class LogsViewModel: ObservableObject {
    @Published var logs: [LogMessage] = []
    @Published var errorMessage: String?

    private let apiService = APIService.shared
    private var timer: Timer?

    init() {
        startPolling()
    }

    deinit {
        stopPolling()
    }

    func startPolling() {
        // Poll every 2 seconds
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.fetchLogs()
        }
        fetchLogs() // Initial fetch
    }

    func stopPolling() {
        timer?.invalidate()
        timer = nil
    }

    func fetchLogs() {
        Task {
            do {
                let logs = try await apiService.getLogs()
                DispatchQueue.main.async {
                    self.logs = logs
                }
            } catch {
                DispatchQueue.main.async {
                    self.errorMessage = "Error fetching logs: \(error.localizedDescription)"
                }
            }
        }
    }
}

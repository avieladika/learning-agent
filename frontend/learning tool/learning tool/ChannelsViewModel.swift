import Foundation
import Combine

class ChannelsViewModel: ObservableObject {
    @Published var channels: [Channel] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    private let apiService = APIService.shared

    init() {
        loadChannels()
    }

    func loadChannels() {
        isLoading = true
        errorMessage = nil

        Task {
            do {
                let channels = try await apiService.getChannels()
                DispatchQueue.main.async {
                    self.channels = channels
                    self.isLoading = false
                }
            } catch {
                DispatchQueue.main.async {
                    self.errorMessage = "Error loading channels: \(error.localizedDescription)"
                    self.isLoading = false
                }
            }
        }
    }

    func addChannel(channelId: String) {
        guard !channelId.isEmpty else { return }

        isLoading = true
        errorMessage = nil

        Task {
            do {
                let newChannel = try await apiService.addChannel(channelId: channelId)

                DispatchQueue.main.async {
                    self.channels.append(newChannel)
                    self.isLoading = false
                }
            } catch {
                DispatchQueue.main.async {
                    self.errorMessage = "Error adding channel: \(error.localizedDescription)"
                    self.isLoading = false
                }
            }
        }
    }

    func deleteChannel(at offsets: IndexSet) {
        offsets.forEach { index in
            let channel = channels[index]

            Task {
                do {
                    try await apiService.deleteChannel(channelId: channel.id)
                    DispatchQueue.main.async {
                        self.channels.remove(at: index)
                    }
                } catch {
                    DispatchQueue.main.async {
                        self.errorMessage = "Error deleting channel: \(error.localizedDescription)"
                    }
                }
            }
        }
    }
}

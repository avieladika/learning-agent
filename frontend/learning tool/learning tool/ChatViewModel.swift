import Foundation
import Combine

class ChatViewModel: ObservableObject {
    @Published var messages: [Message] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?

    private let apiService = APIService.shared

    func sendMessage(_ text: String) {
        guard !text.isEmpty else { return }

        // Send the prior conversation separately; the current message is the question.
        let conversationHistory = messages
        let userMessage = Message(text: text, isUser: true)
        messages.append(userMessage)

        isLoading = true
        errorMessage = nil

        Task {
            do {
                let answer = try await apiService.askQuestion(question: text, history: conversationHistory)

                // Add bot message
                let botMessage = Message(text: answer, isUser: false)

                DispatchQueue.main.async {
                    self.messages.append(botMessage)
                    self.isLoading = false
                }
            } catch {
                DispatchQueue.main.async {
                    self.errorMessage = "Error: \(error.localizedDescription)"
                    self.isLoading = false
                }
            }
        }
    }
}

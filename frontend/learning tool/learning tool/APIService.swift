import Foundation

class APIService {
    static let shared = APIService()
    private let baseURL = "http://localhost:8000" // Change this if running on a real device

    private let session: URLSession

    init() {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 300 // 5 minutes timeout
        configuration.timeoutIntervalForResource = 300 // 5 minutes timeout
        self.session = URLSession(configuration: configuration)
    }

    func askQuestion(question: String, history: [Message]) async throws -> String {
        guard let url = URL(string: "\(baseURL)/ask") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let historyBody = history.map { message in
            ["role": message.isUser ? "user" : "assistant", "content": message.text]
        }
        let body: [String: Any] = ["question": question, "history": historyBody]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, _) = try await session.data(for: request)
        let response = try JSONDecoder().decode(AskResponse.self, from: data)
        return response.answer
    }

    func addChannel(channelId: String) async throws -> Channel {
        guard let url = URL(string: "\(baseURL)/channels") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["channel_id": channelId]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }

        let channel = try JSONDecoder().decode(Channel.self, from: data)
        return channel
    }

    func deleteChannel(channelId: String) async throws {
        guard let url = URL(string: "\(baseURL)/channels/\(channelId)") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"

        let (_, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
    }

    func getChannels() async throws -> [Channel] {
        guard let url = URL(string: "\(baseURL)/channels") else {
            throw URLError(.badURL)
        }

        let (data, response) = try await session.data(for: URLRequest(url: url))

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }

        let channels = try JSONDecoder().decode([Channel].self, from: data)
        return channels
    }

    func getLogs() async throws -> [LogMessage] {
        guard let url = URL(string: "\(baseURL)/logs") else {
            throw URLError(.badURL)
        }

        let (data, response) = try await session.data(for: URLRequest(url: url))

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }

        let logs = try JSONDecoder().decode([LogMessage].self, from: data)
        return logs
    }
}

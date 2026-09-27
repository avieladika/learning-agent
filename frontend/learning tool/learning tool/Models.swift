import Foundation

struct Message: Identifiable, Codable {
    let id: UUID
    let text: String
    let isUser: Bool
    let timestamp: Date

    init(text: String, isUser: Bool) {
        self.id = UUID()
        self.text = text
        self.isUser = isUser
        self.timestamp = Date()
    }
}

struct Channel: Identifiable, Codable {
    let id: String
    let name: String
    let last_scanned: String? // Optional, as it might be null
}

struct AskResponse: Codable {
    let answer: String
}

struct ChannelRequest: Codable {
    let channel_id: String
}

struct LogMessage: Identifiable, Codable {
    var id: String { timestamp + message } // Unique ID based on content
    let timestamp: String
    let message: String
    let level: String
}

import SwiftUI

struct LogsView: View {
    @StateObject private var viewModel = LogsViewModel()

    var body: some View {
        VStack {
            List(viewModel.logs) { log in
                HStack {
                    Text(log.timestamp)
                        .font(.caption)
                        .foregroundColor(.gray)

                    Text(log.level)
                        .font(.caption)
                        .fontWeight(.bold)
                        .foregroundColor(colorForLevel(log.level))
                        .padding(.horizontal, 4)
                        .background(colorForLevel(log.level).opacity(0.2))
                        .cornerRadius(4)

                    Text(log.message)
                }
            }
            .navigationTitle("Server Logs")

            if let error = viewModel.errorMessage {
                Text(error)
                    .foregroundColor(.red)
                    .padding()
            }
        }
    }

    private func colorForLevel(_ level: String) -> Color {
        switch level {
        case "ERROR":
            return .red
        case "WARNING":
            return .orange
        default:
            return .primary
        }
    }
}

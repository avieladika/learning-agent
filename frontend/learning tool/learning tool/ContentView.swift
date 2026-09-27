import SwiftUI

struct ContentView: View {
    @StateObject private var chatViewModel = ChatViewModel()
    @StateObject private var serverManager = ServerManager.shared
    @State private var messageText: String = ""
    @State private var selectedItem: String? = "Chat" // Default selection

    var body: some View {
        NavigationView {
            // Sidebar (Left Panel)
            List(selection: $selectedItem) {
                NavigationLink(destination: ChatView(viewModel: chatViewModel), tag: "Chat", selection: $selectedItem) {
                    Label("Chat", systemImage: "message")
                }

                NavigationLink(destination: ChannelsView(), tag: "Channels", selection: $selectedItem) {
                    Label("Channels", systemImage: "list.bullet")
                }

                NavigationLink(destination: LogsView(), tag: "Logs", selection: $selectedItem) {
                    Label("Logs", systemImage: "terminal")
                }

                NavigationLink(destination: ServerConsoleView(), tag: "ServerConsole", selection: $selectedItem) {
                    Label("Server Console", systemImage: "desktopcomputer")
                }

                NavigationLink(destination: Text("Settings View"), tag: "Settings", selection: $selectedItem) {
                    Label("Settings", systemImage: "gear")
                }

                Divider()

                Button(action: {
                    if serverManager.isRunning {
                        serverManager.stopServer()
                    } else {
                        serverManager.startServer()
                    }
                }) {
                    Label(serverManager.isStarting ? "Starting..." : (serverManager.isRunning ? "Stop Server" : "Start Server"), systemImage: serverManager.isRunning ? "stop.circle.fill" : "play.circle.fill")
                        .foregroundColor(serverManager.isRunning ? .red : .green)
                }
                .disabled(serverManager.isStarting)
            }
            .listStyle(SidebarListStyle())
            .frame(minWidth: 200)

            // Main Content (Right Panel) - Default View
            Text("Select an item from the sidebar")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minWidth: 800, minHeight: 600) // Set minimum window size for macOS
    }
}

// Separate Chat View for cleaner code
struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel
    @State private var messageText: String = ""

    var body: some View {
        VStack {
            // Chat Area
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(viewModel.messages) { message in
                        MessageBubble(message: message)
                    }

                    if viewModel.isLoading {
                        ProgressView()
                            .padding()
                    }

                    if let error = viewModel.errorMessage {
                        Text(error)
                            .foregroundColor(.red)
                            .padding()
                    }
                }
                .padding()
            }

            // Input Area
            HStack {
                TextField("Ask a question...", text: $messageText)
                    .textFieldStyle(RoundedBorderTextFieldStyle())
                    .onSubmit {
                        sendMessage()
                    }

                Button(action: sendMessage) {
                    Image(systemName: "paperplane.fill")
                }
                .disabled(messageText.isEmpty)
            }
            .padding()
        }
        .navigationTitle("Learning Agent")
    }

    private func sendMessage() {
        viewModel.sendMessage(messageText)
        messageText = ""
    }
}

struct MessageBubble: View {
    let message: Message

    var body: some View {
        HStack {
            if message.isUser {
                Spacer()
                Text((try? AttributedString(markdown: message.text)) ?? AttributedString(message.text))
                    .padding()
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(12)
            } else {
                Text(message.text)
                    .padding()
                    .background(Color.gray.opacity(0.2))
                    .foregroundColor(.primary) // Use primary color for dark mode support
                    .cornerRadius(12)
                Spacer()
            }
        }
    }
}

struct ServerConsoleView: View {
    @StateObject private var serverManager = ServerManager.shared

    var body: some View {
        ScrollView {
            Text(serverManager.outputLog)
                .font(.system(.body, design: .monospaced))
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled) // Allow copying text
        }
        .navigationTitle("Local Server Output")
    }
}

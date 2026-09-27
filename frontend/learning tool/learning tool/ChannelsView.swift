import SwiftUI

struct ChannelsView: View {
    @StateObject private var viewModel = ChannelsViewModel()
    @State private var isAddingChannel: Bool = false
    @State private var newChannelId: String = ""

    var body: some View {
        VStack {
            List {
                ForEach(viewModel.channels) { channel in
                    HStack {
                        Image(systemName: "play.rectangle.fill")
                            .foregroundColor(.red)
                        Text(channel.name)
                        Spacer()
                        if let lastScanned = channel.last_scanned {
                            Text("Last scanned: \(lastScanned)")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    .contextMenu {
                        Button(role: .destructive) {
                            if let index = viewModel.channels.firstIndex(where: { $0.id == channel.id }) {
                                viewModel.deleteChannel(at: IndexSet(integer: index))
                            }
                        } label: {
                            Label("Delete Channel", systemImage: "trash")
                        }
                    }
                }
                .onDelete(perform: viewModel.deleteChannel) // Keep this for iOS compatibility or keyboard shortcuts
            }
            .navigationTitle("Channels")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button(action: {
                        isAddingChannel = true
                    }) {
                        Image(systemName: "plus")
                    }
                }
            }
            .sheet(isPresented: $isAddingChannel) {
                VStack {
                    Text("Add New Channel")
                        .font(.headline)
                        .padding()

                    TextField("Enter Channel ID", text: $newChannelId)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .padding()

                    HStack {
                        Button("Cancel") {
                            isAddingChannel = false
                        }
                        .keyboardShortcut(.cancelAction)

                        Button("Add") {
                            viewModel.addChannel(channelId: newChannelId)
                            isAddingChannel = false
                        }
                        .keyboardShortcut(.defaultAction)
                        .disabled(newChannelId.isEmpty)
                    }
                    .padding()
                }
                .padding()
                .frame(width: 300, height: 200) // Set fixed size for sheet on macOS
            }
        }
        .onAppear {
            viewModel.loadChannels()
        }
    }
}

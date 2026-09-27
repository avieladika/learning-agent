import SwiftUI

struct SidebarView: View {
    @Binding var selectedItem: String?

    var body: some View {
        List(selection: $selectedItem) {
            NavigationLink(destination: Text("Chat View"), tag: "Chat", selection: $selectedItem) {
                Label("Chat", systemImage: "message")
            }

            NavigationLink(destination: ChannelsView(), tag: "Channels", selection: $selectedItem) {
                Label("Channels", systemImage: "list.bullet")
            }

            NavigationLink(destination: Text("Settings View"), tag: "Settings", selection: $selectedItem) {
                Label("Settings", systemImage: "gear")
            }
        }
        .listStyle(SidebarListStyle())
        .frame(minWidth: 200)
    }
}

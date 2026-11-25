import SwiftUI

/// Pushed from the incident list's NavigationStack - must not create its own.
struct SettingsView: View {
    @AppStorage("baseURL") private var baseURL = "http://127.0.0.1:8000"
    @State private var apiToken = Keychain.read(APIClient.tokenAccount) ?? ""

    var body: some View {
        Form {
            Section {
                TextField("Server URL", text: $baseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
            } header: {
                Text("Triton server")
            }

            Section {
                SecureField("API token", text: $apiToken)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } header: {
                Text("Authentication")
            } footer: {
                Text("Required only if the server sets TRITON_API_TOKEN. Stored in the Keychain.")
            }
        }
        .navigationTitle("Settings")
        .onChange(of: apiToken) { _, newValue in
            Keychain.write(newValue.trimmingCharacters(in: .whitespaces), for: APIClient.tokenAccount)
        }
    }
}

#Preview {
    NavigationStack { SettingsView() }
}

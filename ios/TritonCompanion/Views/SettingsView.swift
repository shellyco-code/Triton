import SwiftUI

struct SettingsView: View {
    @AppStorage("baseURL") private var baseURL: String = "http://127.0.0.1:8000"
    @AppStorage("groqApiKey") private var groqApiKey: String = ""
    
    var body: some View {
        NavigationStack {
            Form {
                Section(header: Text("API Configuration")) {
                    TextField("Base URL", text: $baseURL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .keyboardType(.URL)
                    
                    SecureField("Groq API Key", text: $groqApiKey)
                }
            }
            .navigationTitle("Settings")
        }
    }
}

#Preview {
    SettingsView()
}

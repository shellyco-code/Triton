import Foundation

struct ToolCall: Codable {
    let tool: String
    let input: [String: String]
}

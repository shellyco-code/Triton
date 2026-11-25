import Foundation

/// One step of the agent's investigation, as recorded by the backend.
struct ToolCall: Codable, Hashable {
    let tool: String
    let input: [String: JSONValue]
    let ok: Bool?
    let error: String?
    let durationMs: Int?

    enum CodingKeys: String, CodingKey {
        case tool, input, ok, error
        case durationMs = "duration_ms"
    }

    var inputDescription: String {
        input.isEmpty ? "" : input.map { "\($0.key)=\($0.value)" }.sorted().joined(separator: ", ")
    }
}

/// Minimal JSON value so tool inputs of any type (bool, number, string) decode.
enum JSONValue: Codable, Hashable, CustomStringConvertible {
    case string(String), number(Double), bool(Bool), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else { self = .string("…") }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .null: try c.encodeNil()
        }
    }

    var description: String {
        switch self {
        case .string(let s): return s
        case .number(let n): return n.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(n)) : String(n)
        case .bool(let b): return String(b)
        case .null: return "null"
        }
    }
}

// Copyright (C) 2026 Luantani
// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI

struct MIDIInputAssignment: Decodable {
    var keyboard: String?
    var device: String?
    var port: String?
    var channel: Int?
    var part_channel: Int?
    var status: String
}
struct MIDIInput: Decodable {
    var assignments: [MIDIInputAssignment]
    var status: String
}
struct MIDIInputView: View {
    var input: MIDIInput
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Ingresso MIDI", systemImage: "pianokeys")
                .font(.system(size: 11, weight: .semibold)).foregroundStyle(.blue)
            if input.assignments.isEmpty {
                Text(input.status).font(.caption).foregroundStyle(.secondary)
            }
            ForEach(Array(input.assignments.enumerated()), id: \.offset) { _, assignment in
                VStack(alignment: .leading, spacing: 5) {
                    Text(assignment.keyboard.map { "Keyboard: \($0)" } ?? "Tastiera non ricavabile")
                        .font(.system(size: 13, weight: .semibold)).textSelection(.enabled)
                    if let device = assignment.device {
                        Label(device, systemImage: "cable.connector").font(.system(size: 12)).textSelection(.enabled)
                        if let port = assignment.port, port != device {
                            Text("Porta: \(port)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    } else {
                        Text("Dispositivo non ricavabile").font(.caption).foregroundStyle(.secondary)
                    }
                    if let channel = assignment.part_channel {
                        Text("Parte MIDI · canale \(channel)").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 9))
            .accessibilityElement(children: .combine)
    }
}

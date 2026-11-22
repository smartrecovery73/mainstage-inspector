// Copyright (C) 2026 Luantani
// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import AppKit

struct KeyboardZone: Decodable {
    var low: Int?; var high: Int?
    var velocity_low: Int?; var velocity_high: Int?
    var transpose: Int?
    var override_parent: Bool
    var unpitched: Bool
    static func note(_ n: Int) -> String {
        ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"][n % 12] + String(n / 12 - 1)
    }
}
struct KeyboardZoneView: View {
    var zone: KeyboardZone
    private let black = [1, 3, 6, 8, 10]
    var body: some View {
        if let low = zone.low, let high = zone.high {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("Zona tastiera").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text("\(KeyboardZone.note(low)) → \(KeyboardZone.note(high))").font(.caption.weight(.medium))
                }
                Canvas { context, size in
                    let whites = (0...127).filter { !black.contains($0 % 12) }
                    let width = size.width / CGFloat(whites.count)
                    for (index, note) in whites.enumerated() {
                        let rect = CGRect(x: CGFloat(index) * width, y: 0, width: width - 0.5, height: size.height)
                        let path = Path(roundedRect: rect, cornerRadius: 1)
                        context.fill(path, with: .color(note >= low && note <= high ? Color(red: 0.59, green: 0.72, blue: 0.81) : Color.gray.opacity(0.3)))
                    }
                    for note in 0...127 where black.contains(note % 12) {
                        let count = whites.filter { $0 < note }.count
                        let rect = CGRect(x: CGFloat(count) * width - width * 0.32, y: 0, width: width * 0.64, height: size.height * 0.62)
                        context.fill(Path(roundedRect: rect, cornerRadius: 1), with: .color(note >= low && note <= high ? Color(red: 0.20, green: 0.35, blue: 0.47) : Color.black.opacity(0.65)))
                    }
                }.frame(height: 43).accessibilityLabel("Zona note MIDI \(low)–\(high)")
                HStack {
                    if let lo = zone.velocity_low, let hi = zone.velocity_high { Text("Velocity \(lo)–\(hi)") }
                    Spacer()
                    if let transpose = zone.transpose { Text("Trasp. \(transpose > 0 ? "+" : "")\(transpose) st") }
                }.font(.caption2).foregroundStyle(.secondary)
                if zone.unpitched { Text("Unpitched").font(.caption2).foregroundStyle(.secondary) }
                if zone.override_parent { Text("Override della zona superiore").font(.caption2).foregroundStyle(.secondary) }
            }.help("Zona locale salvata. Convenzione note: MIDI 60 = C4; gli override dei livelli superiori non sono calcolati.")
        }
    }
}
struct SummaryPlugin: Decodable { var name: String; var instances: Int; var references: Int; var patches: [String] }
struct SummaryDevice: Decodable { var name: String; var keyboards: [String]; var patches: [String] }
struct SummaryAlias: Decodable { var strip: String; var node: String; var target: String }
struct ConcertSummary: Decodable {
    var sets: Int; var patches: Int; var strips: Int; var alias_count: Int
    var plugins: [SummaryPlugin]; var devices: [SummaryDevice]; var aliases: [SummaryAlias]
}
struct ConcertSummaryView: View {
    var summary: ConcertSummary
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("Riepilogo del concerto").font(.title2.bold()); Spacer(); Button("Chiudi") { dismiss() }.keyboardShortcut(.cancelAction) }
            HStack(spacing: 24) {
                Text("\(summary.sets) Set"); Text("\(summary.patches) Patch"); Text("\(summary.strips) Strip"); Text("\(summary.alias_count) Alias")
            }.font(.headline).foregroundStyle(InspectorPalette.patch)
            TextField("Cerca plugin, hardware o alias", text: $query).textFieldStyle(.roundedBorder)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Plugin richiesti").font(.headline)
                    Text("Le istanze escludono gli alias; i riferimenti li includono.").font(.caption).foregroundStyle(.secondary)
                    ForEach(Array(summary.plugins.enumerated()), id: \.offset) { _, plugin in
                        if query.isEmpty || plugin.name.localizedCaseInsensitiveContains(query) {
                            VStack(alignment: .leading, spacing: 5) {
                                HStack { Text(plugin.name).fontWeight(.semibold); Spacer(); Text("\(plugin.instances) istanze · \(plugin.references) riferimenti").foregroundStyle(.secondary) }
                                Text(plugin.patches.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                            }.padding(10).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                    Text("Tastiere assegnate agli strip").font(.headline).padding(.top)
                    ForEach(Array(summary.devices.enumerated()), id: \.offset) { _, device in
                        if query.isEmpty || ([device.name] + device.keyboards).joined(separator: " ").localizedCaseInsensitiveContains(query) {
                            VStack(alignment: .leading, spacing: 5) {
                                Label(device.name, systemImage: "pianokeys").fontWeight(.semibold)
                                Text(device.keyboards.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                                Text("Presente in \(device.patches.count) nodi del concerto").font(.caption).foregroundStyle(.secondary)
                            }.padding(10)
                        }
                    }
                    Text("Alias condivisi").font(.headline).padding(.top)
                    ForEach(Array(summary.aliases.enumerated()), id: \.offset) { _, alias in
                        if query.isEmpty || "\(alias.node) \(alias.strip) \(alias.target)".localizedCaseInsensitiveContains(query) {
                            Label("\(alias.node) / \(alias.strip) → \(alias.target)", systemImage: "link").font(.callout).padding(.vertical, 3)
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
        }.padding(24).frame(minWidth: 760, idealWidth: 880, minHeight: 560, idealHeight: 720)
    }
}
final class RememberingWindowView: NSView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let window else { return }
        if window.frameAutosaveName != "InspectorMainWindow" {
            window.setFrameUsingName("InspectorMainWindow")
            window.setFrameAutosaveName("InspectorMainWindow")
        }
    }
}
struct WindowMemory: NSViewRepresentable {
    func makeNSView(context: Context) -> RememberingWindowView { RememberingWindowView() }
    func updateNSView(_ nsView: RememberingWindowView, context: Context) {}
}


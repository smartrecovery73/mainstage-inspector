// Copyright (C) 2026 Luantani
// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import AppKit

enum InspectorPalette {
    static func adaptive(_ light: (Double, Double, Double), _ dark: (Double, Double, Double)) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let rgb = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1)
        })
    }
    static let patch = adaptive((0.25, 0.39, 0.51), (0.65, 0.76, 0.86))
    static let set = adaptive((0.32, 0.43, 0.33), (0.68, 0.78, 0.67))
    static let concert = adaptive((0.40, 0.35, 0.49), (0.77, 0.72, 0.84))
    static let strip = adaptive((0.46, 0.36, 0.24), (0.84, 0.77, 0.65))
    static func title(_ kind: String) -> Color {
        kind == "Set" ? set : kind == "Concert" ? concert : patch
    }
}

struct Preset: Decodable {
    var name: String
    var role: String
    var modified: Bool?
}
struct Plugin: Decodable {
    var name: String
    var type: String?
    var source: String
    var name_status: String?
    var preset_status: String?
    var presets: [Preset]?
    var setting_name: String?
    var bypass: Bool?
}
struct AliasTarget: Decodable { var node: String; var strip: String }
struct Strip: Decodable {
    var name: String
    var file: String?
    var plugin_records: [Plugin]
    var is_alias: Bool?
    var alias_target: AliasTarget?
    var warnings: [String]
    var midi_input: MIDIInput?
    var zone: KeyboardZone?
    var muted: Bool?
    var solo: Bool?
    var layer_bypassed: Bool?
}
struct ConcertNode: Decodable {
    var kind: String
    var name: String
    var path: String
    var strips: [Strip]
    var controllers: [String]
    var warnings: [String]
    var children: [ConcertNode]
    var hardware: [String]?
    var summary: ConcertSummary?
    var printable_report: String?
}
struct NodeRow: Identifiable {
    var node: ConcertNode
    var depth: Int
    var parents: [ConcertNode]
    var id: String { node.path }
}

@MainActor final class InspectorModel: ObservableObject {
    @Published var tree: ConcertNode?
    @Published var selected: String?
    @Published var loading = false
    @Published var error: String?
    @Published var search = ""
    @Published var searchScope = "Tutto"
    @Published var showSummary = false
    @Published var currentPath: String?
    private var report = Data()
    var rows: [NodeRow] {
        func flatten(_ n: ConcertNode, _ depth: Int, _ parents: [ConcertNode]) -> [NodeRow] {
            [NodeRow(node: n, depth: depth, parents: parents)] + n.children.flatMap { flatten($0, depth + 1, parents + [n]) }
        }
        return tree.map { flatten($0, 0, []) } ?? []
    }
    var chosen: NodeRow? { rows.first { $0.id == selected } }
    var filteredRows: [NodeRow] {
        guard !search.isEmpty else { return rows }
        return rows.filter { row in
            var terms = searchScope == "Tutto" ? [row.node.name] : [String]()
            for strip in row.node.strips {
                if searchScope == "Tutto" { terms.append(strip.name) }
                if searchScope != "Preset" {
                    for input in strip.midi_input?.assignments ?? [] {
                        terms += [input.keyboard ?? "", input.device ?? "", input.port ?? ""]
                    }
                }
                for plugin in strip.plugin_records where searchScope != "Hardware" {
                    if searchScope == "Tutto" { terms.append(plugin.name) }
                    for preset in plugin.presets ?? [] { terms.append(preset.name) }
                }
            }
            return terms.joined(separator: " ").localizedCaseInsensitiveContains(search)
        }
    }
    func open() {
        let panel = NSOpenPanel()
        panel.title = "Apri concerto MainStage"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.treatsFilePackagesAsDirectories = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { load(url.path) }
    }
    func load(_ path: String) {
        guard !loading else { return }
        let previousSelection = currentPath == path ? selected : nil
        loading = true; error = nil; currentPath = path
        let runtime = Bundle.main.resourceURL?.appendingPathComponent("PythonRuntime")
        let bundledPython = runtime?.appendingPathComponent("bin/python3")
        let useBundledPython = bundledPython.map { FileManager.default.isExecutableFile(atPath: $0.path) } ?? false
        let python = useBundledPython ? bundledPython!.path : Bundle.main.object(forInfoDictionaryKey: "InspectorPython") as? String ?? ""
        guard !python.isEmpty else {
            error = "Runtime Python incluso nell’app non trovato. Reinstalla MainStage Inspector."
            loading = false; return
        }
        guard let script = Bundle.main.url(forResource: "mainstage_inspector", withExtension: "py") else {
            error = "Il parser Python non è presente nell'app."; loading = false; return
        }
        Task {
            let result = await Task.detached(priority: .userInitiated) { () -> Result<Data, Error> in
                do {
                    let task = Process()
                    task.executableURL = URL(fileURLWithPath: python)
                    task.arguments = ["-S", "-B", script.path, path, "--json"]
                    if useBundledPython, let runtime {
                        var environment = ProcessInfo.processInfo.environment.filter {
                            !$0.key.hasPrefix("PYTHON") && $0.key != "__PYVENV_LAUNCHER__"
                        }
                        environment["PYTHONHOME"] = runtime.path
                        environment["PYTHONDONTWRITEBYTECODE"] = "1"
                        task.environment = environment
                    }
                    // File temporanei: nessun EOF da attendere da descrittori ereditati
                    // dai processi Audio Unit avviati durante l'enumerazione.
                    let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                    let outputURL = temp.appendingPathExtension("json")
                    FileManager.default.createFile(atPath: temp.path, contents: nil)
                    FileManager.default.createFile(atPath: outputURL.path, contents: nil)
                    let errors = try FileHandle(forWritingTo: temp)
                    let output = try FileHandle(forWritingTo: outputURL)
                    task.standardOutput = output
                    defer {
                        try? errors.close(); try? output.close()
                        try? FileManager.default.removeItem(at: temp)
                        try? FileManager.default.removeItem(at: outputURL)
                    }
                    task.standardError = errors
                    try task.run()
                    let deadline = Date().addingTimeInterval(120)
                    while task.isRunning && Date() < deadline { try await Task.sleep(nanoseconds: 100_000_000) }
                    if task.isRunning {
                        task.terminate()
                        throw NSError(domain: "Inspector", code: 1, userInfo: [NSLocalizedDescriptionKey: "Tempo di analisi scaduto. Riprova usando --cli per la diagnostica."])
                    }
                    let data = try Data(contentsOf: outputURL)
                    if task.terminationStatus != 0 {
                        let message = (try? String(contentsOf: temp, encoding: .utf8)) ?? "Analisi non riuscita."
                        throw NSError(domain: "Inspector", code: Int(task.terminationStatus), userInfo: [NSLocalizedDescriptionKey: message])
                    }
                    return .success(data)
                } catch { return .failure(error) }
            }.value
            do {
                let data = try result.get()
                let parsed = try JSONDecoder().decode(ConcertNode.self, from: data)
                tree = parsed; report = data
                selected = rows.contains(where: { $0.id == previousSelection }) ? previousSelection : parsed.path
                search = ""
            } catch { self.error = error.localizedDescription }
            loading = false
        }
    }
    func exportReadable() {
        guard let html = tree?.printable_report else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "MainStage-report.html"
        if panel.runModal() == .OK, let url = panel.url {
            do { try html.write(to: url, atomically: true, encoding: .utf8) }
            catch { self.error = error.localizedDescription }
        }
    }
    func export() {
        guard !report.isEmpty else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "MainStage-report.json"
        if panel.runModal() == .OK, let url = panel.url {
            do { try report.write(to: url, options: .atomic) }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct PluginView: View {
    let plugin: Plugin
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: plugin.type == "aumu" ? "pianokeys" : "waveform")
                    .foregroundStyle(Color.accentColor).frame(width: 22)
                Text(plugin.name).font(.system(size: 14, weight: .semibold)).textSelection(.enabled)
                Spacer(minLength: 0)
                if plugin.bypass == true {
                    Text("BYPASS").font(.system(size: 9, weight: .bold)).foregroundStyle(.orange)
                }
            }
            if plugin.name_status?.contains("non verificata") == true {
                Text("Nome abbreviato · da verificare").font(.caption).foregroundStyle(.orange)
            }
            let presets = plugin.presets ?? []
            if let setting = plugin.setting_name {
                Text("Impostazione salvata: \(setting)").font(.system(size: 12)).textSelection(.enabled)
            } else if presets.isEmpty {
                Text("Preset non ricavabile").font(.system(size: 12)).foregroundStyle(.secondary)
            } else {
                ForEach(Array(presets.enumerated()), id: \.offset) { _, preset in
                    HStack(alignment: .top) {
                        Text(preset.role).foregroundStyle(.secondary).frame(width: 52, alignment: .leading)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(preset.name).textSelection(.enabled)
                            if preset.modified == true { Text("Modificato rispetto al preset").foregroundStyle(.orange).font(.caption2) }
                        }
                    }.font(.system(size: 12))
                }
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8))
    }
}
struct StripCard: View {
    let strip: Strip
    let origin: String
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(strip.name).font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(InspectorPalette.strip).textSelection(.enabled)
                Text(origin).font(.caption).foregroundStyle(.secondary)
                if let target = strip.alias_target {
                    Label("Alias di \(target.node) / \(target.strip)", systemImage: "link").font(.caption).foregroundStyle(.mint)
                } else if strip.is_alias == true {
                    Label("Alias non risolto", systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
                }
            }
            HStack(spacing: 12) {
                if strip.muted == true { Label("Mute", systemImage: "speaker.slash.fill").foregroundStyle(.orange) }
                if strip.solo == true { Label("Solo", systemImage: "headphones").foregroundStyle(.yellow) }
                if strip.layer_bypassed == true { Label("Layer disattivato", systemImage: "pause.circle").foregroundStyle(.secondary) }
            }.font(.caption.weight(.semibold))
            if let midi = strip.midi_input {
                MIDIInputView(input: midi)
            }
            if let zone = strip.zone { KeyboardZoneView(zone: zone) }
            Divider()
            if strip.plugin_records.isEmpty {
                Text("Nessun plugin riconosciuto nel file. Non equivale a uno strip vuoto.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            ForEach(Array(strip.plugin_records.enumerated()), id: \.offset) { _, plugin in PluginView(plugin: plugin) }
        }.padding(16).frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.09)))
    }
}
struct DetailView: View {
    let row: NodeRow
    @State private var tab = 0
    @State private var showParents = false
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                Text((row.parents.map { $0.name } + [row.node.kind]).joined(separator: "  ›  "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                HStack {
                    Text(row.node.name).font(.system(size: 27, weight: .bold))
                        .foregroundStyle(InspectorPalette.title(row.node.kind))
                    Spacer()
                    Text("\(row.node.strips.count) channel strip locali").font(.callout).foregroundStyle(.secondary)
                }
                Picker("Vista", selection: $tab) {
                    Text("Channel strip").tag(0)
                    Text("Avvisi").tag(1)
                }.pickerStyle(.segmented).frame(maxWidth: 560)
            }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if tab == 0 {
                        if !row.parents.isEmpty {
                            Toggle("Mostra anche gli strip dei livelli superiori", isOn: $showParents).font(.callout)
                        }
                        if row.node.strips.isEmpty {
                            ContentUnavailableView("Nessuno strip locale", systemImage: "slider.horizontal.3", description: Text("Seleziona una Patch o mostra gli strip dei livelli superiori."))
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 290, maximum: 440), spacing: 16, alignment: .top)], alignment: .leading, spacing: 16) {
                            ForEach(Array(row.node.strips.enumerated()), id: \.offset) { _, strip in
                                StripCard(strip: strip, origin: "\(row.node.kind) · \(row.node.name)")
                            }
                        }
                        if showParents {
                            ForEach(row.parents, id: \.path) { parent in
                                if !parent.strips.isEmpty {
                                    Text("\(parent.kind) · \(parent.name)").font(.title3.bold())
                                    Text("Strip salvati al livello superiore; disponibilità effettiva e override non verificati.").font(.caption).foregroundStyle(.secondary)
                                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 290, maximum: 440), alignment: .top)], alignment: .leading, spacing: 16) {
                                        ForEach(Array(parent.strips.enumerated()), id: \.offset) { _, strip in
                                            StripCard(strip: strip, origin: parent.kind)
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        Text("Limiti e diagnostica").font(.headline)
                        ForEach(Array(row.node.warnings.enumerated()), id: \.offset) { _, line in
                            Label(line, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
                        }
                        Text("I nomi dei preset provengono dallo stato salvato nel concerto. Non costituiscono una verifica del suono attualmente caricato in MainStage.").font(.callout).foregroundStyle(.secondary)
                    }
                }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
            }
        }.background(Color(nsColor: .windowBackgroundColor))
    }
}
struct InspectorView: View {
    @StateObject private var model = InspectorModel()
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                Text("LIBRERIA DEL CONCERTO").font(.system(size: 10, weight: .bold)).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.top, 16)
                TextField("Cerca Patch, plugin, hardware o preset", text: $model.search).textFieldStyle(.roundedBorder).padding(12)
                Picker("Cerca in", selection: $model.searchScope) {
                    Text("Tutto").tag("Tutto"); Text("Hardware").tag("Hardware"); Text("Preset").tag("Preset")
                }.pickerStyle(.segmented).padding(.horizontal, 12).padding(.bottom, 8)
                List(selection: $model.selected) {
                    ForEach(model.filteredRows) { row in
                        HStack(spacing: 8) {
                            Image(systemName: row.node.kind == "Patch" ? "music.note" : row.node.kind == "Set" ? "folder" : "square.stack.3d.up")
                                .foregroundStyle(row.node.kind == "Set" ? Color.orange : Color.accentColor).frame(width: 16)
                            Text(row.node.name).font(.system(size: 12)).lineLimit(2)
                                .foregroundStyle(model.selected == row.id ? Color.white : InspectorPalette.title(row.node.kind))
                        }.padding(.leading, CGFloat(max(0, row.depth - 1) * 13)).padding(.vertical, 4).tag(row.id)
                    }
                }.listStyle(.sidebar)
                if let tree = model.tree {
                    Text("\(model.rows.count - 1) Set e Patch · \(tree.name)").font(.caption2).foregroundStyle(.secondary).padding(12)
                }
            }.navigationSplitViewColumnWidth(min: 240, ideal: 280, max: 390)
        } detail: {
            if let row = model.chosen { DetailView(row: row).id(row.id) }
            else {
                ContentUnavailableView {
                    Label("MainStage Inspector", systemImage: "pianokeys")
                } description: { Text("Apri un concerto per esplorare Set, Patch, plugin e preset.") }
                actions: { Button("Apri .concert…", action: model.open).buttonStyle(.borderedProminent).disabled(model.loading) }
            }
        }
        .toolbar {
            ToolbarItemGroup {
                Button(action: model.open) { Label("Apri concerto", systemImage: "folder.badge.plus") }.disabled(model.loading)
                Button {
                    if let path = model.currentPath { model.load(path) }
                } label: { Label("Rianalizza", systemImage: "arrow.clockwise") }
                    .disabled(model.currentPath == nil || model.loading)
                    .help("Rilegge il concerto e aggiorna plugin e preset")
                Button { model.showSummary = true } label: { Label("Riepilogo", systemImage: "list.bullet.rectangle") }
                    .disabled(model.tree?.summary == nil || model.loading)
                Menu {
                    Button("Report stampabile (.html)", action: model.exportReadable)
                    Button("Dati completi (.json)", action: model.export)
                } label: { Label("Esporta", systemImage: "square.and.arrow.up") }.disabled(model.tree == nil || model.loading)
            }
        }
        .overlay {
            if model.loading {
                ZStack {
                    Color.black.opacity(0.25).ignoresSafeArea()
                    VStack(spacing: 14) { ProgressView(); Text("Analisi del concerto…"); Text("Lettura dei plugin e dei preset salvati").font(.caption).foregroundStyle(.secondary) }
                        .padding(30).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                }
            }
        }
        .alert("Analisi non riuscita", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
        .frame(minWidth: 960, minHeight: 640)
        .background(WindowMemory())
        .sheet(isPresented: $model.showSummary) {
            if let summary = model.tree?.summary { ConcertSummaryView(summary: summary) }
        }
        .onAppear {
            if let path = CommandLine.arguments.dropFirst().first(where: { $0.hasSuffix(".concert") }) { model.load(path) }
        }
        .onOpenURL { model.load($0.path) }
    }
}
@main struct MainStageInspectorApp: App {
    init() {
        // Migrazione privacy: elimina esclusivamente le chiavi di sessione
        // create dalle versioni precedenti, senza toccare concerti o report.
        for key in ["lastConcert", "lastSelected", "lastSearch", "lastScope"] {
            UserDefaults.standard.removeObject(forKey: key)
        }
        NSDocumentController.shared.clearRecentDocuments(nil)
    }
    var body: some Scene {
        WindowGroup("MainStage Inspector") { InspectorView() }
            .defaultSize(width: 1220, height: 800)
            .commands {
                CommandGroup(replacing: .help) {
                    Button("Informazioni e licenza") {
                        if let url = Bundle.main.url(forResource: "Informazioni", withExtension: "html") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    Divider()
                    Button("Manuale di MainStage Inspector") {
                        if let url = Bundle.main.url(forResource: "Manuale", withExtension: "html") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                }
            }
    }
}

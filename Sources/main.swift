// TRS80Extract 1.3 - a SwiftUI front end for trsextract.py
// Copyright (C) 2026 Egbert Schroeer
//
// This program is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by the Free
// Software Foundation, either version 3 of the License, or (at your option)
// any later version. Distributed WITHOUT ANY WARRANTY.
// See <https://www.gnu.org/licenses/>.
//
// wrapper function: shells out to `python3 trsextract.py`. Requires Python 3
// on the system and the trsextract.py script (located via the resolver below).
//
// new extended version of the start screen presents now in two intents side by side:
//   - "Read a disk"          drop a .dmk/.dsk to list and extract it.
//   - "Write a file to a disk" choose/drop a target disk, then drop the file
//                             to add; writes via --write-file / --write-basic
//                             into a COPY (<target>.out.dsk), never the original.
//
// 1.3 adds a second tab, "Catalog": search the whole collection ("which disk
// has FILE X?"). It reads catalog.json, the machine output of
//   python3 catalog-logs.py ./logs --json > catalog.json
// and filters it live in memory - no subprocess per keystroke. Empty search
// shows a disk browser (disk list left, file table right). The Python side
// stays the single source of truth for log parsing and the standard-file
// filter rules; this tab only displays what it is given.

import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - Model

/// One row parsed from the trsextract listing.
struct DiskFile: Identifiable {
    let id = UUID()
    let name: String       // e.g. "WC/BAS"
    let attr: String
    let lrl: String
    let eofOff: String
    let extents: String
}

/// Result of running a list operation.
struct ListResult {
    var header: [String]   // the non-table lines (format, sides, dir track)
    var files: [DiskFile]
    var rawError: String   // anything from stderr
}

// MARK: - Runner (subprocess plumbing)

enum TrsError: LocalizedError {
    case pythonNotFound
    case scriptNotFound
    case runFailed(String)
    var errorDescription: String? {
        switch self {
        case .pythonNotFound:
            return "Could not find python3. Install the Xcode Command Line "
                 + "Tools (xcode-select --install) or Homebrew Python."
        case .scriptNotFound:
            return "Could not find trsextract.py. Place it next to this app, "
                 + "or inside the app bundle's Resources, or in the same "
                 + "folder you launched from."
        case .runFailed(let s):
            return s
        }
    }
}

struct TrsRunner {

    /// Locate python3: try common absolute paths, then PATH via /usr/bin/env.
    static func findPython() -> String? {
        let candidates = [
            "/usr/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3"
        ]
        for p in candidates where FileManager.default.isExecutableFile(atPath: p) {
            return p
        }
        // Fall back to env-resolved python3.
        if FileManager.default.isExecutableFile(atPath: "/usr/bin/env") {
            return "/usr/bin/env"   // we'll pass "python3" as first arg
        }
        return nil
    }

    /// Locate trsextract.py: app bundle Resources, then next to the
    /// executable, then current directory.
    static func findScript() -> String? {
        let fm = FileManager.default
        if let r = Bundle.main.resourcePath {
            let p = (r as NSString).appendingPathComponent("trsextract.py")
            if fm.fileExists(atPath: p) { return p }
        }
        let exeDir = (Bundle.main.executablePath as NSString?)?
            .deletingLastPathComponent
        if let d = exeDir {
            let p = (d as NSString).appendingPathComponent("trsextract.py")
            if fm.fileExists(atPath: p) { return p }
        }
        let cwd = fm.currentDirectoryPath
        let p = (cwd as NSString).appendingPathComponent("trsextract.py")
        if fm.fileExists(atPath: p) { return p }
        return nil
    }

    /// Run trsextract with the given arguments. Returns (stdout, stderr, code).
    static func run(_ extraArgs: [String]) throws -> (String, String, Int32) {
        guard let py = findPython() else { throw TrsError.pythonNotFound }
        guard let script = findScript() else { throw TrsError.scriptNotFound }

        let proc = Process()
        var args: [String] = []
        if py.hasSuffix("/env") {
            args = ["python3", script] + extraArgs
        } else {
            args = [script] + extraArgs
        }
        proc.executableURL = URL(fileURLWithPath: py)
        proc.arguments = args

        let outPipe = Pipe()
        let errPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = errPipe

        do {
            try proc.run()
        } catch {
            throw TrsError.runFailed(error.localizedDescription)
        }
        let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
        let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()

        let out = String(data: outData, encoding: .utf8) ?? ""
        let err = String(data: errData, encoding: .utf8) ?? ""
        return (out, err, proc.terminationStatus)
    }

    /// List a disk image.
    static func list(_ image: String) throws -> ListResult {
        let (out, err, _) = try run([image])
        return parseListing(out, err: err)
    }

    /// Extract all files from an image into outDir. Returns the progress log.
    static func extract(_ image: String, to outDir: String) throws -> String {
        let (_, err, code) = try run([image, "-o", outDir])
        if code != 0 && err.contains("ERROR") {
            throw TrsError.runFailed(err)
        }
        return err   // extraction progress is printed on stderr
    }

    /// Write a host file into a COPY of the image. If `asName` is non-empty it
    /// is passed as NAME/EXT; `tokenizeBasic` selects --write-basic vs
    /// --write-file. Returns (outputImagePath, toolMessage).
    static func writeFile(_ image: String, source: String, asName: String,
                          tokenizeBasic: Bool, output: String)
        throws -> (String, String)
    {
        var args = [image]
        args += tokenizeBasic ? ["--write-basic", source]
                              : ["--write-file", source]
        if !asName.isEmpty { args += ["--as", asName] }
        args += ["-o", output]
        let (out, err, code) = try run(args)
        if code != 0 {
            throw TrsError.runFailed(err.isEmpty ? out : err)
        }
        // tool prints a "Wrote ..." line on stdout
        let msg = out.split(separator: "\n").first.map(String.init) ?? "Done."
        return (output, msg)
    }

    /// Parse the stdout listing into header lines + file rows.
    static func parseListing(_ out: String, err: String) -> ListResult {
        var header: [String] = []
        var files: [DiskFile] = []
        var inTable = false
        for line in out.split(separator: "\n", omittingEmptySubsequences: false) {
            let s = String(line)
            if s.hasPrefix("---") { inTable = true; continue }
            if s.hasPrefix("Filename") { continue }     // table header
            if s.contains(" entries.") { continue }     // footer
            if !inTable {
                if !s.trimmingCharacters(in: .whitespaces).isEmpty {
                    header.append(s)
                }
                continue
            }
            // Table row: columns are whitespace-separated; name is column 0,
            // extents is everything after the EOFoff column. Parse leniently.
            let parts = s.split(separator: " ", omittingEmptySubsequences: true)
                          .map(String.init)
            guard parts.count >= 4 else { continue }
            let name = parts[0]
            let attr = parts[1]
            let lrl = parts[2]
            let eof = parts[3]
            let extents = parts.count > 4
                ? parts[4...].joined(separator: " ") : "-"
            files.append(DiskFile(name: name, attr: attr, lrl: lrl,
                                  eofOff: eof, extents: extents))
        }
        return ListResult(header: header, files: files, rawError: err)
    }
}

// MARK: - Catalog (search across the whole collection)

/// Codable mirror of `catalog-logs.py --json` output.
struct CatalogRoot: Codable {
    let generator: String
    let disks: [CatalogDisk]
}

struct CatalogDisk: Codable, Identifiable, Hashable {
    var id: String { disk }
    let disk: String
    let source: String
    let error: String?
    let format: String
    let tracks: String
    let sides: String
    let dirtrack: String
    let note: String
    let files: [CatalogFile]
}

struct CatalogFile: Codable, Hashable {
    let name: String
    let ext: String
    let attr: String
    let standard: Bool           // is_standard() verdict from the Python side
    var full: String { ext.isEmpty ? name : "\(name)/\(ext)" }
}

/// One row in the results / detail table.
struct CatalogRow: Identifiable {
    let id = UUID()
    let file: String
    let disk: String
    let attr: String
    let standard: String         // "" or "std", for a visible column
}

final class CatalogStore: ObservableObject {
    @Published var disks: [CatalogDisk] = []
    @Published var loadedFrom: String = ""
    @Published var loadError: String = ""

    /// Locate catalog.json: last-used path, app bundle Resources, next to the
    /// executable, current directory. Same resolver idea as findScript().
    static func defaultPath(stored: String) -> String? {
        let fm = FileManager.default
        if !stored.isEmpty, fm.fileExists(atPath: stored) { return stored }
        if let r = Bundle.main.resourcePath {
            let p = (r as NSString).appendingPathComponent("catalog.json")
            if fm.fileExists(atPath: p) { return p }
        }
        if let d = (Bundle.main.executablePath as NSString?)?
            .deletingLastPathComponent {
            let p = (d as NSString).appendingPathComponent("catalog.json")
            if fm.fileExists(atPath: p) { return p }
        }
        let p = (fm.currentDirectoryPath as NSString)
            .appendingPathComponent("catalog.json")
        if fm.fileExists(atPath: p) { return p }
        return nil
    }

    func load(path: String) {
        do {
            let data = try Data(contentsOf: URL(fileURLWithPath: path))
            let root = try JSONDecoder().decode(CatalogRoot.self, from: data)
            disks = root.disks
            loadedFrom = path
            loadError = ""
        } catch {
            loadError = "Could not read catalog: \(error.localizedDescription)"
        }
    }
}

struct CatalogSearchView: View {
    @AppStorage("catalogPath") private var catalogPath: String = ""
    @StateObject private var store = CatalogStore()
    @State private var query = ""
    @State private var showStandard = false
    @State private var selectedDisk: CatalogDisk.ID? = nil

    var body: some View {
        VStack(spacing: 0) {
            searchBar
            Divider()
            if store.disks.isEmpty {
                emptyState
            } else if !trimmedQuery.isEmpty {
                resultsTable
            } else {
                browser
            }
            Divider()
            catalogFooter
        }
        .frame(minWidth: 720, minHeight: 480)
        .onAppear {
            if store.disks.isEmpty,
               let p = CatalogStore.defaultPath(stored: catalogPath) {
                store.load(path: p)
                catalogPath = store.loadedFrom
            }
        }
    }

    private var trimmedQuery: String {
        query.trimmingCharacters(in: .whitespaces)
    }

    // MARK: search

    /// All matching files across all readable disks. Case-insensitive
    /// substring on NAME/EXT - same semantics as `catalog-logs.py --find`.
    private var hits: [CatalogRow] {
        let q = trimmedQuery.lowercased()
        var out: [CatalogRow] = []
        for d in store.disks where d.error == nil {
            for f in d.files {
                if !showStandard && f.standard { continue }
                if f.full.lowercased().contains(q) {
                    out.append(CatalogRow(file: f.full, disk: d.disk,
                                          attr: f.attr,
                                          standard: f.standard ? "std" : ""))
                }
            }
        }
        return out.sorted { ($0.file, $0.disk) < ($1.file, $1.disk) }
    }

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass").foregroundColor(.secondary)
            TextField("Search files across all disks  (e.g. PACMAN or /BAS)",
                      text: $query)
                .textFieldStyle(.roundedBorder)
                .font(.system(.body, design: .monospaced))
            Toggle("Standard system files", isOn: $showStandard)
                .toggleStyle(.checkbox)
                .help("Include BOOT/SYS, DIR/SYS, SYS0…SYS21 and common "
                    + "utilities in search results and disk views.")
        }
        .padding()
    }

    private var resultsTable: some View {
        VStack(alignment: .leading, spacing: 0) {
            Table(hits) {
                TableColumn("File", value: \.file)
                TableColumn("Disk", value: \.disk)
                TableColumn("Attr", value: \.attr)
                TableColumn("", value: \.standard)
            }
            .font(.system(.body, design: .monospaced))
            Text("\(hits.count) match(es)"
                 + (showStandard ? "" : " — standard system files hidden"))
                .font(.caption).foregroundColor(.secondary)
                .padding(.horizontal).padding(.vertical, 4)
        }
    }

    // MARK: browser (empty search): disks left, files right

    private var browser: some View {
        HSplitView {
            List(selection: $selectedDisk) {
                ForEach(store.disks) { d in
                    HStack {
                        Text(d.disk)
                            .font(.system(.body, design: .monospaced))
                        Spacer()
                        if d.error != nil {
                            Image(systemName: "exclamationmark.triangle")
                                .foregroundColor(.orange)
                        } else {
                            Text("\(d.files.count)")
                                .font(.caption).foregroundColor(.secondary)
                        }
                    }
                    .tag(d.id)
                }
            }
            .frame(minWidth: 180, idealWidth: 220)
            diskDetail
        }
    }

    @ViewBuilder
    private var diskDetail: some View {
        if let d = store.disks.first(where: { $0.id == selectedDisk }) {
            VStack(alignment: .leading, spacing: 0) {
                Text(d.error == nil
                     ? "\(d.disk) — \(d.format), \(d.tracks) trk, "
                       + "\(d.sides) side(s), dir \(d.dirtrack)"
                       + (d.note.isEmpty ? "" : "  (\(d.note))")
                     : d.disk)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundColor(.secondary)
                    .padding(.horizontal).padding(.top, 6)
                if let err = d.error {
                    Text("⚠️ \(err)")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.orange)
                        .padding()
                    Spacer()
                } else {
                    Table(diskRows(d)) {
                        TableColumn("File", value: \.file)
                        TableColumn("Attr", value: \.attr)
                        TableColumn("", value: \.standard)
                    }
                    .font(.system(.body, design: .monospaced))
                }
            }
        } else {
            VStack {
                Spacer()
                Text("Select a disk — or type above to search all of them.")
                    .foregroundColor(.secondary)
                Spacer()
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func diskRows(_ d: CatalogDisk) -> [CatalogRow] {
        d.files
            .filter { showStandard || !$0.standard }
            .map { CatalogRow(file: $0.full, disk: d.disk, attr: $0.attr,
                              standard: $0.standard ? "std" : "") }
    }

    // MARK: empty state / footer

    private var emptyState: some View {
        VStack(spacing: 10) {
            Spacer()
            Image(systemName: "books.vertical")
                .font(.system(size: 40)).foregroundColor(.secondary)
            Text("No catalog loaded").font(.headline)
            Text("Generate it once from the trsextract folder:\n"
               + "./generate-logs.sh <image-dir> ./logs\n"
               + "python3 catalog-logs.py ./logs --json > catalog.json")
                .multilineTextAlignment(.center)
                .font(.system(.caption, design: .monospaced))
                .foregroundColor(.secondary)
            Button("Choose catalog.json…") { chooseCatalog() }
            if !store.loadError.isEmpty {
                Text(store.loadError)
                    .font(.caption).foregroundColor(.orange)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private var catalogFooter: some View {
        HStack {
            Text(store.loadedFrom.isEmpty
                 ? "No catalog loaded."
                 : "\(store.disks.count) disk(s) — "
                   + (store.loadedFrom as NSString).lastPathComponent)
                .font(.caption).foregroundColor(.secondary)
                .lineLimit(1).truncationMode(.middle)
                .help(store.loadedFrom)
            Spacer()
            Button("Choose catalog.json…") { chooseCatalog() }
            Button("Reload") {
                if !store.loadedFrom.isEmpty { store.load(path: store.loadedFrom) }
            }
            .disabled(store.loadedFrom.isEmpty)
        }
        .padding()
    }

    private func chooseCatalog() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if let json = UTType(filenameExtension: "json") {
            panel.allowedContentTypes = [json]
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        store.load(path: url.path)
        if store.loadError.isEmpty { catalogPath = url.path }
    }
}

// MARK: - View

struct ContentView: View {
    @State private var imagePath: String? = nil
    @State private var result: ListResult? = nil
    @State private var statusMessage: String = "Drop a .dmk or .dsk disk image to begin."
    @State private var isBusy = false
    @State private var extractLog: String = ""
    @State private var showLog = false
    @State private var dropTargeted = false
    // write support
    @State private var pendingWriteSource: String? = nil
    @State private var writeAsName: String = ""
    @State private var writeTokenizeBasic: Bool = false
    @State private var showWriteSheet = false
    @State private var writeDropTargeted = false
    @State private var writeTargetDisk: String? = nil

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let r = result {
                listingView(r)
            } else {
                startScreen
            }
            Divider()
            footer
        }
        .frame(minWidth: 720, minHeight: 480)
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("TRS-80 Disk Extract").font(.headline)
                Text(imagePath.map { ($0 as NSString).lastPathComponent }
                     ?? "No disk loaded")
                    .font(.subheadline).foregroundColor(.secondary)
            }
            Spacer()
            if isBusy { ProgressView().scaleEffect(0.7) }
        }
        .padding()
    }

    /// Start screen: two intents side by side.
    private var startScreen: some View {
        HStack(spacing: 0) {
            readZone
            Divider()
            writeZone
        }
    }

    /// LEFT — read a disk: drop a .dmk/.dsk to list & extract it.
    private var readZone: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [8]))
                .foregroundColor(dropTargeted ? .accentColor : .secondary)
                .padding()
            VStack(spacing: 10) {
                Image(systemName: "externaldrive.fill.badge.person.crop")
                    .font(.system(size: 40)).foregroundColor(.secondary)
                Text("Read a disk").font(.headline)
                Text("Drop a .dmk or .dsk image here\nto list and extract its files")
                    .multilineTextAlignment(.center)
                    .font(.caption).foregroundColor(.secondary)
                Button("Choose Disk Image…") { chooseImage() }
            }
            .padding()
        }
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            handleDrop(providers)
        }
    }

    /// RIGHT — write a file to a disk: pick the target disk, then drop the file.
    private var writeZone: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [8]))
                .foregroundColor(writeDropTargeted ? .accentColor
                                 : (writeTargetDisk != nil ? .green : .secondary))
                .padding()
            VStack(spacing: 10) {
                Image(systemName: "square.and.arrow.down.on.square")
                    .font(.system(size: 40)).foregroundColor(.secondary)
                Text("Write a file to a disk").font(.headline)
                if let disk = writeTargetDisk {
                    Text("Target: \((disk as NSString).lastPathComponent)")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.green)
                        .lineLimit(1).truncationMode(.middle)
                    Text("Now drop the file to add\n(.bas, .cmd, .txt, data…)")
                        .multilineTextAlignment(.center)
                        .font(.caption).foregroundColor(.secondary)
                    Button("Change target disk…") { chooseWriteTargetDisk() }
                        .controlSize(.small)
                } else {
                    Text("Step 1 — choose the target disk\n(an empty/formatted .dmk)")
                        .multilineTextAlignment(.center)
                        .font(.caption).foregroundColor(.secondary)
                    Button("Choose Target Disk…") { chooseWriteTargetDisk() }
                }
            }
            .padding()
        }
        .onDrop(of: [.fileURL], isTargeted: $writeDropTargeted) { providers in
            handleWriteZoneDrop(providers)
        }
    }

    private func listingView(_ r: ListResult) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(r.header, id: \.self) { line in
                Text(line).font(.system(.caption, design: .monospaced))
                    .foregroundColor(.secondary)
                    .padding(.horizontal).padding(.top, 2)
            }
            Table(r.files) {
                TableColumn("Filename", value: \.name)
                TableColumn("Attr", value: \.attr)
                TableColumn("LRL", value: \.lrl)
                TableColumn("EOF", value: \.eofOff)
                TableColumn("Extents", value: \.extents)
            }
            .font(.system(.body, design: .monospaced))
        }
    }

    private var footer: some View {
        HStack {
            Text(statusMessage).font(.caption).foregroundColor(.secondary)
                .lineLimit(1).truncationMode(.middle)
            Spacer()
            if result != nil {
                Button("Load Another…") { reset() }
                Button("Extract All…") { extractAll() }
                    .keyboardShortcut(.defaultAction).disabled(isBusy)
            }
            if !extractLog.isEmpty {
                Button("Log") { showLog = true }
            }
        }
        .padding()
        .sheet(isPresented: $showLog) {
            VStack(alignment: .leading) {
                Text("Extraction log").font(.headline)
                ScrollView {
                    Text(extractLog)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                Button("Close") { showLog = false }
            }
            .padding().frame(width: 560, height: 420)
        }
        .sheet(isPresented: $showWriteSheet) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Write file to disk image").font(.headline)
                if let src = pendingWriteSource {
                    Text("Source: \((src as NSString).lastPathComponent)")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.secondary)
                }
                HStack {
                    Text("On-disk name:")
                    TextField("NAME/EXT  (e.g. PROG/CMD)", text: $writeAsName)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                }
                Toggle("Tokenize as BASIC (source is ASCII .bas)",
                       isOn: $writeTokenizeBasic)
                Text("Writes into a COPY of the loaded image (…\u{2009}.out.dsk). "
                   + "The original is never modified.")
                    .font(.caption).foregroundColor(.secondary)
                HStack {
                    Spacer()
                    Button("Cancel") { showWriteSheet = false }
                    Button("Write") { performWrite() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(writeAsName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .padding().frame(width: 480)
            .onAppear {
                // Seed the name field within the sheet's own render cycle so the
                // Write button's .disabled() check sees the value immediately.
                // (Setting it before presentation left the button disabled until
                // an unrelated control, e.g. the toggle, forced a re-render.)
                if let src = pendingWriteSource {
                    let base = (src as NSString).lastPathComponent
                    let stem = (base as NSString).deletingPathExtension
                    let ext = (base as NSString).pathExtension
                    let name8 = String(stem.prefix(8)).uppercased()
                    let ext3 = String(ext.prefix(3)).uppercased()
                    writeAsName = ext3.isEmpty ? name8 : "\(name8)/\(ext3)"
                    writeTokenizeBasic = ext.lowercased() == "bas"
                }
            }
        }
    }

    // MARK: actions

    private func reset() {
        imagePath = nil; result = nil; extractLog = ""
        writeTargetDisk = nil; pendingWriteSource = nil
        statusMessage = "Drop a .dmk or .dsk disk image to begin."
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        _ = provider.loadObject(ofClass: URL.self) { url, _ in
            if let url = url {
                DispatchQueue.main.async { loadImage(url.path) }
            }
        }
        return true
    }

    private func chooseImage() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if let dmk = UTType(filenameExtension: "dmk"),
           let dsk = UTType(filenameExtension: "dsk") {
            panel.allowedContentTypes = [dmk, dsk]
        }
        if panel.runModal() == .OK, let url = panel.url {
            loadImage(url.path)
        }
    }

    private func loadImage(_ path: String) {
        imagePath = path
        isBusy = true
        statusMessage = "Reading directory…"
        DispatchQueue.global().async {
            do {
                let r = try TrsRunner.list(path)
                DispatchQueue.main.async {
                    result = r
                    statusMessage = "\(r.files.count) entries. "
                        + (r.header.first ?? "")
                    isBusy = false
                }
            } catch {
                DispatchQueue.main.async {
                    statusMessage = "Error: \(error.localizedDescription)"
                    isBusy = false
                }
            }
        }
    }

    // MARK: write-zone actions (two-step: target disk, then file)

    /// Step 1: choose the target disk for writing.
    private func chooseWriteTargetDisk() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = "Choose Target Disk"
        if let dmk = UTType(filenameExtension: "dmk"),
           let dsk = UTType(filenameExtension: "dsk") {
            panel.allowedContentTypes = [dmk, dsk]
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        writeTargetDisk = url.path
        statusMessage = "Target disk set. Now drop the file to add."
    }

    /// A file (disk or payload) was dropped on the WRITE zone.
    /// If no target disk is set yet and a disk image is dropped, it becomes the
    /// target. Otherwise the dropped file is treated as the payload to write.
    private func handleWriteZoneDrop(_ providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }
        _ = provider.loadObject(ofClass: URL.self) { url, _ in
            guard let url = url else { return }
            let ext = url.pathExtension.lowercased()
            let isDiskImage = ["dmk", "dsk", "hdv", "jv1", "jv3"].contains(ext)
            DispatchQueue.main.async {
                if writeTargetDisk == nil {
                    if isDiskImage {
                        writeTargetDisk = url.path
                        statusMessage = "Target disk set. Now drop the file to add."
                    } else {
                        statusMessage = "Choose the target disk first "
                            + "(an empty/formatted .dmk), then drop the file."
                    }
                    return
                }
                // target already set: this drop is the payload
                if isDiskImage {
                    statusMessage = "That's a disk image. Drop a FILE to add "
                        + "(.bas, .cmd, .txt…), or change the target disk."
                    return
                }
                prepareWriteSheet(for: url.path)
            }
        }
        return true
    }

    /// Open the write sheet for a source file. The sheet's own .onAppear
    /// populates the name field and toggle, so the Write button is correctly
    /// enabled the moment the sheet appears.
    private func prepareWriteSheet(for path: String) {
        pendingWriteSource = path
        showWriteSheet = true
    }

    private func performWrite() {
        guard let img = writeTargetDisk, let src = pendingWriteSource else { return }
        showWriteSheet = false
        let asName = writeAsName.trimmingCharacters(in: .whitespaces)
        let tok = writeTokenizeBasic
        // output: <target-stem>.out.dsk next to the target disk
        let stem = (img as NSString).deletingPathExtension
        let outPath = stem + ".out.dsk"
        isBusy = true
        statusMessage = "Writing \(asName)…"
        DispatchQueue.global().async {
            do {
                let (outImg, msg) = try TrsRunner.writeFile(
                    img, source: src, asName: asName,
                    tokenizeBasic: tok, output: outPath)
                // load the listing from the NEW image so the user sees the file
                let r = try? TrsRunner.list(outImg)
                DispatchQueue.main.async {
                    statusMessage = msg
                    if let r = r {
                        result = r
                        imagePath = outImg   // now viewing the written copy
                    }
                    isBusy = false
                    NSWorkspace.shared.activateFileViewerSelecting(
                        [URL(fileURLWithPath: outImg)])
                }
            } catch {
                DispatchQueue.main.async {
                    statusMessage = "Error: \(error.localizedDescription)"
                    extractLog = error.localizedDescription
                    isBusy = false
                }
            }
        }
    }

    private func extractAll() {
        guard let img = imagePath else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Extract Here"
        guard panel.runModal() == .OK, let dir = panel.url else { return }

        // Make a subfolder named after the disk, to avoid mixing files.
        let base = (img as NSString).lastPathComponent
        let stem = (base as NSString).deletingPathExtension
        let outDir = dir.appendingPathComponent(stem + "_extract").path

        isBusy = true
        statusMessage = "Extracting…"
        DispatchQueue.global().async {
            do {
                let log = try TrsRunner.extract(img, to: outDir)
                DispatchQueue.main.async {
                    extractLog = log
                    statusMessage = "Extracted to \(outDir)"
                    isBusy = false
                    NSWorkspace.shared.open(URL(fileURLWithPath: outDir))
                }
            } catch {
                DispatchQueue.main.async {
                    statusMessage = "Error: \(error.localizedDescription)"
                    extractLog = error.localizedDescription
                    isBusy = false
                }
            }
        }
    }
}

// MARK: - App entry

@main
struct TRS80ExtractApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                ContentView()
                    .tabItem { Label("Disk", systemImage: "externaldrive") }
                CatalogSearchView()
                    .tabItem { Label("Catalog", systemImage: "magnifyingglass") }
            }
            .padding(.top, 4)
        }
        .windowResizability(.contentSize)
    }
}
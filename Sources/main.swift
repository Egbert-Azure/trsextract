// TRS80Extract 1.2 - a SwiftUI front end for trsextract.py
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
            ContentView()
        }
        .windowResizability(.contentSize)
    }
}
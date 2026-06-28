// TRS80Extract - a SwiftUI front end for trsextract.py
// Copyright (C) 2026 Egbert Schroeer
//
// This program is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by the Free
// Software Foundation, either version 3 of the License, or (at your option)
// any later version. Distributed WITHOUT ANY WARRANTY.
// See <https://www.gnu.org/licenses/>.
//
// Option-A wrapper: shells out to `python3 trsextract.py`. Requires Python 3
// on the system and the trsextract.py script (located via the resolver below).

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

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let r = result {
                listingView(r)
            } else {
                dropZone
            }
            Divider()
            footer
        }
        .frame(minWidth: 640, minHeight: 480)
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

    private var dropZone: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [8]))
                .foregroundColor(dropTargeted ? .accentColor : .secondary)
                .padding()
            VStack(spacing: 10) {
                Image(systemName: "externaldrive.fill.badge.plus")
                    .font(.system(size: 44)).foregroundColor(.secondary)
                Text("Drop a .dmk or .dsk image here").foregroundColor(.secondary)
                Button("Choose Disk Image…") { chooseImage() }
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            handleDrop(providers)
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
    }

    // MARK: actions

    private func reset() {
        imagePath = nil; result = nil; extractLog = ""
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
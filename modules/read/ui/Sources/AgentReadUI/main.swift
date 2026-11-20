import AppKit
import AVFoundation
import Foundation
import SwiftUI

struct CLIArgs {
    let wavPath: String
    let statusPath: String
    let title: String
}

func parseArgs(_ args: [String]) -> CLIArgs? {
    var wav: String?
    var status: String?
    var title = "Reading"
    var i = 0
    while i < args.count {
        switch args[i] {
        case "--wav":
            i += 1
            guard i < args.count else { return nil }
            wav = args[i]
        case "--status":
            i += 1
            guard i < args.count else { return nil }
            status = args[i]
        case "--title":
            i += 1
            guard i < args.count else { return nil }
            title = args[i]
        default:
            break
        }
        i += 1
    }
    guard let wav, let status else { return nil }
    return CLIArgs(wavPath: wav, statusPath: status, title: title)
}

func writeStatus(_ path: String, status: String) {
    let obj: [String: String] = ["status": status]
    guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return }
    try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
}

func usageAndExit() -> Never {
    fputs("Usage: agent-read-ui --wav PATH --status PATH [--title STR]\n", stderr)
    exit(1)
}

final class PlayerModel: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var isPlaying = false
    let title: String
    let statusPath: String
    private var player: AVAudioPlayer?
    private var finished = false

    init(wavPath: String, title: String, statusPath: String) {
        self.title = title
        self.statusPath = statusPath
        super.init()
        let url = URL(fileURLWithPath: wavPath)
        do {
            player = try AVAudioPlayer(contentsOf: url)
        } catch {
            fputs("agent-read-ui: failed to load wav: \(error)\n", stderr)
            writeStatus(statusPath, status: "error")
            exit(1)
        }
        player?.delegate = self
        player?.prepareToPlay()
    }

    func start() {
        player?.play()
        isPlaying = true
    }

    func toggle() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
            isPlaying = false
        } else {
            player.play()
            isPlaying = true
        }
    }

    func stopUser() {
        guard !finished else { return }
        finished = true
        player?.stop()
        isPlaying = false
        writeStatus(statusPath, status: "stopped")
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        guard !finished else { return }
        finished = true
        isPlaying = false
        writeStatus(statusPath, status: "ok")
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }
}

struct RootView: View {
    @ObservedObject var model: PlayerModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.title)
                .font(.headline)
                .lineLimit(2)
            HStack {
                Button(model.isPlaying ? "Pause" : "Play") { model.toggle() }
                Button("Stop") { model.stopUser() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(16)
        .frame(minWidth: 280)
        .onExitCommand { model.stopUser() }
    }
}

final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var model: PlayerModel?
    var sigtermSource: DispatchSourceSignal?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let cliArgs = Array(CommandLine.arguments.dropFirst())
guard let args = parseArgs(cliArgs) else {
    usageAndExit()
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate

let model = PlayerModel(
    wavPath: args.wavPath,
    title: args.title,
    statusPath: args.statusPath
)
delegate.model = model

// SIGTERM from `agent-read stop` — DispatchSource avoids Swift-closure
// incompatibility with POSIX signal().
signal(SIGTERM, SIG_IGN)
let sigtermSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
sigtermSource.setEventHandler {
    model.stopUser()
}
sigtermSource.resume()
delegate.sigtermSource = sigtermSource

let hosting = NSHostingController(rootView: RootView(model: model))
let window = KeyableWindow(
    contentRect: NSRect(x: 0, y: 0, width: 320, height: 120),
    styleMask: [.titled, .closable, .fullSizeContentView],
    backing: .buffered,
    defer: false
)
window.title = args.title
window.titleVisibility = .hidden
window.titlebarAppearsTransparent = true
window.isReleasedWhenClosed = false
window.contentViewController = hosting
window.isMovableByWindowBackground = true
window.level = .floating
window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
window.center()
delegate.window = window

NotificationCenter.default.addObserver(
    forName: NSWindow.willCloseNotification,
    object: window,
    queue: .main
) { _ in
    model.stopUser()
}

NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
    if event.keyCode == 53 {
        model.stopUser()
        return nil
    }
    return event
}

window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)
model.start()
app.run()

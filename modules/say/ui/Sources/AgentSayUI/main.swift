import AppKit
import Foundation
import SwiftUI

// MARK: - Models

struct OptionItem: Decodable, Identifiable {
    let id: String
    let label: String
}

struct InputSpec: Decodable {
    let enabled: Bool
    let placeholder: String
    let required: Bool

    enum CodingKeys: String, CodingKey {
        case enabled, placeholder, required
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
        placeholder = try c.decodeIfPresent(String.self, forKey: .placeholder) ?? ""
        required = try c.decodeIfPresent(Bool.self, forKey: .required) ?? false
    }
}

struct PingRequest: Decodable {
    let title: String
    let body: String
    let options: [OptionItem]
    let input: InputSpec?
    let level: String

    enum CodingKeys: String, CodingKey {
        case title, body, options, input, level
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decode(String.self, forKey: .title)
        body = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
        options = try c.decodeIfPresent([OptionItem].self, forKey: .options) ?? []
        input = try c.decodeIfPresent(InputSpec.self, forKey: .input)
        level = try c.decodeIfPresent(String.self, forKey: .level) ?? "info"
    }
}

struct PingResponse: Encodable {
    let status: String
    let choice: String?
    let text: String?

    enum CodingKeys: String, CodingKey {
        case status, choice, text
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(status, forKey: .status)
        if let choice {
            try c.encode(choice, forKey: .choice)
        } else {
            try c.encodeNil(forKey: .choice)
        }
        if let text {
            try c.encode(text, forKey: .text)
        } else {
            try c.encodeNil(forKey: .text)
        }
    }
}

// MARK: - CLI

struct CLIArgs {
    let requestPath: String
    let responsePath: String
}

func parseArgs(_ args: [String]) -> CLIArgs? {
    var requestPath: String?
    var responsePath: String?
    var i = 0
    while i < args.count {
        switch args[i] {
        case "--request":
            i += 1
            guard i < args.count else { return nil }
            requestPath = args[i]
        case "--response":
            i += 1
            guard i < args.count else { return nil }
            responsePath = args[i]
        default:
            break
        }
        i += 1
    }
    guard let req = requestPath, let resp = responsePath else { return nil }
    return CLIArgs(requestPath: req, responsePath: resp)
}

func writeResponse(_ response: PingResponse, to path: String) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    do {
        let data = try encoder.encode(response)
        try data.write(to: URL(fileURLWithPath: path), options: .atomic)
    } catch {
        fputs("agent-say-ui: failed to write response: \(error)\n", stderr)
        exit(1)
    }
}

func loadRequest(from path: String) -> PingRequest {
    do {
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        return try JSONDecoder().decode(PingRequest.self, from: data)
    } catch {
        fputs("agent-say-ui: failed to read request: \(error)\n", stderr)
        exit(1)
    }
}

func usageAndExit() -> Never {
    fputs("Usage: agent-say-ui --request PATH --response PATH\n", stderr)
    exit(1)
}

// MARK: - App Kit helpers

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var responsePath: String = ""
    var responded = false

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        true
    }

    func finish(with response: PingResponse) {
        guard !responded else { return }
        responded = true
        writeResponse(response, to: responsePath)
        NSApp.terminate(nil)
    }

    func cancel() {
        finish(with: PingResponse(status: "cancelled", choice: nil, text: nil))
    }
}

final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

// MARK: - SwiftUI View

struct PingView: View {
    let request: PingRequest
    let onChoose: (String, String?) -> Void
    let onCancel: () -> Void

    @State private var text: String = ""
    @FocusState private var inputFocused: Bool

    private var inputEnabled: Bool {
        request.input?.enabled ?? false
    }

    private var inputRequired: Bool {
        (request.input?.required ?? false) && inputEnabled
    }

    private var inputReady: Bool {
        !inputRequired || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var displayOptions: [OptionItem] {
        if request.options.isEmpty {
            return [OptionItem(id: "ok", label: "OK")]
        }
        return request.options
    }

    private var accent: Color {
        switch request.level {
        case "critical": return .red
        case "warn": return .orange
        default: return .accentColor
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                Text(request.title)
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(accent)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Button(action: onCancel) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help("Cancel (Esc)")
            }

            if !request.body.isEmpty {
                Text(request.body)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }

            if inputEnabled {
                TextField(request.input?.placeholder ?? "", text: $text)
                    .textFieldStyle(.roundedBorder)
                    .focused($inputFocused)
                    .onSubmit {
                        if inputReady, let first = displayOptions.first {
                            submit(choice: first.id)
                        }
                    }
            }

            HStack(spacing: 8) {
                Spacer(minLength: 0)
                ForEach(Array(displayOptions.enumerated()), id: \.element.id) { index, option in
                    Button(option.label) {
                        submit(choice: option.id)
                    }
                    .modifier(DefaultActionIfNeeded(isDefault: index == 0))
                    .disabled(!inputReady)
                }
            }
        }
        .padding(20)
        .frame(minWidth: 360, idealWidth: 420, maxWidth: 520)
        .background(VisualEffectBackground())
        .onAppear {
            if inputEnabled {
                DispatchQueue.main.async {
                    inputFocused = true
                }
            }
        }
        .onExitCommand(perform: onCancel)
    }

    private func submit(choice: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let out: String? = inputEnabled && !trimmed.isEmpty ? trimmed : nil
        onChoose(choice, out)
    }
}

struct DefaultActionIfNeeded: ViewModifier {
    let isDefault: Bool
    func body(content: Content) -> some View {
        if isDefault {
            content.keyboardShortcut(.defaultAction)
        } else {
            content
        }
    }
}

struct VisualEffectBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

// MARK: - Entry

let cliArgs = Array(CommandLine.arguments.dropFirst())
guard let args = parseArgs(cliArgs) else {
    usageAndExit()
}

let request = loadRequest(from: args.requestPath)

let app = NSApplication.shared
app.setActivationPolicy(.regular)

let delegate = AppDelegate()
delegate.responsePath = args.responsePath
app.delegate = delegate

let content = PingView(
    request: request,
    onChoose: { choice, text in
        delegate.finish(with: PingResponse(status: "ok", choice: choice, text: text))
    },
    onCancel: {
        delegate.cancel()
    }
)

let hosting = NSHostingController(rootView: content)
let window = KeyableWindow(
    contentRect: NSRect(x: 0, y: 0, width: 420, height: 200),
    styleMask: [.titled, .closable, .fullSizeContentView],
    backing: .buffered,
    defer: false
)
window.title = request.title
window.titleVisibility = .hidden
window.titlebarAppearsTransparent = true
window.isReleasedWhenClosed = false
window.contentViewController = hosting
window.isMovableByWindowBackground = true
window.level = .floating
window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
window.center()
window.isOpaque = false
window.backgroundColor = .clear

if request.level == "critical" {
    window.level = .statusBar
}

delegate.window = window

NotificationCenter.default.addObserver(
    forName: NSWindow.willCloseNotification,
    object: window,
    queue: .main
) { _ in
    if !delegate.responded {
        delegate.cancel()
    }
}

NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
    if event.keyCode == 53 { // Escape
        delegate.cancel()
        return nil
    }
    return event
}

window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)

if request.level == "critical" {
    // Extra nudge for critical interrupts
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
        window.orderFrontRegardless()
        app.activate(ignoringOtherApps: true)
        NSApp.requestUserAttention(.criticalRequest)
    }
}

if let sound = NSSound(named: NSSound.Name("Glass")) {
    sound.play()
} else {
    NSSound.beep()
}

app.run()

// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "AgentSayUI",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "agent-say-ui", targets: ["AgentSayUI"])
    ],
    targets: [
        .executableTarget(
            name: "AgentSayUI"
        )
    ]
)

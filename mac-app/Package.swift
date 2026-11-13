// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "Stentor",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Stentor",
            path: "Sources/Stentor",
            swiftSettings: [.unsafeFlags(["-Ounchecked"])]
        ),
    ]
)

// Installer side art and DMG window background.  swift Installer/make_art.swift Installer
import AppKit
import SwiftUI

let mint = Color(red: 0.80, green: 0.93, blue: 0.86), green = Color(red: 0.40, green: 0.74, blue: 0.58)
let icon = NSImage(contentsOfFile: "Resources/AppIcon-1024.png")!

struct Mark: View {
    var size: CGFloat
    var body: some View {
        VStack(spacing: size * 0.12) {
            Image(nsImage: icon).resizable().frame(width: size * 1.6, height: size * 1.6)
            // solid jade: readable on both the light and the dark Installer window
            Text("STENTOR").font(.custom("Didot-Bold", size: size * 0.42)).tracking(size * 0.1)
                .foregroundStyle(Color(red: 0.30, green: 0.62, blue: 0.47))
        }
    }
}

/// Installer.app side art: a compact mark shown unscaled in the bottom-left corner, below the
/// list of steps (Introduction, License, Destination, Installation Type, Installation, Summary).
struct SideArt: View {
    var body: some View {
        Mark(size: 46).frame(width: 150, height: 120, alignment: .bottom).padding(.bottom, 4)
    }
}

/// DMG window background: logo + instruction + arrow towards the installer icon.
struct DMGBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.12, green: 0.13, blue: 0.15), Color(red: 0.06, green: 0.065, blue: 0.075)],
                           startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [green.opacity(0.18), .clear], center: UnitPoint(x: 0.7, y: 0.55), startRadius: 5, endRadius: 260)
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    Text("STENTOR").font(.custom("Didot-Bold", size: 40)).tracking(9)
                        .foregroundStyle(LinearGradient(colors: [mint, green], startPoint: .top, endPoint: .bottom))
                    Text("Voice restoration for macOS").font(.system(size: 13)).foregroundStyle(.white.opacity(0.7))
                    Text("Double-click  “Install Stentor”\nand follow the steps.").font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.white.opacity(0.92)).lineSpacing(3).padding(.top, 18)
                    Text("Apple Silicon · macOS 14 or later").font(.system(size: 11)).foregroundStyle(.white.opacity(0.45))
                }
                .frame(width: 330, alignment: .leading)
                Image(systemName: "arrow.right").font(.system(size: 34, weight: .light)).foregroundStyle(green.opacity(0.9))
                Spacer()
            }
            .padding(.leading, 44)
        }
        .frame(width: 640, height: 400)
    }
}

@MainActor func save<V: View>(_ v: V, _ path: String, scale: CGFloat, opaque: Bool) {
    let r = ImageRenderer(content: v)
    r.scale = scale
    r.isOpaque = opaque
    let rep = NSBitmapImageRep(data: r.nsImage!.tiffRepresentation!)!
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}

MainActor.assumeIsolated {
    let dir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Installer"
    save(SideArt(), "\(dir)/side-art.png", scale: 1, opaque: false)
    save(SideArt(), "\(dir)/side-art@2x.png", scale: 2, opaque: false)
    save(DMGBackground(), "\(dir)/dmg-background.png", scale: 1, opaque: true)
    save(DMGBackground(), "\(dir)/dmg-background@2x.png", scale: 2, opaque: true)
}

// Renders the Stentor app icon (1024 px master) and the .icns via iconutil.
//   swift Resources/make_icon.swift Resources
import AppKit
import SwiftUI

struct Icon: View {
    var body: some View {
        let mint = Color(red: 0.80, green: 0.93, blue: 0.86), green = Color(red: 0.40, green: 0.74, blue: 0.58)
        ZStack {
            // macOS icon grid: 824 pt body inside a 1024 canvas
            RoundedRectangle(cornerRadius: 185, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.13, green: 0.14, blue: 0.16), Color(red: 0.045, green: 0.05, blue: 0.06)],
                                     startPoint: .top, endPoint: .bottom))
                .overlay(
                    RadialGradient(colors: [green.opacity(0.28), .clear], center: UnitPoint(x: 0.42, y: 0.55), startRadius: 10, endRadius: 430)
                        .clipShape(RoundedRectangle(cornerRadius: 185, style: .continuous))
                )
                .overlay(RoundedRectangle(cornerRadius: 185, style: .continuous).stroke(Color.white.opacity(0.09), lineWidth: 4))
                .frame(width: 824, height: 824)
                .shadow(color: .black.opacity(0.45), radius: 24, y: 14)

            // the herald's voice: three arcs radiating to the right
            ForEach(0..<3) { i in
                Circle()
                    .trim(from: 0.40, to: 0.60)
                    .rotation(.degrees(180))
                    .stroke(green.opacity(0.85 - Double(i) * 0.22), style: StrokeStyle(lineWidth: 26 - CGFloat(i) * 4, lineCap: .round))
                    .frame(width: 270 + CGFloat(i) * 130, height: 270 + CGFloat(i) * 130)
                    .offset(x: 40)
            }

            Text("S")
                .font(.custom("Didot-Bold", size: 520))
                .foregroundStyle(LinearGradient(colors: [mint, green], startPoint: .top, endPoint: .bottom))
                .shadow(color: green.opacity(0.35), radius: 30)
                .offset(x: -80, y: 10)
        }
        .frame(width: 1024, height: 1024)
    }
}

@MainActor func png(_ size: Int) -> Data {
    let r = ImageRenderer(content: Icon().scaleEffect(CGFloat(size) / 1024).frame(width: CGFloat(size), height: CGFloat(size)))
    r.scale = 1
    r.isOpaque = false
    let rep = NSBitmapImageRep(data: r.nsImage!.tiffRepresentation!)!
    return rep.representation(using: .png, properties: [:])!
}

MainActor.assumeIsolated {
    let out = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ".")
    let set = out.appendingPathComponent("Stentor.iconset")
    try? FileManager.default.removeItem(at: set)
    try! FileManager.default.createDirectory(at: set, withIntermediateDirectories: true)
    for (pt, scales) in [(16, [1, 2]), (32, [1, 2]), (128, [1, 2]), (256, [1, 2]), (512, [1, 2])] {
        for s in scales {
            let name = s == 1 ? "icon_\(pt)x\(pt).png" : "icon_\(pt)x\(pt)@2x.png"
            try! png(pt * s).write(to: set.appendingPathComponent(name))
        }
    }
    try! png(1024).write(to: out.appendingPathComponent("AppIcon-1024.png"))
}

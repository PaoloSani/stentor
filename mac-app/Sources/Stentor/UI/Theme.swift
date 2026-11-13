import AppKit
import SwiftUI

/// Appearance chosen in Settings: follow the system, or force dark / light.
enum AppearanceMode: String, CaseIterable {
    case auto, dark, light

    var colorScheme: ColorScheme? { self == .dark ? .dark : self == .light ? .light : nil }
    var nsAppearance: NSAppearance? {
        self == .dark ? NSAppearance(named: .darkAqua) : self == .light ? NSAppearance(named: .aqua) : nil
    }
    static var current: AppearanceMode { AppearanceMode(rawValue: UserDefaults.standard.string(forKey: "appearance") ?? "") ?? .auto }
}

extension Color {
    /// A colour with dark and light variants, resolved from the view's appearance.
    static func adaptive(dark: (Double, Double, Double, Double), light: (Double, Double, Double, Double)) -> Color {
        Color(nsColor: NSColor(name: nil) { ap in
            let c = ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: c.0, green: c.1, blue: c.2, alpha: c.3)
        })
    }
}

enum Theme {
    // surfaces
    static let bg = Color.adaptive(dark: (0.075, 0.078, 0.09, 1), light: (0.945, 0.948, 0.955, 1))
    static let lane = Color.adaptive(dark: (0.095, 0.1, 0.115, 1), light: (0.985, 0.986, 0.99, 1))
    static let header = Color.adaptive(dark: (0.085, 0.088, 0.1, 1), light: (0.915, 0.92, 0.93, 1))
    static let island = Color.adaptive(dark: (0.12, 0.125, 0.145, 0.95), light: (1, 1, 1, 0.96))
    static let card = Color.adaptive(dark: (0.135, 0.14, 0.16, 0.98), light: (1, 1, 1, 0.99))

    /// Foreground ink (white on dark, black on light) — use with opacity for fills, strokes, grids.
    static let ink = Color.adaptive(dark: (1, 1, 1, 1), light: (0, 0, 0, 1))
    static let text = Color.adaptive(dark: (1, 1, 1, 0.86), light: (0.08, 0.09, 0.1, 0.9))
    static let muted = Color.adaptive(dark: (1, 1, 1, 0.48), light: (0, 0, 0, 0.5))
    static let grid = Color.adaptive(dark: (1, 1, 1, 0.06), light: (0, 0, 0, 0.07))
    /// Text on a `text`-coloured fill (selected segment of a switch, play button).
    static let inverse = Color.adaptive(dark: (0.08, 0.085, 0.1, 1), light: (1, 1, 1, 1))
    /// Text on accent (green / amber) fills.
    static let onAccent = Color.adaptive(dark: (0.04, 0.06, 0.05, 0.9), light: (1, 1, 1, 1))

    // signal
    static let wave = Color.adaptive(dark: (0.55, 0.6, 0.68, 1), light: (0.36, 0.4, 0.48, 1))
    static let waveEnh = Color.adaptive(dark: (0.74, 0.67, 0.93, 1), light: (0.47, 0.36, 0.74, 1))

    // accents — a soft jade instead of an acid green
    static let speech = Color.adaptive(dark: (0.40, 0.74, 0.58, 1), light: (0.20, 0.55, 0.42, 1))
    static let accent = speech
    static let loop = Color.adaptive(dark: (0.98, 0.72, 0.32, 1), light: (0.84, 0.53, 0.1, 1))
    static let danger = Color.adaptive(dark: (0.98, 0.42, 0.4, 1), light: (0.86, 0.24, 0.22, 1))

    /// Wordmark gradient (top -> bottom).
    static let wordTop = Color.adaptive(dark: (0.80, 0.93, 0.86, 1), light: (0.33, 0.62, 0.50, 1))
    static let wordBottom = Color.adaptive(dark: (0.40, 0.74, 0.58, 1), light: (0.15, 0.44, 0.33, 1))

    static let rulerHeight: CGFloat = 22
    static let xZone: CGFloat = 20 // top of a bar where the remove badge appears
    /// User-selected icon size (Settings > Appearance), read where views can't observe @AppStorage.
    static var iconScale: CGFloat { CGFloat(UserDefaults.standard.object(forKey: "iconScale") as? Double ?? 1.0) }
}

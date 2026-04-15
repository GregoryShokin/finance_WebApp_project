import Foundation
import SwiftUI

// MARK: - Decimal Formatting

extension Decimal {
    var currencyFormatted: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        formatter.groupingSeparator = " "
        return (formatter.string(from: self as NSDecimalNumber) ?? "0.00") + " " + Constants.Currency.symbol
    }

    var shortFormatted: String {
        let doubleValue = NSDecimalNumber(decimal: self).doubleValue
        if abs(doubleValue) >= 1_000_000 {
            return String(format: "%.1fM", doubleValue / 1_000_000)
        } else if abs(doubleValue) >= 1_000 {
            return String(format: "%.1fK", doubleValue / 1_000)
        }
        return String(format: "%.0f", doubleValue)
    }
}

// MARK: - Date Formatting

extension Date {
    var displayFormatted: String {
        let formatter = DateFormatter()
        formatter.dateFormat = Constants.DateFormats.display
        return formatter.string(from: self)
    }

    var monthYearFormatted: String {
        let formatter = DateFormatter()
        formatter.dateFormat = Constants.DateFormats.monthYear
        formatter.locale = Locale(identifier: "ru_RU")
        return formatter.string(from: self).capitalized
    }

    var apiMonthFormatted: String {
        let formatter = DateFormatter()
        formatter.dateFormat = Constants.DateFormats.apiMonth
        return formatter.string(from: self)
    }

    var iso8601String: String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: self)
    }

    var startOfMonth: Date {
        Calendar.current.date(from: Calendar.current.dateComponents([.year, .month], from: self))!
    }
}

// MARK: - Color Helpers

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 6:
            (a, r, g, b) = (255, (int >> 16) & 0xFF, (int >> 8) & 0xFF, int & 0xFF)
        case 8:
            (a, r, g, b) = ((int >> 24) & 0xFF, (int >> 16) & 0xFF, (int >> 8) & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (255, 0, 0, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }

    static let appPrimary = Color(hex: "2563EB")
    static let appSuccess = Color(hex: "16A34A")
    static let appDanger = Color(hex: "DC2626")
    static let appWarning = Color(hex: "F59E0B")
    static let appBackground = Color(UIColor.systemGroupedBackground)
    static let appCardBackground = Color(UIColor.secondarySystemGroupedBackground)
}

// MARK: - View Modifiers

struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding()
            .background(Color.appCardBackground)
            .cornerRadius(12)
            .shadow(color: .black.opacity(0.05), radius: 2, y: 1)
    }
}

extension View {
    func cardStyle() -> some View {
        modifier(CardModifier())
    }
}

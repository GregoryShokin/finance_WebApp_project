import Foundation

enum Constants {
    // Change this to your server's URL
    static let baseURL = "http://localhost:8000/api/v1"

    static let keychainTokenKey = "finance_app_access_token"

    enum DateFormats {
        static let iso8601 = "yyyy-MM-dd'T'HH:mm:ss"
        static let display = "dd.MM.yyyy"
        static let monthYear = "MMMM yyyy"
        static let apiMonth = "yyyy-MM"
    }

    enum Currency {
        static let defaultCode = "RUB"
        static let symbol = "\u{20BD}" // ₽
    }
}

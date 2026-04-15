import Foundation
import SwiftUI

enum CategoryKind: String, Codable {
    case income
    case expense
}

enum CategoryPriority: String, Codable, CaseIterable {
    case expenseEssential = "expense_essential"
    case expenseSecondary = "expense_secondary"
    case expenseTarget = "expense_target"
    case incomeActive = "income_active"
    case incomePassive = "income_passive"

    var displayName: String {
        switch self {
        case .expenseEssential: return "Обязательные"
        case .expenseSecondary: return "Второстепенные"
        case .expenseTarget: return "Целевые"
        case .incomeActive: return "Активный доход"
        case .incomePassive: return "Пассивный доход"
        }
    }

    var color: Color {
        switch self {
        case .expenseEssential: return .appDanger
        case .expenseSecondary: return .appWarning
        case .expenseTarget: return .appPrimary
        case .incomeActive: return .appSuccess
        case .incomePassive: return .mint
        }
    }
}

struct Category: Codable, Identifiable {
    let id: Int
    let userId: Int
    let name: String
    let kind: CategoryKind
    let priority: CategoryPriority
    let color: String?
    let iconName: String
    let isSystem: Bool
    let excludeFromPlanning: Bool
    let incomeType: String?
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, kind, priority, color
        case userId = "user_id"
        case iconName = "icon_name"
        case isSystem = "is_system"
        case excludeFromPlanning = "exclude_from_planning"
        case incomeType = "income_type"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    var sfSymbolName: String {
        iconMapping[iconName] ?? "tag"
    }
}

struct CategoryCreateRequest: Codable {
    var name: String
    var kind: CategoryKind
    var priority: CategoryPriority
    var isSystem: Bool = false
    var excludeFromPlanning: Bool = false
    var incomeType: String?

    enum CodingKeys: String, CodingKey {
        case name, kind, priority
        case isSystem = "is_system"
        case excludeFromPlanning = "exclude_from_planning"
        case incomeType = "income_type"
    }
}

private let iconMapping: [String: String] = [
    "tag": "tag",
    "home": "house",
    "cart": "cart",
    "car": "car",
    "heart": "heart",
    "star": "star",
    "briefcase": "briefcase",
    "gift": "gift",
    "food": "fork.knife",
    "plane": "airplane",
    "book": "book",
    "music": "music.note",
    "film": "film",
    "phone": "phone",
    "wifi": "wifi",
    "creditcard": "creditcard",
    "banknote": "banknote",
    "chart": "chart.bar",
    "person": "person",
    "shield": "shield",
    "wrench": "wrench",
    "leaf": "leaf",
    "drop": "drop",
    "flame": "flame",
    "bolt": "bolt",
    "pills": "pills",
    "graduation": "graduationcap",
    "baby": "figure.and.child.holdinghands",
    "pet": "pawprint",
    "gym": "dumbbell",
    "gamepad": "gamecontroller",
    "palette": "paintpalette",
]

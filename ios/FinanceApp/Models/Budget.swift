import Foundation

struct BudgetProgress: Codable, Identifiable {
    var id: Int { categoryId }

    let categoryId: Int
    let categoryName: String
    let categoryKind: CategoryKind
    let categoryPriority: CategoryPriority
    let incomeType: String?
    let excludeFromPlanning: Bool
    let plannedAmount: Decimal
    let suggestedAmount: Decimal
    let spentAmount: Decimal
    let remaining: Decimal
    let percentUsed: Double

    enum CodingKeys: String, CodingKey {
        case categoryId = "category_id"
        case categoryName = "category_name"
        case categoryKind = "category_kind"
        case categoryPriority = "category_priority"
        case incomeType = "income_type"
        case excludeFromPlanning = "exclude_from_planning"
        case plannedAmount = "planned_amount"
        case suggestedAmount = "suggested_amount"
        case spentAmount = "spent_amount"
        case remaining
        case percentUsed = "percent_used"
    }
}

struct BudgetAlert: Codable, Identifiable {
    let id: Int
    let alertType: String
    let categoryId: Int?
    let message: String
    let triggeredAt: Date
    let isRead: Bool

    enum CodingKeys: String, CodingKey {
        case id, message
        case alertType = "alert_type"
        case categoryId = "category_id"
        case triggeredAt = "triggered_at"
        case isRead = "is_read"
    }
}

struct FinancialIndependence: Codable {
    let passiveIncome: Decimal
    let activeIncome: Decimal
    let totalExpenses: Decimal
    let percent: Double
    let status: String

    enum CodingKeys: String, CodingKey {
        case percent, status
        case passiveIncome = "passive_income"
        case activeIncome = "active_income"
        case totalExpenses = "total_expenses"
    }
}

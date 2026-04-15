import Foundation

enum TransactionType: String, Codable {
    case income
    case expense
}

enum OperationType: String, Codable, CaseIterable {
    case regular
    case transfer
    case investmentBuy = "investment_buy"
    case investmentSell = "investment_sell"
    case creditDisbursement = "credit_disbursement"
    case creditPayment = "credit_payment"
    case creditEarlyRepayment = "credit_early_repayment"
    case creditInterest = "credit_interest"
    case debt
    case refund
    case adjustment

    var displayName: String {
        switch self {
        case .regular: return "Обычная"
        case .transfer: return "Перевод"
        case .investmentBuy: return "Покупка инвестиций"
        case .investmentSell: return "Продажа инвестиций"
        case .creditDisbursement: return "Выдача кредита"
        case .creditPayment: return "Платёж по кредиту"
        case .creditEarlyRepayment: return "Досрочное погашение"
        case .creditInterest: return "Проценты по кредиту"
        case .debt: return "Долг"
        case .refund: return "Возврат"
        case .adjustment: return "Корректировка"
        }
    }
}

enum DebtDirection: String, Codable {
    case lent
    case borrowed
    case repaid
    case collected
}

struct Transaction: Codable, Identifiable {
    let id: Int
    let userId: Int
    let accountId: Int
    let targetAccountId: Int?
    let creditAccountId: Int?
    let categoryId: Int?
    let counterpartyId: Int?
    let goalId: Int?
    let amount: Decimal
    let currency: String
    let type: TransactionType
    let operationType: OperationType
    let creditPrincipalAmount: Decimal?
    let creditInterestAmount: Decimal?
    let debtDirection: DebtDirection?
    let description: String?
    let normalizedDescription: String?
    let transactionDate: Date
    let needsReview: Bool
    let affectsAnalytics: Bool
    let transferPairId: Int?
    let createdAt: Date
    let updatedAt: Date

    // Joined fields
    let categoryName: String?
    let accountName: String?

    enum CodingKeys: String, CodingKey {
        case id, amount, currency, type, description
        case userId = "user_id"
        case accountId = "account_id"
        case targetAccountId = "target_account_id"
        case creditAccountId = "credit_account_id"
        case categoryId = "category_id"
        case counterpartyId = "counterparty_id"
        case goalId = "goal_id"
        case operationType = "operation_type"
        case creditPrincipalAmount = "credit_principal_amount"
        case creditInterestAmount = "credit_interest_amount"
        case debtDirection = "debt_direction"
        case normalizedDescription = "normalized_description"
        case transactionDate = "transaction_date"
        case needsReview = "needs_review"
        case affectsAnalytics = "affects_analytics"
        case transferPairId = "transfer_pair_id"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case categoryName = "category_name"
        case accountName = "account_name"
    }
}

struct TransactionCreateRequest: Codable {
    var accountId: Int
    var targetAccountId: Int?
    var creditAccountId: Int?
    var categoryId: Int?
    var counterpartyId: Int?
    var goalId: Int?
    var amount: Decimal
    var currency: String = Constants.Currency.defaultCode
    var type: TransactionType
    var operationType: OperationType = .regular
    var debtDirection: DebtDirection?
    var description: String?
    var transactionDate: Date

    enum CodingKeys: String, CodingKey {
        case amount, currency, type, description
        case accountId = "account_id"
        case targetAccountId = "target_account_id"
        case creditAccountId = "credit_account_id"
        case categoryId = "category_id"
        case counterpartyId = "counterparty_id"
        case goalId = "goal_id"
        case operationType = "operation_type"
        case debtDirection = "debt_direction"
        case transactionDate = "transaction_date"
    }
}

import Foundation

enum AccountType: String, Codable, CaseIterable {
    case regular
    case credit
    case creditCard = "credit_card"
    case cash
    case broker
    case deposit
}

struct Account: Codable, Identifiable {
    let id: Int
    let userId: Int
    let name: String
    let currency: String
    let balance: Decimal
    let isActive: Bool
    let accountType: AccountType
    let isCredit: Bool

    // Credit fields
    let creditLimitOriginal: Decimal?
    let creditCurrentAmount: Decimal?
    let creditInterestRate: Decimal?
    let creditTermRemaining: Int?
    let monthlyPayment: Decimal?

    // Deposit fields
    let depositInterestRate: Decimal?
    let depositOpenDate: String?
    let depositCloseDate: String?
    let depositCapitalizationPeriod: String?

    // Identifiers
    let contractNumber: String?
    let statementAccountNumber: String?

    let lastTransactionDate: String?
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, currency, balance
        case userId = "user_id"
        case isActive = "is_active"
        case accountType = "account_type"
        case isCredit = "is_credit"
        case creditLimitOriginal = "credit_limit_original"
        case creditCurrentAmount = "credit_current_amount"
        case creditInterestRate = "credit_interest_rate"
        case creditTermRemaining = "credit_term_remaining"
        case monthlyPayment = "monthly_payment"
        case depositInterestRate = "deposit_interest_rate"
        case depositOpenDate = "deposit_open_date"
        case depositCloseDate = "deposit_close_date"
        case depositCapitalizationPeriod = "deposit_capitalization_period"
        case contractNumber = "contract_number"
        case statementAccountNumber = "statement_account_number"
        case lastTransactionDate = "last_transaction_date"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct AccountCreateRequest: Codable {
    var name: String
    var currency: String = Constants.Currency.defaultCode
    var balance: Decimal = 0
    var isActive: Bool = true
    var accountType: AccountType = .regular
    var isCredit: Bool = false
    var creditLimitOriginal: Decimal?
    var creditCurrentAmount: Decimal?
    var creditInterestRate: Decimal?
    var creditTermRemaining: Int?
    var monthlyPayment: Decimal?
    var depositInterestRate: Decimal?
    var contractNumber: String?

    enum CodingKeys: String, CodingKey {
        case name, currency, balance
        case isActive = "is_active"
        case accountType = "account_type"
        case isCredit = "is_credit"
        case creditLimitOriginal = "credit_limit_original"
        case creditCurrentAmount = "credit_current_amount"
        case creditInterestRate = "credit_interest_rate"
        case creditTermRemaining = "credit_term_remaining"
        case monthlyPayment = "monthly_payment"
        case depositInterestRate = "deposit_interest_rate"
        case contractNumber = "contract_number"
    }
}

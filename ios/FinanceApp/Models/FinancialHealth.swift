import Foundation

struct FinancialHealth: Codable {
    let savingsRate: Double?
    let avgSavingsRate: Double?
    let savingsRateZone: String?
    let monthlyAvgBalance: Decimal?
    let monthsCalculated: Int?
    let dailyLimit: Decimal?
    let dailyLimitWithCarry: Decimal?
    let carryOverDays: Int?
    let dti: Double?
    let dtiZone: String?
    let dtiTotalPayments: Decimal?
    let dtiIncome: Decimal?
    let leverage: Double?
    let leverageZone: String?
    let leverageTotalDebt: Decimal?
    let leverageOwnCapital: Decimal?
    let realAssetsTotal: Decimal?
    let disciplineScore: Double?
    let disciplineZone: String?
    let fiPercent: Double?
    let fiZone: String?
    let fiCapitalNeeded: Decimal?
    let fiPassiveIncome: Decimal?

    enum CodingKeys: String, CodingKey {
        case savingsRate = "savings_rate"
        case avgSavingsRate = "avg_savings_rate"
        case savingsRateZone = "savings_rate_zone"
        case monthlyAvgBalance = "monthly_avg_balance"
        case monthsCalculated = "months_calculated"
        case dailyLimit = "daily_limit"
        case dailyLimitWithCarry = "daily_limit_with_carry"
        case carryOverDays = "carry_over_days"
        case dti
        case dtiZone = "dti_zone"
        case dtiTotalPayments = "dti_total_payments"
        case dtiIncome = "dti_income"
        case leverage
        case leverageZone = "leverage_zone"
        case leverageTotalDebt = "leverage_total_debt"
        case leverageOwnCapital = "leverage_own_capital"
        case realAssetsTotal = "real_assets_total"
        case disciplineScore = "discipline_score"
        case disciplineZone = "discipline_zone"
        case fiPercent = "fi_percent"
        case fiZone = "fi_zone"
        case fiCapitalNeeded = "fi_capital_needed"
        case fiPassiveIncome = "fi_passive_income"
    }
}

struct RealAsset: Codable, Identifiable {
    let id: Int
    let assetType: String
    let name: String
    let estimatedValue: Decimal
    let linkedAccountId: Int?
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name
        case assetType = "asset_type"
        case estimatedValue = "estimated_value"
        case linkedAccountId = "linked_account_id"
        case updatedAt = "updated_at"
    }
}

struct Counterparty: Codable, Identifiable {
    let id: Int
    let userId: Int
    let name: String
    let receivableAmount: Decimal?
    let payableAmount: Decimal?
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name
        case userId = "user_id"
        case receivableAmount = "receivable_amount"
        case payableAmount = "payable_amount"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct Metrics: Codable {
    let financialIndependence: FinancialIndependence?
    let savingsRate: SavingsRateMetric

    enum CodingKeys: String, CodingKey {
        case financialIndependence = "financial_independence"
        case savingsRate = "savings_rate"
    }
}

struct SavingsRateMetric: Codable {
    let percent: Double
    let invested: Decimal
    let totalIncome: Decimal

    enum CodingKeys: String, CodingKey {
        case percent, invested
        case totalIncome = "total_income"
    }
}

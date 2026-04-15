import Foundation

enum GoalStatus: String, Codable {
    case active
    case achieved
    case archived
}

struct Goal: Codable, Identifiable {
    let id: Int
    let userId: Int
    let name: String
    let targetAmount: Decimal
    let deadline: String?
    let status: GoalStatus
    let isSystem: Bool
    let systemKey: String?
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, status, deadline
        case userId = "user_id"
        case targetAmount = "target_amount"
        case isSystem = "is_system"
        case systemKey = "system_key"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct GoalWithProgress: Codable, Identifiable {
    let id: Int
    let userId: Int
    let name: String
    let targetAmount: Decimal
    let deadline: String?
    let status: GoalStatus
    let isSystem: Bool
    let systemKey: String?
    let savedAmount: Decimal
    let percent: Double
    let remaining: Decimal
    let monthlyNeeded: Decimal?
    let isOnTrack: Bool?
    let shortfall: Decimal?
    let estimatedDate: String?
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, name, status, deadline, percent, remaining
        case userId = "user_id"
        case targetAmount = "target_amount"
        case isSystem = "is_system"
        case systemKey = "system_key"
        case savedAmount = "saved_amount"
        case monthlyNeeded = "monthly_needed"
        case isOnTrack = "is_on_track"
        case shortfall
        case estimatedDate = "estimated_date"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct GoalCreateRequest: Codable {
    var name: String
    var targetAmount: Decimal
    var deadline: String?

    enum CodingKeys: String, CodingKey {
        case name
        case targetAmount = "target_amount"
        case deadline
    }
}

struct GoalForecast: Codable {
    let monthlyAvgBalance: Decimal?
    let monthlyNeeded: Decimal?
    let estimatedMonths: Int?
    let estimatedDate: String?
    let isAchievable: Bool
    let shortfall: Decimal?
    let suggestedDate: String?
    let contributionPercent: Double?
    let deadlineTooClose: Bool?

    enum CodingKeys: String, CodingKey {
        case monthlyAvgBalance = "monthly_avg_balance"
        case monthlyNeeded = "monthly_needed"
        case estimatedMonths = "estimated_months"
        case estimatedDate = "estimated_date"
        case isAchievable = "is_achievable"
        case shortfall
        case suggestedDate = "suggested_date"
        case contributionPercent = "contribution_percent"
        case deadlineTooClose = "deadline_too_close"
    }
}

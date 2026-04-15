import Foundation

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var recentTransactions: [Transaction] = []
    @Published var goals: [GoalWithProgress] = []
    @Published var budgetProgress: [BudgetProgress] = []
    @Published var metrics: Metrics?
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api = APIClient.shared

    var totalBalance: Decimal {
        accounts.filter { $0.isActive && !$0.isCredit }.reduce(0) { $0 + $1.balance }
    }

    var totalDebt: Decimal {
        accounts.filter { $0.isCredit }.reduce(0) { $0 + ($1.creditCurrentAmount ?? 0) }
    }

    var monthlyIncome: Decimal {
        recentTransactions
            .filter { $0.type == .income && isCurrentMonth($0.transactionDate) }
            .reduce(0) { $0 + $1.amount }
    }

    var monthlyExpenses: Decimal {
        recentTransactions
            .filter { $0.type == .expense && isCurrentMonth($0.transactionDate) }
            .reduce(0) { $0 + $1.amount }
    }

    var activeGoalsCount: Int {
        goals.filter { $0.status == .active }.count
    }

    func loadDashboard() async {
        isLoading = true
        errorMessage = nil

        async let accountsTask: [Account] = api.get(path: "/accounts")
        async let transactionsTask: [Transaction] = api.get(path: "/transactions")
        async let goalsTask: [GoalWithProgress] = api.get(path: "/goals")

        let month = Date().startOfMonth
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let monthStr = formatter.string(from: month)
        async let budgetTask: [BudgetProgress] = api.get(path: "/budget/\(monthStr)")

        let monthParam = Date().apiMonthFormatted
        async let metricsTask: Metrics = api.get(
            path: "/metrics",
            queryItems: [URLQueryItem(name: "month", value: monthParam)]
        )

        do {
            accounts = try await accountsTask
            recentTransactions = try await transactionsTask
            goals = try await goalsTask
            budgetProgress = try await budgetTask
            metrics = try await metricsTask
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func isCurrentMonth(_ date: Date) -> Bool {
        Calendar.current.isDate(date, equalTo: Date(), toGranularity: .month)
    }
}

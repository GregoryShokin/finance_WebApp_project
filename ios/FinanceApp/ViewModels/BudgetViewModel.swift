import Foundation

@MainActor
final class BudgetViewModel: ObservableObject {
    @Published var budgetItems: [BudgetProgress] = []
    @Published var alerts: [BudgetAlert] = []
    @Published var fiMetrics: FinancialIndependence?
    @Published var selectedMonth: Date = Date().startOfMonth
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api = APIClient.shared

    var expenseItems: [BudgetProgress] {
        budgetItems.filter { $0.categoryKind == .expense }
    }

    var incomeItems: [BudgetProgress] {
        budgetItems.filter { $0.categoryKind == .income }
    }

    var totalPlanned: Decimal {
        expenseItems.reduce(0) { $0 + $1.plannedAmount }
    }

    var totalSpent: Decimal {
        expenseItems.reduce(0) { $0 + $1.spentAmount }
    }

    var unreadAlertsCount: Int {
        alerts.filter { !$0.isRead }.count
    }

    func loadBudget() async {
        isLoading = true
        errorMessage = nil

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let monthStr = formatter.string(from: selectedMonth)

        do {
            async let budgetTask: [BudgetProgress] = api.get(path: "/budget/\(monthStr)")
            async let alertsTask: [BudgetAlert] = api.get(path: "/budget/alerts")
            async let fiTask: FinancialIndependence = api.get(path: "/budget/financial-independence/\(monthStr)")

            budgetItems = try await budgetTask
            alerts = try await alertsTask
            fiMetrics = try await fiTask
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func updateBudget(categoryId: Int, amount: Decimal) async {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let monthStr = formatter.string(from: selectedMonth)

        do {
            let body = ["planned_amount": amount]
            let _: BudgetProgress = try await api.put(
                path: "/budget/\(monthStr)/\(categoryId)",
                body: body
            )
            await loadBudget()
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func markAlertRead(_ id: Int) async {
        do {
            let _: BudgetAlert = try await api.post(path: "/budget/alerts/\(id)/read")
            if let index = alerts.firstIndex(where: { $0.id == id }) {
                alerts.remove(at: index)
            }
        } catch {}
    }

    func goToPreviousMonth() {
        selectedMonth = Calendar.current.date(byAdding: .month, value: -1, to: selectedMonth) ?? selectedMonth
        Task { await loadBudget() }
    }

    func goToNextMonth() {
        selectedMonth = Calendar.current.date(byAdding: .month, value: 1, to: selectedMonth) ?? selectedMonth
        Task { await loadBudget() }
    }
}

import Foundation

@MainActor
final class TransactionsViewModel: ObservableObject {
    @Published var transactions: [Transaction] = []
    @Published var accounts: [Account] = []
    @Published var categories: [Category] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var showingCreateForm = false

    // Filters
    @Published var selectedAccountId: Int?
    @Published var selectedCategoryId: Int?
    @Published var selectedType: TransactionType?
    @Published var dateFrom: Date?
    @Published var dateTo: Date?
    @Published var searchText = ""

    private let api = APIClient.shared

    var filteredTransactions: [Transaction] {
        var result = transactions
        if !searchText.isEmpty {
            result = result.filter {
                ($0.description ?? "").localizedCaseInsensitiveContains(searchText)
            }
        }
        return result
    }

    var groupedByDate: [(String, [Transaction])] {
        let grouped = Dictionary(grouping: filteredTransactions) { tx in
            tx.transactionDate.displayFormatted
        }
        return grouped.sorted { $0.key > $1.key }
    }

    func loadTransactions() async {
        isLoading = true
        errorMessage = nil

        var queryItems: [URLQueryItem] = []
        if let accountId = selectedAccountId {
            queryItems.append(URLQueryItem(name: "account_id", value: "\(accountId)"))
        }
        if let categoryId = selectedCategoryId {
            queryItems.append(URLQueryItem(name: "category_id", value: "\(categoryId)"))
        }
        if let type = selectedType {
            queryItems.append(URLQueryItem(name: "type", value: type.rawValue))
        }
        if let dateFrom {
            queryItems.append(URLQueryItem(name: "date_from", value: dateFrom.iso8601String))
        }
        if let dateTo {
            queryItems.append(URLQueryItem(name: "date_to", value: dateTo.iso8601String))
        }

        do {
            async let txTask: [Transaction] = api.get(
                path: "/transactions",
                queryItems: queryItems.isEmpty ? nil : queryItems
            )
            async let accTask: [Account] = api.get(path: "/accounts")
            async let catTask: [Category] = api.get(path: "/categories")

            transactions = try await txTask
            accounts = try await accTask
            categories = try await catTask
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func createTransaction(_ request: TransactionCreateRequest) async -> Bool {
        do {
            let _: Transaction = try await api.post(path: "/transactions", body: request)
            await loadTransactions()
            return true
        } catch let error as APIError {
            errorMessage = error.errorDescription
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteTransaction(_ id: Int) async {
        do {
            let _: [String: Bool] = try await api.request("DELETE", path: "/transactions/\(id)")
            transactions.removeAll { $0.id == id }
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func accountName(for id: Int) -> String {
        accounts.first { $0.id == id }?.name ?? "—"
    }

    func categoryName(for id: Int?) -> String {
        guard let id else { return "Без категории" }
        return categories.first { $0.id == id }?.name ?? "—"
    }
}

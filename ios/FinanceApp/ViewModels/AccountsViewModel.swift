import Foundation

@MainActor
final class AccountsViewModel: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var realAssets: [RealAsset] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var showingCreateForm = false

    private let api = APIClient.shared

    var regularAccounts: [Account] {
        accounts.filter { !$0.isCredit && $0.accountType != .deposit }
    }

    var creditAccounts: [Account] {
        accounts.filter { $0.isCredit || $0.accountType == .credit || $0.accountType == .creditCard }
    }

    var depositAccounts: [Account] {
        accounts.filter { $0.accountType == .deposit }
    }

    var totalBalance: Decimal {
        regularAccounts.filter(\.isActive).reduce(0) { $0 + $1.balance }
    }

    var totalDebt: Decimal {
        creditAccounts.reduce(0) { $0 + ($1.creditCurrentAmount ?? 0) }
    }

    func loadAccounts() async {
        isLoading = true
        errorMessage = nil

        do {
            async let accountsReq: [Account] = api.get(path: "/accounts")
            async let assetsReq: [RealAsset] = api.get(path: "/real-assets")
            accounts = try await accountsReq
            realAssets = try await assetsReq
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func createAccount(_ request: AccountCreateRequest) async -> Bool {
        do {
            let _: Account = try await api.post(path: "/accounts", body: request)
            await loadAccounts()
            return true
        } catch let error as APIError {
            errorMessage = error.errorDescription
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteAccount(_ id: Int) async {
        do {
            try await api.delete(path: "/accounts/\(id)")
            accounts.removeAll { $0.id == id }
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

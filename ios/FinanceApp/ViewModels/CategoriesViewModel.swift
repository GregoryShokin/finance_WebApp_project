import Foundation

@MainActor
final class CategoriesViewModel: ObservableObject {
    @Published var categories: [Category] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var showingCreateForm = false
    @Published var selectedKind: CategoryKind = .expense

    private let api = APIClient.shared

    var filteredCategories: [Category] {
        categories.filter { $0.kind == selectedKind }
    }

    var groupedByPriority: [(CategoryPriority, [Category])] {
        let grouped = Dictionary(grouping: filteredCategories) { $0.priority }
        let order: [CategoryPriority] = selectedKind == .expense
            ? [.expenseEssential, .expenseSecondary, .expenseTarget]
            : [.incomeActive, .incomePassive]
        return order.compactMap { priority in
            guard let cats = grouped[priority], !cats.isEmpty else { return nil }
            return (priority, cats)
        }
    }

    func loadCategories() async {
        isLoading = true
        errorMessage = nil

        do {
            categories = try await api.get(path: "/categories")
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func createCategory(_ request: CategoryCreateRequest) async -> Bool {
        do {
            let _: Category = try await api.post(path: "/categories", body: request)
            await loadCategories()
            return true
        } catch let error as APIError {
            errorMessage = error.errorDescription
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteCategory(_ id: Int) async {
        do {
            try await api.delete(path: "/categories/\(id)")
            categories.removeAll { $0.id == id }
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

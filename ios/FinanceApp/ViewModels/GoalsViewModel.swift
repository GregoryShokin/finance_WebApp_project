import Foundation

@MainActor
final class GoalsViewModel: ObservableObject {
    @Published var goals: [GoalWithProgress] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var showingCreateForm = false

    private let api = APIClient.shared

    var activeGoals: [GoalWithProgress] {
        goals.filter { $0.status == .active }
    }

    var achievedGoals: [GoalWithProgress] {
        goals.filter { $0.status == .achieved }
    }

    var archivedGoals: [GoalWithProgress] {
        goals.filter { $0.status == .archived }
    }

    func loadGoals() async {
        isLoading = true
        errorMessage = nil

        do {
            goals = try await api.get(path: "/goals")
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func createGoal(_ request: GoalCreateRequest) async -> Bool {
        do {
            let _: Goal = try await api.post(path: "/goals", body: request)
            await loadGoals()
            return true
        } catch let error as APIError {
            errorMessage = error.errorDescription
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func archiveGoal(_ id: Int) async {
        do {
            let _: Goal = try await api.post(path: "/goals/\(id)/archive")
            await loadGoals()
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

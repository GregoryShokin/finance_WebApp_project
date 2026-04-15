import Foundation

@MainActor
final class HealthViewModel: ObservableObject {
    @Published var health: FinancialHealth?
    @Published var isLoading = false
    @Published var errorMessage: String?

    private let api = APIClient.shared

    func loadHealth() async {
        isLoading = true
        errorMessage = nil

        do {
            health = try await api.get(path: "/financial-health")
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func zoneColor(_ zone: String?) -> String {
        switch zone {
        case "green", "independent": return "green"
        case "yellow", "growing": return "yellow"
        case "red", "starting": return "red"
        default: return "gray"
        }
    }

    func zoneEmoji(_ zone: String?) -> String {
        switch zone {
        case "green", "independent": return "checkmark.circle.fill"
        case "yellow", "growing": return "exclamationmark.triangle.fill"
        case "red", "starting": return "xmark.circle.fill"
        default: return "questionmark.circle"
        }
    }
}

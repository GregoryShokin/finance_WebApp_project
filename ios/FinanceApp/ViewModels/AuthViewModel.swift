import Foundation
import SwiftUI

@MainActor
final class AuthViewModel: ObservableObject {
    @Published var isAuthenticated = false
    @Published var currentUser: User?
    @Published var isLoading = false
    @Published var errorMessage: String?

    // Login fields
    @Published var loginEmail = ""
    @Published var loginPassword = ""

    // Register fields
    @Published var registerEmail = ""
    @Published var registerPassword = ""
    @Published var registerFullName = ""

    private let api = APIClient.shared
    private let keychain = KeychainService.shared

    func checkAuth() {
        guard keychain.getToken() != nil else {
            isAuthenticated = false
            return
        }
        Task {
            await fetchCurrentUser()
        }
    }

    func login() async {
        guard !loginEmail.isEmpty, !loginPassword.isEmpty else {
            errorMessage = "Заполните email и пароль"
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            let request = LoginRequest(email: loginEmail, password: loginPassword)
            let response: TokenResponse = try await api.post(path: "/auth/login", body: request)
            keychain.save(token: response.accessToken)
            await fetchCurrentUser()
            loginPassword = ""
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func register() async {
        guard !registerEmail.isEmpty, !registerPassword.isEmpty else {
            errorMessage = "Заполните email и пароль"
            return
        }
        guard registerPassword.count >= 8 else {
            errorMessage = "Пароль должен содержать минимум 8 символов"
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            let request = RegisterRequest(
                email: registerEmail,
                password: registerPassword,
                fullName: registerFullName.isEmpty ? nil : registerFullName
            )
            let _: User = try await api.post(path: "/auth/register", body: request)

            // Auto-login after registration
            loginEmail = registerEmail
            loginPassword = registerPassword
            await login()
            registerPassword = ""
        } catch let error as APIError {
            errorMessage = error.errorDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func logout() {
        keychain.deleteToken()
        currentUser = nil
        isAuthenticated = false
        loginEmail = ""
        loginPassword = ""
    }

    private func fetchCurrentUser() async {
        do {
            let user: User = try await api.get(path: "/auth/me")
            currentUser = user
            isAuthenticated = true
        } catch {
            keychain.deleteToken()
            isAuthenticated = false
        }
    }
}

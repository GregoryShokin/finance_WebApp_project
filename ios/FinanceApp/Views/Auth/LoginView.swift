import SwiftUI

struct LoginView: View {
    @EnvironmentObject var authViewModel: AuthViewModel
    @State private var showRegister = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 32) {
                    // Logo
                    VStack(spacing: 12) {
                        Image(systemName: "chart.line.uptrend.xyaxis.circle.fill")
                            .font(.system(size: 72))
                            .foregroundStyle(.appPrimary)

                        Text("Финансы")
                            .font(.largeTitle)
                            .fontWeight(.bold)

                        Text("Управляйте своими финансами")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 60)

                    // Form
                    VStack(spacing: 16) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Email")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            TextField("email@example.com", text: $authViewModel.loginEmail)
                                .textFieldStyle(.roundedBorder)
                                .textContentType(.emailAddress)
                                .keyboardType(.emailAddress)
                                .autocapitalization(.none)
                                .autocorrectionDisabled()
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Пароль")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            SecureField("Введите пароль", text: $authViewModel.loginPassword)
                                .textFieldStyle(.roundedBorder)
                                .textContentType(.password)
                        }

                        if let error = authViewModel.errorMessage {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.red)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        Button {
                            Task { await authViewModel.login() }
                        } label: {
                            HStack {
                                if authViewModel.isLoading {
                                    ProgressView()
                                        .tint(.white)
                                }
                                Text("Войти")
                                    .fontWeight(.semibold)
                            }
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.appPrimary)
                            .foregroundStyle(.white)
                            .cornerRadius(12)
                        }
                        .disabled(authViewModel.isLoading)
                    }
                    .padding(.horizontal)

                    // Register link
                    Button {
                        showRegister = true
                    } label: {
                        HStack(spacing: 4) {
                            Text("Нет аккаунта?")
                                .foregroundStyle(.secondary)
                            Text("Зарегистрироваться")
                                .foregroundStyle(.appPrimary)
                                .fontWeight(.medium)
                        }
                        .font(.subheadline)
                    }
                }
                .padding()
            }
            .navigationDestination(isPresented: $showRegister) {
                RegisterView()
                    .environmentObject(authViewModel)
            }
        }
    }
}

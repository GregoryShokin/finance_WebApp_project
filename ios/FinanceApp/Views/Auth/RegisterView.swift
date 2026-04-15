import SwiftUI

struct RegisterView: View {
    @EnvironmentObject var authViewModel: AuthViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(spacing: 8) {
                    Text("Создать аккаунт")
                        .font(.title)
                        .fontWeight(.bold)

                    Text("Начните управлять финансами")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.top, 20)

                VStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Имя")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        TextField("Ваше имя (необязательно)", text: $authViewModel.registerFullName)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.name)
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Email")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        TextField("email@example.com", text: $authViewModel.registerEmail)
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
                        SecureField("Минимум 8 символов", text: $authViewModel.registerPassword)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.newPassword)
                    }

                    if let error = authViewModel.errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button {
                        Task { await authViewModel.register() }
                    } label: {
                        HStack {
                            if authViewModel.isLoading {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text("Зарегистрироваться")
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
            }
            .padding()
        }
        .navigationBarTitleDisplayMode(.inline)
    }
}

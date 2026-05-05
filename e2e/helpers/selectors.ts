/**
 * Stable test selectors for the FinanceApp frontend. Spec files MUST use
 * these constants (or `getByRole`) — never CSS classes or xpath-by-index.
 *
 * When you need a selector that doesn't exist:
 *  1. Add `data-testid="..."` in `frontend/components/...` (kebab-case,
 *     semantic — `confirm-import-button`, not `primary-button`).
 *  2. Add a constant here.
 *  3. Use the constant from your spec.
 *
 * Sonner toasts: see SEL.toast{Error,Success} — sonner emits
 * `[data-sonner-toast][data-type="error|success"]` with the toast body in
 * a child element.
 */
export const SEL = {
  // Login form
  loginForm: '[data-testid="login-form"]',
  loginEmail: '[data-testid="login-email-input"]',
  loginEmailError: '[data-testid="login-email-error"]',
  loginPassword: '[data-testid="login-password-input"]',
  loginPasswordError: '[data-testid="login-password-error"]',
  loginSubmit: '[data-testid="login-submit"]',

  // Register form
  registerForm: '[data-testid="register-form"]',
  registerFullName: '[data-testid="register-full-name-input"]',
  registerEmail: '[data-testid="register-email-input"]',
  registerPassword: '[data-testid="register-password-input"]',
  registerConfirmPassword: '[data-testid="register-confirm-password-input"]',
  registerSubmit: '[data-testid="register-submit"]',

  // Sonner toasts (sonner sets these data-* attrs automatically)
  toastError: '[data-sonner-toast][data-type="error"]',
  toastSuccess: '[data-sonner-toast][data-type="success"]',
} as const;

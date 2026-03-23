import { AuthCard } from '@/components/auth/auth-card';
import { LoginForm } from '@/components/auth/login-form';

export default function LoginPage() {
  return (
    <AuthCard title="Вход" description="Войди в аккаунт, чтобы управлять финансами.">
      <LoginForm />
    </AuthCard>
  );
}

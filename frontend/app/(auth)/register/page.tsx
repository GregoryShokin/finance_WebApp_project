import { AuthCard } from '@/components/auth/auth-card';
import { RegisterForm } from '@/components/auth/register-form';

export default function RegisterPage() {
  return (
    <AuthCard title="Регистрация" description="Создай аккаунт и начни вести учет финансов.">
      <RegisterForm />
    </AuthCard>
  );
}

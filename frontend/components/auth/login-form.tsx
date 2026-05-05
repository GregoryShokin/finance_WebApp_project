'use client';

import Link from 'next/link';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { login } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';
import { formatRateLimitErrorAuth, isRateLimitError } from '@/lib/api/rate-limit-error';
import { setTokenPair } from '@/lib/auth/token';
import { RETURN_TO_KEY } from '@/lib/auth/constants';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const schema = z.object({
  email: z.string().email('Укажи корректный email'),
  password: z.string().min(8, 'Минимум 8 символов'),
});

type FormValues = z.infer<typeof schema>;

export function LoginForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: async (data) => {
      setTokenPair(data);
      await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] });
      toast.success('Вход выполнен');
      let returnTo: string | null = null;
      if (typeof window !== 'undefined') {
        try {
          returnTo = window.sessionStorage.getItem(RETURN_TO_KEY);
          window.sessionStorage.removeItem(RETURN_TO_KEY);
        } catch {
          returnTo = null;
        }
      }
      router.replace(returnTo && returnTo.startsWith('/') ? returnTo : '/dashboard');
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && isRateLimitError(error.status, error.payload)) {
        toast.error(formatRateLimitErrorAuth(error.payload));
        return;
      }
      toast.error(error.message || 'Не удалось войти');
    },
  });

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <div>
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" placeholder="mail@example.com" {...register('email')} />
        {errors.email && <p className="mt-1 text-sm text-danger">{errors.email.message}</p>}
      </div>

      <div>
        <Label htmlFor="password">Пароль</Label>
        <Input id="password" type="password" placeholder="••••••••" {...register('password')} />
        {errors.password && <p className="mt-1 text-sm text-danger">{errors.password.message}</p>}
      </div>

      <Button className="w-full" type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? 'Входим...' : 'Войти'}
      </Button>

      <p className="text-sm text-slate-500">
        Нет аккаунта?{' '}
        <Link href="/register" className="font-medium text-slate-900 underline underline-offset-4">
          Зарегистрироваться
        </Link>
      </p>
    </form>
  );
}

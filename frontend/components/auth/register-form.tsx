'use client';

import Link from 'next/link';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { register as registerRequest, login } from '@/lib/api/auth';
import { setAccessToken } from '@/lib/auth/token';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const schema = z
  .object({
    full_name: z.string().min(2, 'Минимум 2 символа').optional().or(z.literal('')),
    email: z.string().email('Укажи корректный email'),
    password: z.string().min(8, 'Минимум 8 символов'),
    confirmPassword: z.string().min(8, 'Минимум 8 символов'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    path: ['confirmPassword'],
    message: 'Пароли не совпадают',
  });

type FormValues = z.infer<typeof schema>;

export function RegisterForm() {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      await registerRequest({
        email: values.email,
        password: values.password,
        full_name: values.full_name || undefined,
      });
      return login({ email: values.email, password: values.password });
    },
    onSuccess: (data) => {
      setAccessToken(data.access_token);
      toast.success('Аккаунт создан');
      router.replace('/dashboard');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось зарегистрироваться');
    },
  });

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <div>
        <Label htmlFor="full_name">Имя</Label>
        <Input id="full_name" placeholder="Григорий" {...register('full_name')} />
        {errors.full_name && <p className="mt-1 text-sm text-danger">{errors.full_name.message}</p>}
      </div>

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

      <div>
        <Label htmlFor="confirmPassword">Подтверждение пароля</Label>
        <Input id="confirmPassword" type="password" placeholder="••••••••" {...register('confirmPassword')} />
        {errors.confirmPassword && <p className="mt-1 text-sm text-danger">{errors.confirmPassword.message}</p>}
      </div>

      <Button className="w-full" type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? 'Создаем аккаунт...' : 'Создать аккаунт'}
      </Button>

      <p className="text-sm text-slate-500">
        Уже есть аккаунт?{' '}
        <Link href="/login" className="font-medium text-slate-900 underline underline-offset-4">
          Войти
        </Link>
      </p>
    </form>
  );
}

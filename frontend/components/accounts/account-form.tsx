'use client';

import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Account, CreateAccountPayload } from '@/types/account';

type AccountFormValues = CreateAccountPayload;

const defaultValues: AccountFormValues = {
  name: '',
  currency: 'RUB',
  balance: 0,
  is_active: true,
  is_credit: false,
};

export function AccountForm({
  initialData,
  initialValues,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  initialData?: Account | null;
  initialValues?: Partial<CreateAccountPayload> | null;
  isSubmitting?: boolean;
  onSubmit: (values: AccountFormValues) => void;
  onCancel: () => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AccountFormValues>({
    defaultValues,
  });

  useEffect(() => {
    if (initialData) {
      reset({
        name: initialData.name,
        currency: initialData.currency,
        balance: Number(initialData.balance),
        is_active: initialData.is_active,
        is_credit: initialData.is_credit,
      });
      return;
    }

    reset({
      ...defaultValues,
      name: initialValues?.name ?? '',
      currency: initialValues?.currency ?? 'RUB',
      balance: initialValues?.balance ?? 0,
      is_active: initialValues?.is_active ?? true,
      is_credit: initialValues?.is_credit ?? false,
    });
  }, [initialData, initialValues, reset]);

  return (
    <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
      <div>
        <Label htmlFor="account-name">Название счёта</Label>
        <Input
          id="account-name"
          placeholder="Например, Основная карта"
          {...register('name', {
            required: 'Укажи название счёта',
            minLength: { value: 1, message: 'Название не должно быть пустым' },
          })}
        />
        {errors.name ? <p className="mt-1 text-sm text-danger">{errors.name.message}</p> : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="account-currency">Валюта</Label>
          <Input
            id="account-currency"
            placeholder="RUB"
            maxLength={3}
            {...register('currency', {
              required: 'Укажи валюту',
              setValueAs: (value) => String(value).toUpperCase(),
              validate: (value) => value.trim().length === 3 || 'Код валюты должен состоять из 3 символов',
            })}
          />
          {errors.currency ? <p className="mt-1 text-sm text-danger">{errors.currency.message}</p> : null}
        </div>

        <div>
          <Label htmlFor="account-balance">Баланс</Label>
          <Input
            id="account-balance"
            type="number"
            step="0.01"
            placeholder="0"
            {...register('balance', {
              required: 'Укажи баланс',
              valueAsNumber: true,
              validate: (value) => Number.isFinite(value) || 'Введите корректное число',
            })}
          />
          {errors.balance ? <p className="mt-1 text-sm text-danger">{errors.balance.message}</p> : null}
        </div>
      </div>

      <div className="grid gap-3">
        <label className="flex items-center gap-3 rounded-xl border bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <Checkbox {...register('is_active')} />
          Счёт активен
        </label>
        <label className="flex items-center gap-3 rounded-xl border bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <Checkbox {...register('is_credit')} />
          Это кредитный счёт / кредитная карта / рассрочка
        </label>
      </div>

      <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Сохраняем...' : initialData ? 'Сохранить изменения' : 'Создать счёт'}
        </Button>
      </div>
    </form>
  );
}

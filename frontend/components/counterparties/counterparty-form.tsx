'use client';

import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { CreateCounterpartyPayload } from '@/types/counterparty';

type FormValues = {
  name: string;
  opening_balance: string;
  opening_balance_kind: 'receivable' | 'payable';
};

export function CounterpartyForm({
  initialValues,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  initialValues?: Partial<CreateCounterpartyPayload> | null;
  isSubmitting?: boolean;
  onSubmit: (payload: CreateCounterpartyPayload) => void;
  onCancel: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    defaultValues: {
      name: initialValues?.name ?? '',
      opening_balance: initialValues?.opening_balance != null ? String(initialValues.opening_balance) : '',
      opening_balance_kind: initialValues?.opening_balance_kind ?? 'receivable',
    },
  });

  return (
    <form
      className="space-y-5"
      onSubmit={handleSubmit((values) =>
        onSubmit({
          name: values.name.trim(),
          opening_balance: values.opening_balance ? Number(values.opening_balance) : 0,
          opening_balance_kind: values.opening_balance_kind,
        })
      )}
    >
      <div>
        <Label htmlFor="counterparty-name">Имя</Label>
        <Input
          id="counterparty-name"
          className="h-10"
          placeholder="Например, Иван"
          {...register('name', { required: 'Укажи имя' })}
        />
        {errors.name ? <p className="mt-1 text-xs text-danger">{errors.name.message}</p> : null}
      </div>

      <div>
        <Label htmlFor="counterparty-opening-balance">Текущая сумма долга не учитывая текущую сумму</Label>
        <Input
          id="counterparty-opening-balance"
          className="h-10"
          type="number"
          step="0.01"
          placeholder="0.00"
          {...register('opening_balance', {
            validate: (value) => !value || Number(value) >= 0 || 'Введите корректную сумму',
          })}
        />
      </div>

      <div>
        <Label>Тип долга</Label>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3 text-sm text-slate-700 transition hover:border-slate-300">
            <input type="radio" value="receivable" className="mt-1" {...register('opening_balance_kind')} />
            <span>
              <span className="block font-medium text-slate-900">Мне должны</span>
              <span className="block text-xs text-slate-500">Контрагент должен деньги мне.</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3 text-sm text-slate-700 transition hover:border-slate-300">
            <input type="radio" value="payable" className="mt-1" {...register('opening_balance_kind')} />
            <span>
              <span className="block font-medium text-slate-900">Я должен</span>
              <span className="block text-xs text-slate-500">Я должен деньги этому контрагенту.</span>
            </span>
          </label>
        </div>
      </div>

      <div className="flex flex-col-reverse gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Сохраняем...' : 'Создать контрагента'}
        </Button>
      </div>
    </form>
  );
}

'use client';

import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { Select } from '@/components/ui/select';
import type { Account, AccountType, CreateAccountPayload } from '@/types/account';

type AccountFormValues = CreateAccountPayload;
type AccountTypeValue = AccountType;

const defaultValues: AccountFormValues = {
  name: '',
  currency: 'RUB',
  balance: 0,
  is_active: true,
  account_type: 'regular',
  is_credit: false,
  credit_limit_original: null,
  credit_current_amount: null,
  credit_interest_rate: null,
  credit_term_remaining: null,
  monthly_payment: null,
  deposit_interest_rate: null,
  deposit_open_date: null,
  deposit_close_date: null,
  deposit_capitalization_period: null,
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
    setValue,
    formState: { errors },
  } = useForm<AccountFormValues>({ defaultValues });

  const [accountType, setAccountType] = useState<AccountTypeValue>('regular');
  const [accountTypeQuery, setAccountTypeQuery] = useState('Обычный');

  const accountTypeItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'regular', label: 'Обычный счёт', searchText: 'обычный счет карта наличные regular' },
      { value: 'credit_card', label: 'Кредитная карта', searchText: 'кредитная карта credit card лимит' },
      { value: 'credit', label: 'Кредит', searchText: 'кредит кредитный счет loan credit' },
      { value: 'deposit', label: 'Вклад', searchText: 'вклад депозит deposit проценты' },
    ],
    [],
  );

  useEffect(() => {
    const resolvedAccountType =
      initialData?.account_type ??
      initialValues?.account_type ??
      (initialData?.is_credit ?? initialValues?.is_credit ? 'credit' : 'regular');
    setAccountType(resolvedAccountType);
    setAccountTypeQuery(
      accountTypeItems.find((item) => item.value === resolvedAccountType)?.label ?? 'Обычный счёт',
    );

    if (initialData) {
      reset({
        name: initialData.name,
        currency: initialData.currency,
        balance: Number(initialData.balance),
        is_active: initialData.is_active,
        account_type: initialData.account_type ?? (initialData.is_credit ? 'credit' : 'regular'),
        is_credit: initialData.is_credit,
        credit_limit_original:
          initialData.credit_limit_original != null ? Number(initialData.credit_limit_original) : null,
        credit_current_amount:
          initialData.credit_current_amount != null ? Number(initialData.credit_current_amount) : null,
        credit_interest_rate:
          initialData.credit_interest_rate != null ? Number(initialData.credit_interest_rate) : null,
        credit_term_remaining: initialData.credit_term_remaining ?? null,
        monthly_payment:
          initialData.monthly_payment != null ? Number(initialData.monthly_payment) : null,
        deposit_interest_rate:
          initialData.deposit_interest_rate != null ? Number(initialData.deposit_interest_rate) : null,
        deposit_open_date: initialData.deposit_open_date ?? null,
        deposit_close_date: initialData.deposit_close_date ?? null,
        deposit_capitalization_period: initialData.deposit_capitalization_period ?? null,
      });
      return;
    }

    reset({
      ...defaultValues,
      name: initialValues?.name ?? '',
      currency: initialValues?.currency ?? 'RUB',
      balance: initialValues?.balance ?? 0,
      is_active: initialValues?.is_active ?? true,
      account_type: initialValues?.account_type ?? (initialValues?.is_credit ? 'credit' : 'regular'),
      is_credit: initialValues?.is_credit ?? false,
      credit_limit_original: initialValues?.credit_limit_original ?? null,
      credit_current_amount: initialValues?.credit_current_amount ?? null,
      credit_interest_rate: initialValues?.credit_interest_rate ?? null,
      credit_term_remaining: initialValues?.credit_term_remaining ?? null,
      monthly_payment: initialValues?.monthly_payment ?? null,
      deposit_interest_rate: initialValues?.deposit_interest_rate ?? null,
      deposit_open_date: initialValues?.deposit_open_date ?? null,
      deposit_close_date: initialValues?.deposit_close_date ?? null,
      deposit_capitalization_period: initialValues?.deposit_capitalization_period ?? null,
    });
  }, [accountTypeItems, initialData, initialValues, reset]);

  const isCredit = accountType === 'credit';
  const isCreditCard = accountType === 'credit_card';
  const isDeposit = accountType === 'deposit';

  return (
    <form
      className="space-y-4"
      onSubmit={handleSubmit((values) => {
        const payload: AccountFormValues = {
          ...values,
          account_type: accountType,
          is_credit: isCredit,
          balance: isCredit ? 0 : Number(values.balance),
          credit_limit_original: isCredit || isCreditCard ? Number(values.credit_limit_original) : null,
          credit_current_amount: isCredit ? Number(values.credit_current_amount) : null,
          credit_interest_rate: isCredit ? Number(values.credit_interest_rate) : null,
          credit_term_remaining: isCredit ? Number(values.credit_term_remaining) : null,
          monthly_payment: isCredit || isCreditCard ? (values.monthly_payment || null) : null,
          deposit_interest_rate: isDeposit ? (values.deposit_interest_rate || null) : null,
          deposit_open_date: isDeposit ? (values.deposit_open_date || null) : null,
          deposit_close_date: isDeposit ? (values.deposit_close_date || null) : null,
          deposit_capitalization_period: isDeposit ? (values.deposit_capitalization_period || null) : null,
        };
        onSubmit(payload);
      })}
    >
      <div>
        <Label htmlFor="account-name">Название счёта</Label>
        <Input
          id="account-name"
          placeholder="Например, Основная карта или Ипотека"
          {...register('name', {
            required: 'Укажи название счёта',
            minLength: { value: 1, message: 'Название не должно быть пустым' },
          })}
        />
        {errors.name ? <p className="mt-1 text-sm text-danger">{errors.name.message}</p> : null}
      </div>

      <input type="hidden" {...register('account_type')} />

      <div>
        <SearchSelect
          id="account-type"
          label="Тип счёта"
          placeholder="Выбери тип"
          widthClassName="w-full"
          query={accountTypeQuery}
          setQuery={setAccountTypeQuery}
          items={accountTypeItems}
          selectedValue={accountType}
          showAllOnFocus
          onSelect={(item) => {
            const nextType = item.value as AccountTypeValue;
            setAccountType(nextType);
            setAccountTypeQuery(item.label);
            setValue('account_type', nextType);
            setValue('is_credit', nextType === 'credit');
          }}
        />
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

        {!isCredit && !isCreditCard ? (
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
        ) : null}
      </div>

      {isCredit ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="credit-limit-original">Изначальная сумма</Label>
            <Input id="credit-limit-original" type="number" step="0.01" placeholder="0" {...register('credit_limit_original', { valueAsNumber: true, required: 'Укажи изначальную сумму' })} />
            {errors.credit_limit_original ? <p className="mt-1 text-sm text-danger">{errors.credit_limit_original.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="credit-balance-current">Текущая сумма долга</Label>
            <Input id="credit-balance-current" type="number" step="0.01" placeholder="0" {...register('credit_current_amount', { valueAsNumber: true, required: 'Укажи текущую сумму долга' })} />
            {errors.credit_current_amount ? <p className="mt-1 text-sm text-danger">{errors.credit_current_amount.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="credit-interest-rate">Процентная ставка</Label>
            <Input id="credit-interest-rate" type="number" step="0.001" placeholder="0" {...register('credit_interest_rate', { valueAsNumber: true, required: 'Укажи процентную ставку' })} />
            {errors.credit_interest_rate ? <p className="mt-1 text-sm text-danger">{errors.credit_interest_rate.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="credit-remaining-term-months">Оставшийся срок, мес.</Label>
            <Input id="credit-remaining-term-months" type="number" step="1" placeholder="0" {...register('credit_term_remaining', { valueAsNumber: true, required: 'Укажи оставшийся срок' })} />
            {errors.credit_term_remaining ? <p className="mt-1 text-sm text-danger">{errors.credit_term_remaining.message}</p> : null}
          </div>
        </div>
      ) : null}

      {isCreditCard ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="credit-card-limit">Лимит</Label>
            <Input id="credit-card-limit" type="number" step="0.01" placeholder="0" {...register('credit_limit_original', { valueAsNumber: true, required: 'Укажи лимит карты' })} />
            {errors.credit_limit_original ? <p className="mt-1 text-sm text-danger">{errors.credit_limit_original.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="credit-card-balance">Текущий баланс</Label>
            <Input id="credit-card-balance" type="number" step="0.01" placeholder="0" {...register('balance', { required: 'Укажи текущий баланс', valueAsNumber: true, validate: (value) => Number.isFinite(value) || 'Введите корректное число' })} />
            {errors.balance ? <p className="mt-1 text-sm text-danger">{errors.balance.message}</p> : null}
          </div>
        </div>
      ) : null}

      {isDeposit ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="deposit-interest-rate">Процентная ставка, % годовых</Label>
            <Input id="deposit-interest-rate" type="number" step="0.01" placeholder="0" {...register('deposit_interest_rate', { valueAsNumber: true })} />
          </div>
          <div>
            <Label htmlFor="deposit-open-date">Дата открытия</Label>
            <Input id="deposit-open-date" type="date" {...register('deposit_open_date')} />
          </div>
          <div>
            <Label htmlFor="deposit-close-date">Дата закрытия</Label>
            <Input id="deposit-close-date" type="date" {...register('deposit_close_date')} />
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="deposit-capitalization-period">Капитализация процентов</Label>
            <Select
              id="deposit-capitalization-period"
              defaultValue=""
              {...register('deposit_capitalization_period')}
            >
              <option value="">Нет (проценты выплачиваются отдельно)</option>
              <option value="daily">Ежедневная</option>
              <option value="monthly">Ежемесячная</option>
              <option value="quarterly">Ежеквартальная</option>
              <option value="yearly">Ежегодная</option>
            </Select>
          </div>
        </div>
      ) : null}

      {isCredit || isCreditCard ? (
        <div>
          <Label htmlFor="monthly-payment">Ежемесячный платёж</Label>
          <Input
            id="monthly-payment"
            type="number"
            step="0.01"
            placeholder="Укажи размер платежа из договора"
            {...register('monthly_payment', { valueAsNumber: true })}
          />
          <p className="mt-1 text-xs text-slate-400">
            Необязательно · используется до первого внесённого платежа
          </p>
        </div>
      ) : null}

      <div className="grid gap-3">
        <label className="flex items-center gap-3 rounded-xl border bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <Checkbox {...register('is_active')} />
          Счёт активен
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

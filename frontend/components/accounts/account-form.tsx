'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { BankPicker } from '@/components/accounts/bank-picker';
import { BankSupportRequestModal } from '@/components/accounts/bank-support-request-form';
import type { Account, AccountType, Bank, CreateAccountPayload } from '@/types/account';

type TypeOption = { value: AccountType; label: string };
const ALL_TYPE_OPTIONS: TypeOption[] = [
  { value: 'cash',             label: 'Наличные' },
  { value: 'main',             label: 'Дебетовая карта' },
  { value: 'credit_card',      label: 'Кредитная карта' },
  { value: 'installment_card', label: 'Карта рассрочки' },
  { value: 'marketplace',      label: 'Маркетплейс / электронный кошелёк' },
  { value: 'broker',           label: 'Брокерский счёт' },
  { value: 'currency',         label: 'Валютный счёт' },
  { value: 'savings',          label: 'Вклад' },
  { value: 'savings_account',  label: 'Накопительный счёт' },
  { value: 'loan',             label: 'Кредит / ипотека' },
];

type AccountFormValues = CreateAccountPayload;
type AccountTypeValue = AccountType;

const defaultValues: AccountFormValues = {
  name: '',
  currency: 'RUB',
  balance: 0,
  is_active: true,
  account_type: 'main',
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
  contract_number: null,
  statement_account_number: null,
};

export function AccountForm({
  initialData,
  initialValues,
  initialBank,
  allowedTypes,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  initialData?: Account | null;
  initialValues?: Partial<CreateAccountPayload> | null;
  // Auto-account-recognition Шаг 3 (2026-05-06): when the import flow opens
  // the create-account dialog with a pre-detected bank, pass the full Bank
  // object so the BankPicker shows it preselected without a second roundtrip.
  initialBank?: Bank | null;
  allowedTypes?: AccountType[];
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

  const [accountType, setAccountType] = useState<AccountTypeValue>('main');
  const [selectedBank, setSelectedBank] = useState<Bank | null>(null);
  const [bankError, setBankError] = useState<string | null>(null);
  const [supportRequestOpen, setSupportRequestOpen] = useState(false);

  useEffect(() => {
    const resolvedAccountType =
      initialData?.account_type ??
      initialValues?.account_type ??
      (initialData?.is_credit ?? initialValues?.is_credit ? 'loan' : 'main');
    setAccountType(resolvedAccountType);

    if (initialData) {
      setSelectedBank(initialData.bank ?? null);
      reset({
        name: initialData.name,
        currency: initialData.currency,
        balance: Number(initialData.balance),
        is_active: initialData.is_active,
        account_type: initialData.account_type ?? (initialData.is_credit ? 'loan' : 'main'),
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
      account_type: initialValues?.account_type ?? (initialValues?.is_credit ? 'loan' : 'main'),
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
      contract_number: initialValues?.contract_number ?? null,
      statement_account_number: initialValues?.statement_account_number ?? null,
    });
    // initialBank pre-selects the BankPicker without an extra fetch — used by
    // the import flow when the extractor detected a known bank.
    if (initialBank) {
      setSelectedBank(initialBank);
    }
  }, [initialData, initialValues, initialBank, reset]);

  const typeOptions = allowedTypes
    ? ALL_TYPE_OPTIONS.filter((o) => allowedTypes.includes(o.value))
    : ALL_TYPE_OPTIONS;

  const isCash = accountType === 'cash';
  const isLoan = accountType === 'loan';
  const isCreditCard = accountType === 'credit_card';
  const isSavings = accountType === 'savings';
  const isSavingsAccount = accountType === 'savings_account';
  const isInstallmentCard = accountType === 'installment_card';

  return (
    <form
      className="space-y-4"
      autoComplete="off"
      onSubmit={handleSubmit((values) => {
        if (!isCash && !selectedBank) {
          setBankError('Выбери банк — без него выписки не распознаются');
          return;
        }
        setBankError(null);
        const payload: AccountFormValues = {
          ...values,
          account_type: accountType,
          is_credit: isLoan,
          bank_id: isCash ? null : selectedBank!.id,
          balance: isLoan ? 0 : Number(values.balance),
          credit_limit_original: isLoan || isCreditCard || isInstallmentCard ? Number(values.credit_limit_original) : null,
          credit_current_amount: isLoan || isInstallmentCard ? Number(values.credit_current_amount) : null,
          credit_interest_rate: isLoan || isInstallmentCard ? Number(values.credit_interest_rate) : null,
          credit_term_remaining: isLoan ? Number(values.credit_term_remaining) : null,
          monthly_payment: isLoan || isCreditCard || isInstallmentCard ? (values.monthly_payment || null) : null,
          deposit_interest_rate: isSavings ? (values.deposit_interest_rate || null) : null,
          deposit_open_date: isSavings ? (values.deposit_open_date || null) : null,
          deposit_close_date: isSavings ? (values.deposit_close_date || null) : null,
          deposit_capitalization_period: isSavings ? (values.deposit_capitalization_period || null) : null,
          // Шаг 3: thread contract_number / statement_account_number through to
          // backend so the create-account-from-import flow sets the identifiers
          // that will let future uploads from the same bank auto-attach via
          // Level 1/2 lookup. Empty strings are normalised to null.
          contract_number: values.contract_number?.trim() ? values.contract_number.trim() : null,
          statement_account_number: values.statement_account_number?.trim() ? values.statement_account_number.trim() : null,
        };
        onSubmit(payload);
      })}
    >
      <div>
        <Label htmlFor="account-name">Название счёта</Label>
        <Input
          id="account-name"
          placeholder="Например, Основная карта или Ипотека"
          // Browser autofill (Chrome history) was suggesting account names
          // entered by other users on the same machine. autoComplete="off"
          // is enough for non-credential text inputs.
          autoComplete="off"
          {...register('name', {
            required: 'Укажи название счёта',
            minLength: { value: 1, message: 'Название не должно быть пустым' },
          })}
        />
        {errors.name ? <p className="mt-1 text-sm text-danger">{errors.name.message}</p> : null}
      </div>

      {!isCash ? (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">
            Банк <span className="text-danger">*</span>
          </label>
          <BankPicker
            value={selectedBank?.id ?? null}
            onChange={(bank) => {
              setSelectedBank(bank);
              if (bank) setBankError(null);
            }}
          />
          {bankError ? (
            <p className="mt-1 text-sm text-danger">{bankError}</p>
          ) : selectedBank && selectedBank.extractor_status !== 'supported' ? (
            <div className="mt-1 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800 ring-1 ring-amber-200">
              <p>
                {selectedBank.extractor_status === 'broken'
                  ? 'Импорт для этого банка временно не работает — формат выписки изменился, чиним.'
                  : 'Импорт выписок этого банка пока не поддерживается. Транзакции придётся вводить вручную.'}
              </p>
              <button
                type="button"
                onClick={() => setSupportRequestOpen(true)}
                className="mt-1 font-medium text-amber-900 underline hover:no-underline"
              >
                Запросить поддержку
              </button>
            </div>
          ) : (
            <p className="mt-1 text-xs text-slate-400">Помогает правильно распознавать выписки и связывать счета</p>
          )}
        </div>
      ) : null}

      <input type="hidden" {...register('account_type')} />

      <div>
        <Label htmlFor="account-type">Тип счёта</Label>
        <Select
          id="account-type"
          value={accountType}
          onChange={(e) => {
            const nextType = e.target.value as AccountTypeValue;
            setAccountType(nextType);
            setValue('account_type', nextType);
            setValue('is_credit', nextType === 'loan');
          }}
        >
          {typeOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>
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

        {!isLoan && !isCreditCard && !isInstallmentCard ? (
          <div>
            <Label htmlFor="account-balance">{isSavings || isSavingsAccount ? 'Сумма' : 'Баланс'}</Label>
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

      {isLoan ? (
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

      {isSavingsAccount ? (
        <div>
          <Label htmlFor="savings-account-rate">Процентная ставка, % годовых</Label>
          <Input id="savings-account-rate" type="number" step="0.01" placeholder="0" {...register('deposit_interest_rate', { valueAsNumber: true })} />
        </div>
      ) : null}

      {isSavings ? (
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

      {isInstallmentCard ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="installment-limit">Лимит</Label>
            <Input id="installment-limit" type="number" step="0.01" placeholder="0" {...register('credit_limit_original', { valueAsNumber: true, required: 'Укажи лимит карты' })} />
            {errors.credit_limit_original ? <p className="mt-1 text-sm text-danger">{errors.credit_limit_original.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="installment-debt">Текущий долг</Label>
            <Input id="installment-debt" type="number" step="0.01" placeholder="0" {...register('credit_current_amount', { valueAsNumber: true })} />
          </div>
          <div>
            <Label htmlFor="installment-rate">Ставка, %</Label>
            <Input id="installment-rate" type="number" step="0.001" placeholder="0" {...register('credit_interest_rate', { valueAsNumber: true })} />
          </div>
        </div>
      ) : null}

      {isLoan || isCreditCard || isInstallmentCard ? (
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

      {supportRequestOpen && (
        <BankSupportRequestModal
          bank={selectedBank}
          onClose={() => setSupportRequestOpen(false)}
        />
      )}
    </form>
  );
}

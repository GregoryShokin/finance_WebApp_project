'use client';

import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import type { Account } from '@/types/account';
import type { Category, CategoryKind } from '@/types/category';
import type { CreateTransactionPayload, Transaction, TransactionKind, TransactionOperationType } from '@/types/transaction';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';

type TransactionFormValues = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  amount: string;
  operation_type: TransactionOperationType;
  description: string;
  transaction_date: string;
  needs_review: string;
};

type MainTypeValue = 'regular' | 'transfer' | 'investment' | 'credit_principal' | 'debt';
type InvestmentDirection = '' | 'buy' | 'sell';
type DebtDirection = '' | 'lent' | 'borrowed';

const defaultValues: TransactionFormValues = {
  account_id: '',
  target_account_id: '',
  category_id: '',
  amount: '',
  operation_type: 'regular',
  description: '',
  transaction_date: '',
  needs_review: 'false',
};

function toDatetimeLocal(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function toIso(value: string) {
  return new Date(value).toISOString();
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function mapOperationToUi(
  operationType: TransactionOperationType,
  transactionKind?: TransactionKind | null,
): {
  mainType: MainTypeValue;
  investmentDirection: InvestmentDirection;
  debtDirection: DebtDirection;
} {
  if (operationType === 'transfer') {
    return { mainType: 'transfer', investmentDirection: '', debtDirection: '' };
  }
  if (operationType === 'investment_buy') {
    return { mainType: 'investment', investmentDirection: 'buy', debtDirection: '' };
  }
  if (operationType === 'investment_sell') {
    return { mainType: 'investment', investmentDirection: 'sell', debtDirection: '' };
  }
  if (operationType === 'credit_disbursement' || operationType === 'credit_payment') {
    return { mainType: 'credit_principal', investmentDirection: '', debtDirection: '' };
  }
  if (operationType === 'debt') {
    return {
      mainType: 'debt',
      investmentDirection: '',
      debtDirection: transactionKind === 'income' ? 'borrowed' : 'lent',
    };
  }
  return { mainType: 'regular', investmentDirection: '', debtDirection: '' };
}

function mapUiToOperation(mainType: MainTypeValue, investmentDirection: InvestmentDirection): TransactionOperationType {
  if (mainType === 'transfer') return 'transfer';
  if (mainType === 'investment') {
    return investmentDirection === 'sell' ? 'investment_sell' : 'investment_buy';
  }
  if (mainType === 'credit_principal') {
    return 'credit_payment';
  }
  if (mainType === 'debt') {
    return 'debt';
  }
  return 'regular';
}

function getFixedTypeByOperation(operationType: TransactionOperationType): TransactionKind | null {
  const map: Record<TransactionOperationType, TransactionKind | null> = {
    regular: null,
    transfer: 'expense',
    investment_buy: 'expense',
    investment_sell: 'income',
    credit_disbursement: 'income',
    credit_payment: 'expense',
    credit_interest: 'expense',
    debt: null,
  };
  return map[operationType] ?? null;
}

function getDerivedType(
  operationType: TransactionOperationType,
  category: Category | null,
  debtDirection: DebtDirection,
): TransactionKind {
  if (operationType === 'debt') {
    return debtDirection === 'borrowed' ? 'income' : 'expense';
  }
  if (category?.kind) return category.kind as TransactionKind;
  return getFixedTypeByOperation(operationType) ?? 'expense';
}

function getOperationSummaryLabel(
  operationType: TransactionOperationType,
  investmentDirection: InvestmentDirection,
  debtDirection: DebtDirection,
  hasValidDebtDirection: boolean,
) {
  if (operationType === 'debt') {
    if (!hasValidDebtDirection) return 'Долг: направление не выбрано';
    return debtDirection === 'borrowed' ? 'Долг: мне заняли' : 'Долг: занял';
  }
  if (operationType === 'investment_buy' || operationType === 'investment_sell') {
    if (!investmentDirection) return 'Инвестиционный: действие не выбрано';
  }
  return operationTypeLabels[operationType];
}

export function TransactionForm({
  initialData,
  accounts,
  categories,
  isSubmitting,
  onSubmit,
  onCancel,
  onCreateCategoryRequest,
  onCreateAccountRequest,
}: {
  initialData?: Transaction | null;
  accounts: Account[];
  categories: Category[];
  isSubmitting?: boolean;
  onSubmit: (values: CreateTransactionPayload) => void;
  onCancel: () => void;
  onCreateCategoryRequest?: (payload: { name: string; kind: CategoryKind }) => void;
  onCreateAccountRequest?: (payload: { name: string }) => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, submitCount },
  } = useForm<TransactionFormValues>({ defaultValues });

  const selectedAccountId = watch('account_id');
  const selectedTargetAccountId = watch('target_account_id');
  const selectedCategoryId = watch('category_id');
  const needsReviewValue = watch('needs_review');

  const [mainType, setMainType] = useState<MainTypeValue>('regular');
  const [mainTypeQuery, setMainTypeQuery] = useState('Обычный');
  const [investmentDirection, setInvestmentDirection] = useState<InvestmentDirection>('');
  const [investmentDirectionQuery, setInvestmentDirectionQuery] = useState('');
  const [debtDirection, setDebtDirection] = useState<DebtDirection>('');
  const [debtDirectionQuery, setDebtDirectionQuery] = useState('');
  const [accountQuery, setAccountQuery] = useState('');
  const [targetAccountQuery, setTargetAccountQuery] = useState('');
  const [categoryQuery, setCategoryQuery] = useState('');
  const [reviewQuery, setReviewQuery] = useState('Нет');

  const mainTypeItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'regular', label: 'Обычный', searchText: 'обычный обычная regular' },
      { value: 'transfer', label: 'Перевод', searchText: 'перевод transfer между счетами' },
      { value: 'investment', label: 'Инвестиционный', searchText: 'инвестиционный инвестиции investment' },
      { value: 'credit_principal', label: 'Тело кредита', searchText: 'тело кредита кредит principal' },
      { value: 'debt', label: 'Долг', searchText: 'долг долги debt займ' },
    ],
    [],
  );

  const investmentDirectionItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'buy', label: 'Покупка', searchText: 'покупка buy' },
      { value: 'sell', label: 'Продажа', searchText: 'продажа sell' },
    ],
    [],
  );

  const debtDirectionItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'lent', label: 'Занял', searchText: 'занял выдал долг дал в долг расход выбытие' },
      { value: 'borrowed', label: 'Мне заняли', searchText: 'мне заняли взял в долг поступление доход' },
    ],
    [],
  );

  const accountItems = useMemo<SearchSelectItem[]>(
    () =>
      accounts.map((account) => ({
        value: String(account.id),
        label: account.name,
        searchText: `${account.name} ${account.currency}`,
        badge: account.currency,
      })),
    [accounts],
  );

  const categoryItems = useMemo<SearchSelectItem[]>(
    () =>
      [...categories]
        .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
        .map((category) => ({
          value: String(category.id),
          label: category.name,
          searchText: `${category.name} ${category.kind}`,
          badge: category.kind === 'income' ? 'Доход' : 'Расход',
          badgeClassName: category.kind === 'income' ? 'text-emerald-600' : 'text-rose-600',
        })),
    [categories],
  );

  const reviewItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'false', label: 'Нет', searchText: 'нет false' },
      { value: 'true', label: 'Да', searchText: 'да true' },
    ],
    [],
  );

  const selectedAccount = useMemo(
    () => accounts.find((account) => String(account.id) === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  );

  const selectedTargetAccount = useMemo(
    () => accounts.find((account) => String(account.id) === selectedTargetAccountId) ?? null,
    [accounts, selectedTargetAccountId],
  );

  const selectedCategory = useMemo(
    () => categories.find((category) => String(category.id) === selectedCategoryId) ?? null,
    [categories, selectedCategoryId],
  );

  const exactMatchedAccount = useMemo(() => {
    const normalized = normalize(accountQuery);
    if (!normalized) return null;
    return accounts.find((account) => normalize(account.name) === normalized) ?? null;
  }, [accounts, accountQuery]);

  const exactMatchedTargetAccount = useMemo(() => {
    const normalized = normalize(targetAccountQuery);
    if (!normalized) return null;
    return accounts.find((account) => normalize(account.name) === normalized) ?? null;
  }, [accounts, targetAccountQuery]);

  const exactMatchedCategory = useMemo(() => {
    const normalized = normalize(categoryQuery);
    if (!normalized) return null;
    return categories.find((category) => normalize(category.name) === normalized) ?? null;
  }, [categories, categoryQuery]);

  const selectedMainTypeItem = useMemo(
    () => mainTypeItems.find((item) => item.value === mainType) ?? null,
    [mainTypeItems, mainType],
  );

  const selectedInvestmentDirectionItem = useMemo(
    () => investmentDirectionItems.find((item) => item.value === investmentDirection) ?? null,
    [investmentDirectionItems, investmentDirection],
  );

  const selectedDebtDirectionItem = useMemo(
    () => debtDirectionItems.find((item) => item.value === debtDirection) ?? null,
    [debtDirectionItems, debtDirection],
  );

  const selectedTargetAccountItem = useMemo(
    () => accountItems.find((item) => item.value === selectedTargetAccountId) ?? null,
    [accountItems, selectedTargetAccountId],
  );

  const selectedReviewItem = useMemo(
    () => reviewItems.find((item) => item.value === needsReviewValue) ?? null,
    [reviewItems, needsReviewValue],
  );

  const showTransferTarget = mainType === 'transfer';
  const showInvestmentDirection = mainType === 'investment';
  const showDebtDirection = mainType === 'debt';
  const showCategory = mainType === 'regular';
  const hasValidInvestmentDirection = mainType !== 'investment' || Boolean(investmentDirection);
  const hasValidDebtDirection = mainType !== 'debt' || Boolean(debtDirection);
  const hasValidTargetAccount = !showTransferTarget || (Boolean(selectedTargetAccountId) && selectedTargetAccountId !== selectedAccountId);
  const hasValidDirection = hasValidInvestmentDirection && hasValidDebtDirection && hasValidTargetAccount;
  const resolvedOperationType = mapUiToOperation(mainType, investmentDirection || 'buy');
  const derivedType = useMemo(
    () => getDerivedType(resolvedOperationType, showCategory ? selectedCategory : null, debtDirection),
    [resolvedOperationType, selectedCategory, showCategory, debtDirection],
  );

  const showCreateAccountAction = Boolean(accountQuery.trim()) && !exactMatchedAccount;
  const showCreateCategoryAction = showCategory && Boolean(categoryQuery.trim()) && !exactMatchedCategory;
  const categoryKindForCreate = derivedType === 'income' ? 'income' : 'expense';

  useEffect(() => {
    setValue('operation_type', resolvedOperationType, { shouldValidate: true, shouldDirty: true });
  }, [resolvedOperationType, setValue]);

  useEffect(() => {
    if (exactMatchedAccount) {
      setValue('account_id', String(exactMatchedAccount.id), { shouldValidate: true, shouldDirty: true });
      return;
    }

    if (accountQuery.trim()) {
      setValue('account_id', '', { shouldValidate: true, shouldDirty: true });
    }
  }, [accountQuery, exactMatchedAccount, setValue]);

  useEffect(() => {
    if (!showTransferTarget) {
      setValue('target_account_id', '', { shouldValidate: true, shouldDirty: true });
      setTargetAccountQuery('');
      return;
    }

    if (exactMatchedTargetAccount) {
      setValue('target_account_id', String(exactMatchedTargetAccount.id), { shouldValidate: true, shouldDirty: true });
      return;
    }

    if (targetAccountQuery.trim()) {
      setValue('target_account_id', '', { shouldValidate: true, shouldDirty: true });
    }
  }, [targetAccountQuery, exactMatchedTargetAccount, setValue, showTransferTarget]);

  useEffect(() => {
    if (!showCategory) {
      setValue('category_id', '', { shouldValidate: true, shouldDirty: true });
      setCategoryQuery('');
      return;
    }

    if (exactMatchedCategory) {
      setValue('category_id', String(exactMatchedCategory.id), { shouldValidate: true, shouldDirty: true });
      return;
    }

    if (categoryQuery.trim()) {
      setValue('category_id', '', { shouldValidate: true, shouldDirty: true });
    }
  }, [categoryQuery, exactMatchedCategory, setValue, showCategory]);

  useEffect(() => {
    if (initialData) {
      const mapped = mapOperationToUi(initialData.operation_type, initialData.type);
      const initialAccount = accounts.find((account) => account.id === initialData.account_id) ?? null;
      const initialTargetAccount = initialData.target_account_id ? accounts.find((account) => account.id === initialData.target_account_id) ?? null : null;
      const initialCategory = initialData.category_id ? categories.find((category) => category.id === initialData.category_id) ?? null : null;

      reset({
        account_id: String(initialData.account_id),
        target_account_id: initialData.target_account_id ? String(initialData.target_account_id) : '',
        category_id: initialData.category_id ? String(initialData.category_id) : '',
        amount: String(initialData.amount),
        operation_type: initialData.operation_type,
        description: initialData.description ?? '',
        transaction_date: toDatetimeLocal(initialData.transaction_date),
        needs_review: String(initialData.needs_review),
      });

      setMainType(mapped.mainType);
      setMainTypeQuery(mainTypeItems.find((item) => item.value === mapped.mainType)?.label ?? 'Обычный');
      setInvestmentDirection(mapped.investmentDirection);
      setInvestmentDirectionQuery(mapped.investmentDirection === 'buy' ? 'Покупка' : mapped.investmentDirection === 'sell' ? 'Продажа' : '');
      setDebtDirection(mapped.debtDirection);
      setDebtDirectionQuery(mapped.debtDirection === 'borrowed' ? 'Мне заняли' : mapped.debtDirection === 'lent' ? 'Занял' : '');
      setAccountQuery(initialAccount?.name ?? '');
      setTargetAccountQuery(initialTargetAccount?.name ?? '');
      setCategoryQuery(initialCategory?.name ?? '');
      setReviewQuery(initialData.needs_review ? 'Да' : 'Нет');
      return;
    }

    reset({ ...defaultValues, transaction_date: toDatetimeLocal(new Date().toISOString()) });
    setMainType('regular');
    setMainTypeQuery('Обычный');
    setInvestmentDirection('');
    setInvestmentDirectionQuery('');
    setDebtDirection('');
    setDebtDirectionQuery('');
    setAccountQuery('');
    setTargetAccountQuery('');
    setCategoryQuery('');
    setReviewQuery('Нет');
  }, [initialData, reset, accounts, categories, mainTypeItems]);

  function handleCreateAccountClick() {
    const name = accountQuery.trim() || 'Новый счёт';
    onCreateAccountRequest?.({ name });
  }

  function handleCreateCategoryClick() {
    const name = categoryQuery.trim() || 'Новая категория';
    onCreateCategoryRequest?.({ name, kind: categoryKindForCreate });
  }

  return (
    <form
      className="space-y-5"
      onSubmit={handleSubmit((values) => {
        if (!hasValidDirection) return;

        onSubmit({
          account_id: Number(values.account_id),
          target_account_id: showTransferTarget && values.target_account_id ? Number(values.target_account_id) : null,
          category_id: showCategory && values.category_id ? Number(values.category_id) : null,
          amount: Number(values.amount),
          currency: (selectedAccount?.currency ?? selectedTargetAccount?.currency ?? 'RUB').trim().toUpperCase(),
          type: getDerivedType(
            values.operation_type,
            showCategory ? categories.find((category) => String(category.id) === values.category_id) ?? null : null,
            debtDirection,
          ),
          operation_type: values.operation_type,
          description: values.description.trim() || null,
          transaction_date: toIso(values.transaction_date),
          needs_review: values.needs_review === 'true',
        });
      })}
    >
      <input type="hidden" {...register('operation_type', { required: true })} />
      <input type="hidden" {...register('account_id', { required: 'Выбери счёт отправления' })} />
      <input
        type="hidden"
        {...register('target_account_id', {
          validate: (value) => {
            if (!showTransferTarget) return true;
            if (!targetAccountQuery.trim()) return 'Выбери счёт поступления';
            if (!value) return 'Выбери счёт поступления из списка';
            if (value === selectedAccountId) return 'Счёт отправления и поступления должны отличаться';
            return true;
          },
        })}
      />
      <input
        type="hidden"
        {...register('category_id', {
          validate: (value) => {
            if (!showCategory) return true;
            if (!categoryQuery.trim()) return true;
            return Boolean(value) || 'Выбери категорию из списка или создай новую';
          },
        })}
      />
      <input type="hidden" {...register('needs_review')} />

      <div className="grid gap-4 xl:grid-cols-6">
        <SearchSelect
          id="tx-main-type"
          label="Тип"
          placeholder="Выбери тип"
          widthClassName="w-full"
          query={mainTypeQuery}
          setQuery={setMainTypeQuery}
          items={mainTypeItems}
          selectedValue={selectedMainTypeItem?.value}
          showAllOnFocus
          onSelect={(item) => {
            const nextType = item.value as MainTypeValue;
            setMainType(nextType);
            setMainTypeQuery(item.label);
            if (nextType !== 'investment') {
              setInvestmentDirection('');
              setInvestmentDirectionQuery('');
            }
            if (nextType !== 'debt') {
              setDebtDirection('');
              setDebtDirectionQuery('');
            }
          }}
        />

        {showInvestmentDirection ? (
          <SearchSelect
            id="tx-investment-direction"
            label="Покупка / продажа"
            placeholder="Выбери действие"
            widthClassName="w-full"
            query={investmentDirectionQuery}
            setQuery={setInvestmentDirectionQuery}
            items={investmentDirectionItems}
            selectedValue={selectedInvestmentDirectionItem?.value}
            showAllOnFocus
            onSelect={(item) => {
              setInvestmentDirection(item.value as InvestmentDirection);
              setInvestmentDirectionQuery(item.label);
            }}
            error={submitCount > 0 && !hasValidInvestmentDirection ? 'Выбери действие' : undefined}
          />
        ) : null}

        {showDebtDirection ? (
          <SearchSelect
            id="tx-debt-direction"
            label="Направление"
            placeholder="Выбери направление"
            widthClassName="w-full"
            query={debtDirectionQuery}
            setQuery={setDebtDirectionQuery}
            items={debtDirectionItems}
            selectedValue={selectedDebtDirectionItem?.value}
            showAllOnFocus
            onSelect={(item) => {
              setDebtDirection(item.value as DebtDirection);
              setDebtDirectionQuery(item.label);
            }}
            error={submitCount > 0 && !hasValidDebtDirection ? 'Выбери направление' : undefined}
          />
        ) : null}

        <div>
          <SearchSelect
            id="tx-account"
            label={showTransferTarget ? 'Счёт отправления' : 'Счёт'}
            placeholder="Выбери счёт"
            widthClassName="w-full"
            query={accountQuery}
            setQuery={setAccountQuery}
            items={accountItems}
            selectedValue={selectedAccountId}
            showAllOnFocus
            onSelect={(item) => {
              setValue('account_id', item.value, { shouldValidate: true, shouldDirty: true });
              setAccountQuery(item.label);
            }}
            error={errors.account_id?.message}
            createAction={
              onCreateAccountRequest
                ? {
                    visible: showCreateAccountAction,
                    label: 'Создать счёт',
                    onClick: handleCreateAccountClick,
                  }
                : undefined
            }
          />
        </div>

        {showTransferTarget ? (
          <div>
            <SearchSelect
              id="tx-target-account"
              label="Счёт поступления"
              placeholder="Выбери счёт"
              widthClassName="w-full"
              query={targetAccountQuery}
              setQuery={setTargetAccountQuery}
              items={accountItems.filter((item) => item.value !== selectedAccountId)}
              selectedValue={selectedTargetAccountItem?.value}
              showAllOnFocus
              onSelect={(item) => {
                setValue('target_account_id', item.value, { shouldValidate: true, shouldDirty: true });
                setTargetAccountQuery(item.label);
              }}
              error={errors.target_account_id?.message || (submitCount > 0 && !hasValidTargetAccount ? 'Выбери счёт поступления' : undefined)}
            />
          </div>
        ) : null}

        <div>
          <Label htmlFor="tx-amount">Сумма</Label>
          <Input
            id="tx-amount"
            className="h-9"
            type="number"
            step="0.01"
            placeholder="0.00"
            {...register('amount', {
              required: 'Укажи сумму',
              validate: (value) => Number(value) > 0 || 'Сумма > 0',
            })}
          />
          {errors.amount ? <p className="mt-1 text-xs text-danger">{errors.amount.message}</p> : null}
        </div>

        {showCategory ? (
          <div>
            <SearchSelect
              id="tx-category"
              label="Категория"
              placeholder="Начни вводить..."
              widthClassName="w-full"
              query={categoryQuery}
              setQuery={setCategoryQuery}
              items={categoryItems}
              selectedValue={selectedCategoryId}
              onSelect={(item) => {
                setValue('category_id', item.value, { shouldValidate: true, shouldDirty: true });
                setCategoryQuery(item.label);
              }}
              error={errors.category_id?.message}
              createAction={
                onCreateCategoryRequest
                  ? {
                      visible: showCreateCategoryAction,
                      label: 'Создать категорию',
                      onClick: handleCreateCategoryClick,
                    }
                  : undefined
              }
            />
          </div>
        ) : null}

        <div>
          <Label htmlFor="tx-date">Дата и время</Label>
          <Input id="tx-date" className="h-9" type="datetime-local" {...register('transaction_date', { required: 'Укажи дату' })} />
          {errors.transaction_date ? <p className="mt-1 text-xs text-danger">{errors.transaction_date.message}</p> : null}
        </div>

        <SearchSelect
          id="tx-review"
          label="Проверка"
          placeholder="Выбери"
          widthClassName="w-full"
          query={reviewQuery}
          setQuery={setReviewQuery}
          items={reviewItems}
          selectedValue={selectedReviewItem?.value}
          showAllOnFocus
          onSelect={(item) => {
            setValue('needs_review', item.value, { shouldValidate: true, shouldDirty: true });
            setReviewQuery(item.label);
          }}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div>
          <Label htmlFor="tx-description">Описание</Label>
          <Input id="tx-description" className="h-10" placeholder="Комментарий" {...register('description')} />
        </div>

        <div className="flex min-h-10 flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span>
            Вид: <strong>{showTransferTarget ? 'Перевод' : transactionTypeLabels[derivedType]}</strong>
          </span>
          <span className="text-slate-300">•</span>
          <span>
            Валюта: <strong>{selectedAccount?.currency ?? selectedTargetAccount?.currency ?? '—'}</strong>
          </span>
          <span className="text-slate-300">•</span>
          <span>{getOperationSummaryLabel(watch('operation_type'), investmentDirection, debtDirection, hasValidDebtDirection)}</span>
        </div>
      </div>

      <div className="flex flex-col-reverse gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Сохраняем...' : initialData ? 'Сохранить изменения' : 'Создать транзакцию'}
        </Button>
      </div>
    </form>
  );
}

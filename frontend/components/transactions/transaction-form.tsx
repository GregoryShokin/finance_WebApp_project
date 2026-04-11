'use client';

import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { checkLargePurchase } from '@/lib/api/transactions';
import type { Account } from '@/types/account';
import type { Category, CategoryKind } from '@/types/category';
import type { CreateTransactionPayload, LargePurchaseCheck, Transaction, TransactionKind, TransactionOperationType } from '@/types/transaction';
import type { Counterparty } from '@/types/counterparty';
import type { GoalWithProgress } from '@/types/goal';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';

type TransactionFormValues = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  counterparty_id: string;
  credit_account_id: string;
  goal_id: string;
  amount: string;
  credit_principal_amount: string;
  credit_interest_amount: string;
  operation_type: TransactionOperationType;
  description: string;
  transaction_date: string;
  needs_review: string;
};

type MainTypeValue = 'regular' | 'refund' | 'transfer' | 'investment' | 'credit_operation' | 'debt';
type InvestmentDirection = '' | 'buy' | 'sell';
type DebtDirection = '' | 'lent' | 'borrowed' | 'repaid' | 'collected';
type CreditOperationKind = '' | 'disbursement' | 'payment' | 'early_repayment';

const defaultValues: TransactionFormValues = {
  account_id: '',
  target_account_id: '',
  category_id: '',
  credit_account_id: '',
  counterparty_id: '',
  goal_id: '',
  amount: '',
  credit_principal_amount: '',
  credit_interest_amount: '',
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


// Настоящий кредит-займ — денег на нём нет, операции проводятся
// через отдельный блок «Платёж по кредиту»/«Получение кредита».
// Кредитные карты и карты рассрочки — обычные платёжные инструменты,
// ими платят за покупки и они должны быть доступны в списке счетов.
function isLoanAccount(account: Account) {
  return account.account_type === 'credit';
}

function isSelectableTransactionAccount(account: Account) {
  return !isLoanAccount(account);
}

function mapOperationToUi(
  operationType: TransactionOperationType,
  debtDirectionOrKind?: DebtDirection | TransactionKind | null,
) : {
  mainType: MainTypeValue;
  investmentDirection: InvestmentDirection;
  debtDirection: DebtDirection;
  creditOperationKind: CreditOperationKind;
} {
  if (operationType === 'transfer') {
    return { mainType: 'transfer', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
  }
  if (operationType === 'refund') {
    return { mainType: 'refund', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
  }
  if (operationType === 'investment_buy') {
    return { mainType: 'investment', investmentDirection: 'buy', debtDirection: '', creditOperationKind: '' };
  }
  if (operationType === 'investment_sell') {
    return { mainType: 'investment', investmentDirection: 'sell', debtDirection: '', creditOperationKind: '' };
  }
  if (operationType === 'credit_disbursement' || operationType === 'credit_payment' || operationType === 'credit_early_repayment') {
    return {
      mainType: 'credit_operation',
      investmentDirection: '',
      debtDirection: '',
      creditOperationKind:
        operationType === 'credit_disbursement'
          ? 'disbursement'
          : operationType === 'credit_early_repayment'
            ? 'early_repayment'
            : 'payment',
    };
  }
  if (operationType === 'debt') {
    return {
      mainType: 'debt',
      investmentDirection: '',
      debtDirection: debtDirectionOrKind === 'lent' || debtDirectionOrKind === 'borrowed' || debtDirectionOrKind === 'repaid' || debtDirectionOrKind === 'collected' ? debtDirectionOrKind : debtDirectionOrKind === 'income' ? 'borrowed' : 'lent',
      creditOperationKind: '',
    };
  }
  return { mainType: 'regular', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
}

function mapUiToOperation(mainType: MainTypeValue, investmentDirection: InvestmentDirection, creditOperationKind: CreditOperationKind): TransactionOperationType {
  if (mainType === 'transfer') return 'transfer';
  if (mainType === 'refund') return 'refund';
  if (mainType === 'investment') {
    return investmentDirection === 'sell' ? 'investment_sell' : 'investment_buy';
  }
  if (mainType === 'credit_operation') {
    if (creditOperationKind === 'disbursement') return 'credit_disbursement';
    if (creditOperationKind === 'early_repayment') return 'credit_early_repayment';
    return 'credit_payment';
  }
  if (mainType === 'debt') {
    return 'debt';
  }
  return 'regular';
}

function getCreditOperationKindLabel(kind: CreditOperationKind) {
  if (kind === 'disbursement') return 'Получение кредита';
  if (kind === 'payment') return 'Платёж по кредиту';
  return 'Вид кредитной операции не выбран';
}

function getFixedTypeByOperation(operationType: TransactionOperationType): TransactionKind | null {
  const map: Record<TransactionOperationType, TransactionKind | null> = {
    regular: null,
    transfer: 'expense',
    investment_buy: 'expense',
    investment_sell: 'income',
    credit_disbursement: 'income',
    credit_payment: 'expense',
    credit_early_repayment: 'expense',
    credit_interest: 'expense',
    credit_principal_attribution: 'expense',
    debt: null,
    refund: 'income',
    adjustment: null,
  };
  return map[operationType] ?? null;
}

function getDerivedType(
  operationType: TransactionOperationType,
  category: Category | null,
  debtDirection: DebtDirection,
): TransactionKind {
  if (operationType === 'debt') {
    return debtDirection === 'borrowed' || debtDirection === 'collected' ? 'income' : 'expense';
  }
  if (operationType === 'refund') {
    return 'income';
  }
  if (category?.kind) return category.kind as TransactionKind;
  return getFixedTypeByOperation(operationType) ?? 'expense';
}

function getOperationSummaryLabel(
  operationType: TransactionOperationType,
  investmentDirection: InvestmentDirection,
  debtDirection: DebtDirection,
  hasValidDebtDirection: boolean,
  creditOperationKind: CreditOperationKind,
  hasValidCreditOperationKind: boolean,
) {
  if (operationType === 'debt') {
    if (!hasValidDebtDirection) return 'Долг: направление не выбрано';
    if (debtDirection === 'borrowed') return 'Долг: мне заняли';
    if (debtDirection === 'lent') return 'Долг: я занял';
    if (debtDirection === 'repaid') return 'Долг: вернул';
    if (debtDirection === 'collected') return 'Долг: мне вернули';
    return 'Долг';
  }
  if (operationType === 'investment_buy' || operationType === 'investment_sell') {
    if (!investmentDirection) return 'Инвестиционный: действие не выбрано';
  }
  if (operationType === 'credit_disbursement' || operationType === 'credit_payment' || operationType === 'credit_early_repayment') {
    if (!hasValidCreditOperationKind) return 'Кредитная операция: вид не выбран';
    return `Кредитная операция: ${getCreditOperationKindLabel(creditOperationKind)}`;
  }
  return operationTypeLabels[operationType];
}

export function TransactionForm({
  initialData,
  accounts,
  categories,
  counterparties = [],
  goals = [],
  isSubmitting,
  onSubmit,
  onCancel,
  onCreateCategoryRequest,
  onCreateAccountRequest,
  onCreateCounterpartyRequest,
  onDeleteCounterpartyRequest,
}: {
  initialData?: Transaction | null;
  accounts: Account[];
  categories: Category[];
  counterparties?: Counterparty[];
  goals?: GoalWithProgress[];
  isSubmitting?: boolean;
  onSubmit: (values: CreateTransactionPayload) => void;
  onCancel: () => void;
  onCreateCategoryRequest?: (payload: { name: string; kind: CategoryKind }) => void;
  onCreateAccountRequest?: (payload: { name: string }) => void;
  onCreateCounterpartyRequest?: (payload: { name: string; opening_balance_kind: 'receivable' | 'payable' }) => void;
  onDeleteCounterpartyRequest?: (counterparty: Counterparty) => void;
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
  const selectedCreditAccountId = watch('credit_account_id');
  const selectedCounterpartyId = watch('counterparty_id');
  const needsReviewValue = watch('needs_review');

  const [mainType, setMainType] = useState<MainTypeValue>('regular');
  const [mainTypeQuery, setMainTypeQuery] = useState('Обычный');
  const [investmentDirection, setInvestmentDirection] = useState<InvestmentDirection>('');
  const [investmentDirectionQuery, setInvestmentDirectionQuery] = useState('');
  const [creditOperationKind, setCreditOperationKind] = useState<CreditOperationKind>('');
  const [creditOperationKindQuery, setCreditOperationKindQuery] = useState('');
  const [debtDirection, setDebtDirection] = useState<DebtDirection>('');
  const [debtDirectionQuery, setDebtDirectionQuery] = useState('');
  const [accountQuery, setAccountQuery] = useState('');
  const [targetAccountQuery, setTargetAccountQuery] = useState('');
  const [categoryQuery, setCategoryQuery] = useState('');
  const [creditAccountQuery, setCreditAccountQuery] = useState('');
  const [counterpartyQuery, setCounterpartyQuery] = useState('');
  const [reviewQuery, setReviewQuery] = useState('Нет');

  const mainTypeItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'regular', label: 'Обычный', searchText: 'обычный обычная regular' },
      { value: 'refund', label: 'Возврат', searchText: 'возврат refund' },
      { value: 'transfer', label: 'Перевод', searchText: 'перевод transfer между счетами' },
      { value: 'investment', label: 'Инвестиционный', searchText: 'инвестиционный инвестиции investment' },
      { value: 'credit_operation', label: 'Кредитная операция', searchText: 'кредитная операция кредит payment disbursement loan credit' },
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

  const creditOperationKindItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'disbursement', label: 'Получение кредита', searchText: 'получение кредита выдача кредита disbursement' },
      { value: 'payment', label: 'Платёж по кредиту', searchText: 'платеж по кредиту погашение кредита payment' },
    ],
    [],
  );

  const debtDirectionItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'lent', label: 'Я занял', searchText: 'я занял выдал долг дал в долг расход выбытие' },
      { value: 'borrowed', label: 'Мне заняли', searchText: 'мне заняли взял в долг поступление доход' },
      { value: 'repaid', label: 'Вернул', searchText: 'вернул погасил долг отдал долг' },
      { value: 'collected', label: 'Мне вернули', searchText: 'мне вернули возврат долга вернули деньги' },
    ],
    [],
  );

  const accountItems = useMemo<SearchSelectItem[]>(
    () =>
      accounts.filter(isSelectableTransactionAccount).map((account) => ({
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


  const counterpartyItems = useMemo<SearchSelectItem[]>(
    () =>
      [...counterparties]
        .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
        .map((item) => ({
          value: String(item.id),
          label: item.name,
          searchText: item.name,
          badge: Number(item.receivable_amount) > 0 ? 'Мне должны' : Number(item.payable_amount) > 0 ? 'Я должен' : undefined,
          badgeClassName: Number(item.receivable_amount) > 0 ? 'text-emerald-600' : Number(item.payable_amount) > 0 ? 'text-amber-600' : undefined,
        })),
    [counterparties],
  );

  const reviewItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'false', label: 'Нет', searchText: 'нет false' },
      { value: 'true', label: 'Да', searchText: 'да true' },
    ],
    [],
  );

  const goalItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: '', label: 'Не привязывать', searchText: 'не привязывать без цели' },
      ...goals
        .filter((g) => g.status === 'active')
        .map((g) => ({
          value: String(g.id),
          label: g.name,
          searchText: g.name,
          badge: `${g.percent.toFixed(0)}%`,
        })),
    ],
    [goals],
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

  const selectedCreditAccount = useMemo(
    () => accounts.find((account) => String(account.id) === selectedCreditAccountId) ?? null,
    [accounts, selectedCreditAccountId],
  );

  const selectedGoalId = watch('goal_id');
  const [goalQuery, setGoalQuery] = useState('');

  // Large-purchase check
  const [largePurchaseCheck, setLargePurchaseCheck] = useState<LargePurchaseCheck | null>(null);
  type LargePurchaseKind = 'normal' | 'large' | 'deferred';
  const [largePurchaseKind, setLargePurchaseKind] = useState<LargePurchaseKind>('normal');
  const amountValue = watch('amount');

  const selectedCounterparty = useMemo(
    () => counterparties.find((item) => String(item.id) === selectedCounterpartyId) ?? null,
    [counterparties, selectedCounterpartyId],
  );

  const exactMatchedAccount = useMemo(() => {
    const normalized = normalize(accountQuery);
    if (!normalized) return null;
    return accounts.find((account) => isSelectableTransactionAccount(account) && normalize(account.name) === normalized) ?? null;
  }, [accounts, accountQuery]);

  const exactMatchedTargetAccount = useMemo(() => {
    const normalized = normalize(targetAccountQuery);
    if (!normalized) return null;
    return accounts.find((account) => isSelectableTransactionAccount(account) && normalize(account.name) === normalized) ?? null;
  }, [accounts, targetAccountQuery]);

  const exactMatchedCreditAccount = useMemo(() => {
    const normalized = normalize(creditAccountQuery);
    if (!normalized) return null;
    return accounts.find((account) => isLoanAccount(account) && normalize(account.name) === normalized) ?? null;
  }, [accounts, creditAccountQuery]);

  const exactMatchedCounterparty = useMemo(() => {
    const normalized = normalize(counterpartyQuery);
    if (!normalized) return null;
    return counterparties.find((item) => normalize(item.name) === normalized) ?? null;
  }, [counterparties, counterpartyQuery]);

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

  const selectedCreditOperationKindItem = useMemo(
    () => creditOperationKindItems.find((item) => item.value === creditOperationKind) ?? null,
    [creditOperationKindItems, creditOperationKind],
  );

  const selectedDebtDirectionItem = useMemo(
    () => debtDirectionItems.find((item) => item.value === debtDirection) ?? null,
    [debtDirectionItems, debtDirection],
  );

  const selectedTargetAccountItem = useMemo(
    () => accountItems.find((item) => item.value === selectedTargetAccountId) ?? null,
    [accountItems, selectedTargetAccountId],
  );

  const selectedCounterpartyItem = useMemo(
    () => counterpartyItems.find((item) => item.value === selectedCounterpartyId) ?? null,
    [counterpartyItems, selectedCounterpartyId],
  );

  const selectedReviewItem = useMemo(
    () => reviewItems.find((item) => item.value === needsReviewValue) ?? null,
    [reviewItems, needsReviewValue],
  );

  const showTransferTarget = mainType === 'transfer';
  const showInvestmentDirection = mainType === 'investment';
  const showCreditOperationKind = mainType === 'credit_operation';
  const showCreditPaymentFields = mainType === 'credit_operation' && creditOperationKind === 'payment';
  const showCreditEarlyRepaymentFields = mainType === 'credit_operation' && creditOperationKind === 'early_repayment';
  const showCreditRepaymentFields = showCreditPaymentFields || showCreditEarlyRepaymentFields;
  const showCreditDisbursementInfo = mainType === 'credit_operation' && creditOperationKind === 'disbursement';
  const showDebtDirection = mainType === 'debt';
  const showCounterparty = mainType === 'debt';
  const showCategory = mainType === 'regular' || mainType === 'refund';
  const showGoalField =
    goals.length > 0 &&
    (mainType === 'investment' ||
      (showCategory && selectedCategory?.priority === 'expense_target'));
  const hasValidInvestmentDirection = mainType !== 'investment' || Boolean(investmentDirection);
  const hasValidCreditOperationKind = mainType !== 'credit_operation' || Boolean(creditOperationKind);
  const hasValidDebtDirection = mainType !== 'debt' || Boolean(debtDirection);
  const hasValidCounterparty = mainType !== 'debt' || Boolean(selectedCounterpartyId);
  const hasValidTargetAccount = !showTransferTarget || (Boolean(selectedTargetAccountId) && selectedTargetAccountId !== selectedAccountId);
  const hasValidCreditAccount = !showCreditRepaymentFields || (Boolean(selectedCreditAccountId) && selectedCreditAccountId !== selectedAccountId);
  const hasValidCreditBreakdown =
    !showCreditRepaymentFields ||
    (showCreditPaymentFields
      ? Number(watch('credit_principal_amount')) >= 0 && Number(watch('credit_interest_amount')) >= 0 && Number(watch('amount')) === Number(watch('credit_principal_amount')) + Number(watch('credit_interest_amount'))
      : Number(watch('credit_principal_amount')) >= 0 && Number(watch('amount')) === Number(watch('credit_principal_amount')));
  const hasValidDirection = hasValidInvestmentDirection && hasValidCreditOperationKind && hasValidDebtDirection && hasValidTargetAccount && hasValidCreditAccount && hasValidCreditBreakdown && hasValidCounterparty;
  const resolvedOperationType = mapUiToOperation(mainType, investmentDirection || 'buy', creditOperationKind);
  const derivedType = useMemo(
    () => getDerivedType(resolvedOperationType, showCategory ? selectedCategory : null, debtDirection),
    [resolvedOperationType, selectedCategory, showCategory, debtDirection],
  );

  const showCreateAccountAction = Boolean(accountQuery.trim()) && !exactMatchedAccount;
  const showCreateCategoryAction = showCategory && Boolean(categoryQuery.trim()) && !exactMatchedCategory;
  const showCreateCreditAccountAction = showCreditRepaymentFields && Boolean(creditAccountQuery.trim()) && !exactMatchedCreditAccount;
  const showCreateCounterpartyAction = showCounterparty && Boolean(counterpartyQuery.trim()) && !exactMatchedCounterparty;
  const categoryKindForCreate = derivedType === 'income' ? 'income' : 'expense';

  useEffect(() => {
    setValue('operation_type', resolvedOperationType, { shouldValidate: true, shouldDirty: true });
  }, [resolvedOperationType, setValue]);

  // Debounced large-purchase check — only for new regular expenses
  useEffect(() => {
    if (mainType !== 'regular' || Boolean(initialData)) {
      setLargePurchaseCheck(null);
      setLargePurchaseKind('normal');
      return;
    }
    const num = Number(amountValue);
    if (!num || num <= 0) {
      setLargePurchaseCheck(null);
      setLargePurchaseKind('normal');
      return;
    }
    const timer = setTimeout(() => {
      checkLargePurchase(num)
        .then((result) => {
          setLargePurchaseCheck(result);
          if (!result.is_large) setLargePurchaseKind('normal');
        })
        .catch(() => setLargePurchaseCheck(null));
    }, 600);
    return () => clearTimeout(timer);
  }, [amountValue, mainType, initialData]);

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
    if (!showCounterparty) {
      setValue('counterparty_id', '', { shouldValidate: true, shouldDirty: true });
      setCounterpartyQuery('');
    } else if (exactMatchedCounterparty) {
      setValue('counterparty_id', String(exactMatchedCounterparty.id), { shouldValidate: true, shouldDirty: true });
    } else if (counterpartyQuery.trim()) {
      setValue('counterparty_id', '', { shouldValidate: true, shouldDirty: true });
    }
  }, [counterpartyQuery, exactMatchedCounterparty, setValue, showCounterparty]);

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
    if (!showCreditOperationKind) {
      setCreditOperationKind('');
      setCreditOperationKindQuery('');
    }
  }, [showCreditOperationKind]);

  useEffect(() => {
    if (!showCreditRepaymentFields) {
      setValue('credit_account_id', '', { shouldValidate: true });
      setValue('credit_principal_amount', '', { shouldValidate: true });
      setValue('credit_interest_amount', '', { shouldValidate: true });
      setCreditAccountQuery('');
      return;
    }

    if (exactMatchedCreditAccount) {
      setValue('credit_account_id', String(exactMatchedCreditAccount.id), { shouldValidate: true, shouldDirty: true });
    } else if (!creditAccountQuery.trim()) {
      setValue('credit_account_id', '', { shouldValidate: true, shouldDirty: true });
    }
    if (showCreditEarlyRepaymentFields) {
      setValue('credit_interest_amount', '0', { shouldValidate: true });
    }
  }, [creditAccountQuery, exactMatchedCreditAccount, setValue, showCreditRepaymentFields, showCreditEarlyRepaymentFields]);

  useEffect(() => {
    if (initialData) {
      const mapped = mapOperationToUi(initialData.operation_type, initialData.debt_direction ?? initialData.type);
      const initialAccount = accounts.find((account) => account.id === initialData.account_id) ?? null;
      const initialTargetAccount = initialData.target_account_id ? accounts.find((account) => account.id === initialData.target_account_id) ?? null : null;
      const initialCategory = initialData.category_id ? categories.find((category) => category.id === initialData.category_id) ?? null : null;

      reset({
        account_id: String(initialData.account_id),
        target_account_id: initialData.target_account_id ? String(initialData.target_account_id) : '',
        category_id: initialData.category_id ? String(initialData.category_id) : '',
        credit_account_id: initialData.credit_account_id ? String(initialData.credit_account_id) : '',
        counterparty_id: initialData.counterparty_id ? String(initialData.counterparty_id) : '',
        goal_id: initialData.goal_id ? String(initialData.goal_id) : '',
        amount: String(initialData.amount),
        credit_principal_amount: initialData.credit_principal_amount != null ? String(initialData.credit_principal_amount) : '',
        credit_interest_amount: initialData.credit_interest_amount != null ? String(initialData.credit_interest_amount) : '',
        operation_type: initialData.operation_type,
        description: initialData.description ?? '',
        transaction_date: toDatetimeLocal(initialData.transaction_date),
        needs_review: String(initialData.needs_review),
      });

      setMainType(mapped.mainType);
      setMainTypeQuery(mainTypeItems.find((item) => item.value === mapped.mainType)?.label ?? 'Обычный');
      setInvestmentDirection(mapped.investmentDirection);
      setInvestmentDirectionQuery(mapped.investmentDirection === 'buy' ? 'Покупка' : mapped.investmentDirection === 'sell' ? 'Продажа' : '');
      setCreditOperationKind(mapped.creditOperationKind);
      setCreditOperationKindQuery(mapped.creditOperationKind ? getCreditOperationKindLabel(mapped.creditOperationKind) : '');
      setDebtDirection(mapped.debtDirection);
      setDebtDirectionQuery(mapped.debtDirection === 'borrowed' ? 'Мне заняли' : mapped.debtDirection === 'lent' ? 'Я занял' : mapped.debtDirection === 'repaid' ? 'Вернул' : mapped.debtDirection === 'collected' ? 'Мне вернули' : '');
      setAccountQuery(initialAccount?.name ?? '');
      setTargetAccountQuery(initialTargetAccount?.name ?? '');
      setCategoryQuery(initialCategory?.name ?? '');
      setCounterpartyQuery(initialData.counterparty_name ?? '');
      setReviewQuery(initialData.needs_review ? 'Да' : 'Нет');
      return;
    }

    reset({ ...defaultValues, transaction_date: toDatetimeLocal(new Date().toISOString()) });
    setMainType('regular');
    setMainTypeQuery('Обычный');
    setInvestmentDirection('');
    setInvestmentDirectionQuery('');
    setCreditOperationKind('');
    setCreditOperationKindQuery('');
    setCounterpartyQuery('');
    setDebtDirection('');
    setDebtDirectionQuery('');
    setAccountQuery('');
    setTargetAccountQuery('');
    setCategoryQuery('');
    setGoalQuery('');
    setReviewQuery('Нет');
    setLargePurchaseCheck(null);
    setLargePurchaseKind('normal');
  }, [initialData, reset, accounts, categories, mainTypeItems]);

  function handleCreateAccountClick() {
    const name = accountQuery.trim() || 'Новый счёт';
    onCreateAccountRequest?.({ name });
  }

  function handleCreateCounterpartyClick() {
    const name = counterpartyQuery.trim() || 'Новый контрагент';
    const opening_balance_kind = debtDirection === 'borrowed' || debtDirection === 'repaid' ? 'payable' : 'receivable';
    onCreateCounterpartyRequest?.({ name, opening_balance_kind });
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
          credit_account_id: showCreditRepaymentFields && values.credit_account_id ? Number(values.credit_account_id) : null,
          category_id: showCategory && values.category_id ? Number(values.category_id) : null,
          counterparty_id: showCounterparty && values.counterparty_id ? Number(values.counterparty_id) : null,
          goal_id: showGoalField && values.goal_id ? Number(values.goal_id) : null,
          amount: Number(values.amount),
          credit_principal_amount: showCreditRepaymentFields ? Number(values.credit_principal_amount) : null,
          credit_interest_amount: showCreditPaymentFields ? Number(values.credit_interest_amount) : showCreditEarlyRepaymentFields ? 0 : null,
          debt_direction: showCounterparty && debtDirection ? debtDirection : null,
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
          is_deferred_purchase:
            largePurchaseCheck?.is_large && largePurchaseKind === 'deferred' ? true : undefined,
          is_large_purchase:
            largePurchaseCheck?.is_large && largePurchaseKind === 'large' ? true : undefined,
        });
      })}
    >
      <input type="hidden" {...register('operation_type', { required: true })} />
      <input type="hidden" {...register('account_id', { required: 'Выбери счёт отправления' })} />
      <input type="hidden" {...register('counterparty_id')} />
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
        {...register('credit_account_id', {
          validate: (value) => {
            if (!showCreditRepaymentFields) return true;
            if (!creditAccountQuery.trim()) return 'Выбери кредит';
            if (!value) return 'Выбери кредит из списка';
            if (value === selectedAccountId) return 'Счёт списания и кредит должны отличаться';
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
            if (nextType !== 'credit_operation') {
              setCreditOperationKind('');
              setCreditOperationKindQuery('');
            }
            if (nextType !== 'debt') {
              setDebtDirection('');
              setDebtDirectionQuery('');
            }
            if (nextType === 'refund') {
              setValue('target_account_id', '', { shouldValidate: true, shouldDirty: true });
              setTargetAccountQuery('');
              setValue('credit_account_id', '', { shouldValidate: true, shouldDirty: true });
              setCreditAccountQuery('');
              setValue('counterparty_id', '', { shouldValidate: true, shouldDirty: true });
              setCounterpartyQuery('');
              setValue('credit_principal_amount', '', { shouldValidate: true, shouldDirty: true });
              setValue('credit_interest_amount', '', { shouldValidate: true, shouldDirty: true });
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

        {showCreditOperationKind ? (
          <SearchSelect
            id="tx-credit-operation-kind"
            label="Вид кредитной операции"
            placeholder="Выбери вид"
            widthClassName="w-full"
            query={creditOperationKindQuery}
            setQuery={setCreditOperationKindQuery}
            items={creditOperationKindItems}
            selectedValue={selectedCreditOperationKindItem?.value}
            showAllOnFocus
            onSelect={(item) => {
              setCreditOperationKind(item.value as CreditOperationKind);
              setCreditOperationKindQuery(item.label);
            }}
            error={submitCount > 0 && !hasValidCreditOperationKind ? 'Выбери вид кредитной операции' : undefined}
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

        {showCounterparty ? (
          <SearchSelect
            id="tx-counterparty"
            label="Контрагент"
            placeholder="Выбери контрагента"
            widthClassName="w-full"
            query={counterpartyQuery}
            setQuery={setCounterpartyQuery}
            items={counterpartyItems}
            selectedValue={selectedCounterpartyItem?.value}
            showAllOnFocus
            onSelect={(item) => {
              setValue('counterparty_id', item.value, { shouldValidate: true, shouldDirty: true });
              setCounterpartyQuery(item.label);
            }}
            error={submitCount > 0 && !hasValidCounterparty ? 'Выбери контрагента' : undefined}
            onDeleteItem={onDeleteCounterpartyRequest ? (item) => {
              const found = counterparties.find((counterparty) => String(counterparty.id) === item.value);
              if (found) onDeleteCounterpartyRequest(found);
            } : undefined}
            deleteItemLabel="Удалить контрагента"
            createAction={
              onCreateCounterpartyRequest
                ? {
                    visible: showCreateCounterpartyAction,
                    label: 'Создать контрагента',
                    onClick: handleCreateCounterpartyClick,
                  }
                : undefined
            }
          />
        ) : null}

        <div>
          <SearchSelect
            id="tx-account"
            label={showTransferTarget ? 'Счёт отправления' : showCreditDisbursementInfo ? 'Счёт поступления' : 'Счёт'}
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

        {showCreditRepaymentFields ? (
          <div>
            <SearchSelect
              id="tx-credit-account"
              label="Кредит"
              placeholder="Выбери кредит"
              widthClassName="w-full"
              query={creditAccountQuery}
              setQuery={setCreditAccountQuery}
              items={accounts.filter((account) => isLoanAccount(account) && String(account.id) !== selectedAccountId).map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}`, badge: account.currency }))}
              selectedValue={selectedCreditAccountId}
              showAllOnFocus
              onSelect={(item) => {
                setValue('credit_account_id', item.value, { shouldValidate: true, shouldDirty: true });
                setCreditAccountQuery(item.label);
              }}
              error={errors.credit_account_id?.message || (submitCount > 0 && !hasValidCreditAccount ? 'Выбери кредит' : undefined)}
              createAction={
                onCreateAccountRequest
                  ? {
                      visible: showCreateCreditAccountAction,
                      label: 'Создать кредит',
                      onClick: () => onCreateAccountRequest({ name: creditAccountQuery.trim() }),
                    }
                  : undefined
              }
            />
          </div>
        ) : null}

        <div>
          <Label htmlFor="tx-amount">{showCreditRepaymentFields ? 'Общая сумма платежа' : showCreditDisbursementInfo ? 'Сумма кредита' : 'Сумма'}</Label>
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

        {/* ── Large-purchase banner ─────────────────────────────────────── */}
        {largePurchaseCheck?.is_large && mainType === 'regular' && !initialData ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm font-semibold text-amber-800">Крупная покупка</p>
            <p className="mt-0.5 text-xs text-amber-600">
              Сумма превышает порог {formatMoney(largePurchaseCheck.threshold_amount)} — как учесть?
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setLargePurchaseKind('normal')}
                className={cn(
                  'rounded-lg border px-3 py-1.5 text-xs font-medium transition',
                  largePurchaseKind === 'normal'
                    ? 'border-amber-500 bg-amber-100 text-amber-800'
                    : 'border-amber-200 bg-white text-amber-700 hover:bg-amber-50',
                )}
              >
                В расходы обычно
              </button>
              <button
                type="button"
                onClick={() => setLargePurchaseKind('large')}
                className={cn(
                  'rounded-lg border px-3 py-1.5 text-xs font-medium transition',
                  largePurchaseKind === 'large'
                    ? 'border-amber-500 bg-amber-100 text-amber-800'
                    : 'border-amber-200 bg-white text-amber-700 hover:bg-amber-50',
                )}
              >
                Отдельная строка
              </button>
              {selectedAccount &&
              (selectedAccount.account_type === 'credit' ||
                selectedAccount.account_type === 'installment_card' ||
                selectedAccount.is_credit) ? (
                <button
                  type="button"
                  onClick={() => setLargePurchaseKind('deferred')}
                  className={cn(
                    'rounded-lg border px-3 py-1.5 text-xs font-medium transition',
                    largePurchaseKind === 'deferred'
                      ? 'border-blue-500 bg-blue-100 text-blue-800'
                      : 'border-blue-200 bg-white text-blue-700 hover:bg-blue-50',
                  )}
                >
                  Откладывать на кредит
                </button>
              ) : null}
            </div>
            {largePurchaseKind === 'large' && (
              <p className="mt-2 text-xs text-amber-600">
                Покупка будет видна в разделе «Крупные покупки» и не войдёт в средние расходы.
              </p>
            )}
            {largePurchaseKind === 'deferred' && (
              <p className="mt-2 text-xs text-blue-600">
                Покупка будет учтена в расходах постепенно — по мере платежей по кредиту.
              </p>
            )}
          </div>
        ) : null}

        {showCreditRepaymentFields ? (
          <>
            <div>
              <Label htmlFor="tx-credit-principal">Основной долг</Label>
              <Input id="tx-credit-principal" className="h-9" type="number" step="0.01" placeholder="0.00" {...register('credit_principal_amount', { validate: (value) => !showCreditRepaymentFields || Number(value) >= 0 || 'Введите корректную сумму' })} />
            </div>
            {showCreditPaymentFields ? (
              <div>
                <Label htmlFor="tx-credit-interest">Проценты</Label>
                <Input id="tx-credit-interest" className="h-9" type="number" step="0.01" placeholder="0.00" {...register('credit_interest_amount', { validate: (value) => !showCreditPaymentFields || Number(value) >= 0 || 'Введите корректную сумму' })} />
                {submitCount > 0 && !hasValidCreditBreakdown ? <p className="mt-1 text-xs text-danger">Сумма должна быть равна основному долгу и процентам</p> : null}
              </div>
            ) : null}
          </>
        ) : null}

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

        {showGoalField ? (
          <div>
            <input type="hidden" {...register('goal_id')} />
            <SearchSelect
              id="tx-goal"
              label="Цель"
              placeholder="Не привязывать"
              widthClassName="w-full"
              query={goalQuery}
              setQuery={setGoalQuery}
              items={goalItems}
              selectedValue={selectedGoalId}
              showAllOnFocus
              onSelect={(item) => {
                setValue('goal_id', item.value, { shouldValidate: true, shouldDirty: true });
                setGoalQuery(item.label);
              }}
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
            Валюта: <strong>{selectedAccount?.currency ?? selectedTargetAccount?.currency ?? selectedCreditAccount?.currency ?? '—'}</strong>
          </span>
          <span className="text-slate-300">•</span>
          <span>{getOperationSummaryLabel(watch('operation_type'), investmentDirection, debtDirection, hasValidDebtDirection, creditOperationKind, hasValidCreditOperationKind)}</span>
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

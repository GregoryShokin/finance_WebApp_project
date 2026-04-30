/**
 * Reusable option lists + direction-aware filters for the import-row UI.
 * Mirrors the working HTML mockup so TxRow / SplitModal / BucketModal share
 * the same vocabulary.
 */

import type { CreatableOption } from '@/components/ui/creatable-select';

// ── Main operation type ──────────────────────────────────────────────────────

export type MainType =
  | 'regular'
  | 'transfer'
  | 'debt'
  | 'refund'
  | 'investment'
  | 'credit_operation';

export const TYPE_OPTIONS: CreatableOption[] = [
  { value: 'regular',          label: 'Обычная',             toneDot: '#8a8479' },
  { value: 'transfer',         label: 'Перевод',             toneDot: '#1d4f8a' },
  { value: 'debt',             label: 'Долг',                toneDot: '#b07712' },
  { value: 'refund',           label: 'Возврат',             toneDot: '#5b3a8a' },
  { value: 'investment',       label: 'Инвестиция',          toneDot: '#14613b' },
  { value: 'credit_operation', label: 'Кредитная операция',  toneDot: '#8b1f1f' },
];

// ── Debt direction ───────────────────────────────────────────────────────────

export type DebtDirection = 'borrowed' | 'lent' | 'repaid' | 'collected';

export const DEBT_DIR_OPTIONS: CreatableOption[] = [
  { value: 'borrowed',  label: 'Я взял(а) в долг' },     // income
  { value: 'collected', label: 'Мне вернули долг' },     // income
  { value: 'lent',      label: 'Я дал(а) в долг' },      // expense
  { value: 'repaid',    label: 'Я вернул(а) долг' },     // expense
];

/**
 * Filter debt-direction options by the row's money direction.
 *   expense (out) → lent / repaid
 *   income  (in)  → borrowed / collected
 */
export function debtDirOptionsFor(direction: 'income' | 'expense' | string): CreatableOption[] {
  if (direction === 'income') {
    return DEBT_DIR_OPTIONS.filter((o) => o.value === 'borrowed' || o.value === 'collected');
  }
  return DEBT_DIR_OPTIONS.filter((o) => o.value === 'lent' || o.value === 'repaid');
}

// ── Credit operation kind ────────────────────────────────────────────────────

export type CreditKind = 'disbursement' | 'payment' | 'early_repayment';

export const CREDIT_KIND_OPTIONS: CreatableOption[] = [
  { value: 'disbursement',    label: 'Получение кредита' },
  { value: 'payment',         label: 'Регулярный платёж' },
  { value: 'early_repayment', label: 'Досрочное погашение' },
];

/** Map UI credit_kind back to the backend operation_type. */
export function creditKindToOperationType(kind: CreditKind | ''): string {
  if (kind === 'disbursement')   return 'credit_disbursement';
  if (kind === 'payment')        return 'credit_payment';
  if (kind === 'early_repayment') return 'credit_early_repayment';
  return 'regular';
}
export function operationTypeToCreditKind(opType: string | undefined): CreditKind | '' {
  if (opType === 'credit_disbursement')    return 'disbursement';
  if (opType === 'credit_payment')         return 'payment';
  if (opType === 'credit_early_repayment') return 'early_repayment';
  return '';
}

// ── Investment direction ─────────────────────────────────────────────────────

export type InvestmentDirection = 'buy' | 'sell';

export const INVEST_DIR_OPTIONS: CreatableOption[] = [
  { value: 'buy',  label: 'Покупка',  toneDot: 'var(--accent-green, #14613b)' },
  { value: 'sell', label: 'Продажа',  toneDot: 'var(--accent-red, #8b1f1f)' },
];

/**
 * Investment direction is fully derived from the row's money direction:
 *   expense (money out) → buy  (we paid for the asset)
 *   income  (money in)  → sell (we sold the asset)
 * No user input needed.
 */
export function investmentDirFor(direction: 'income' | 'expense' | string): InvestmentDirection {
  return direction === 'income' ? 'sell' : 'buy';
}

/** Map UI investment_direction → backend operation_type. */
export function investmentDirToOperationType(dir: InvestmentDirection): string {
  return dir === 'sell' ? 'investment_sell' : 'investment_buy';
}

// ── Category filtering ───────────────────────────────────────────────────────

type CategoryOptionWithKind = CreatableOption & { kind?: 'income' | 'expense' };

/** Filter category options by income/expense kind. */
export function categoryOptionsForKind(
  allCategoryOptions: CategoryOptionWithKind[],
  kind: 'income' | 'expense' | null | undefined,
): CategoryOptionWithKind[] {
  if (!kind) return allCategoryOptions;
  return allCategoryOptions.filter((o) => o.kind === kind);
}

// ── Credit-only account filtering ────────────────────────────────────────────

type AccountWithType = {
  id: number;
  account_type?: string | null;
  is_credit?: boolean | null;
};

/** Keep only credit accounts (loan / credit_card / installment_card / is_credit). */
export function creditAccountOptions(
  allAccountOptions: CreatableOption[],
  allAccounts: AccountWithType[],
): CreatableOption[] {
  const creditIds = new Set(
    allAccounts
      .filter((a) => a.is_credit
        || a.account_type === 'loan'
        || a.account_type === 'credit_card'
        || a.account_type === 'installment_card')
      .map((a) => a.id),
  );
  return allAccountOptions.filter((o) => creditIds.has(Number(o.value)));
}

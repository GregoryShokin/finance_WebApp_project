'use client';

import { ChangeEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, ChevronDown, FileUp, Info, Plus, ShieldOff, Split, Trash2, Undo2 } from 'lucide-react';
import { toast } from 'sonner';

import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategoryRules } from '@/lib/api/category-rules';
import { getCategories, createCategory } from '@/lib/api/categories';
import { getCounterparties, createCounterparty, deleteCounterparty } from '@/lib/api/counterparties';
import { commitImport, getImportPreview, getImportSession, previewImport, updateImportRow, uploadImportFile } from '@/lib/api/imports';
import { DescriptionAutocomplete } from '@/components/import/description-autocomplete';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { ImportStatusBadge } from '@/components/import/import-status-badge';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { CounterpartyDialog } from '@/components/counterparties/counterparty-dialog';
import { cn } from '@/lib/utils/cn';
import { dequeueImportSession, enqueueImportSession, getQueuedImportSession } from '@/lib/utils/import-queue';
import type { Account, CreateAccountPayload } from '@/types/account';
import type { Category, CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';
import type { Counterparty, CreateCounterpartyPayload } from '@/types/counterparty';
import type {
  ImportCommitResponse,
  ImportDetection,
  ImportMappingPayload,
  ImportPreviewResponse,
  ImportPreviewRow,
  ImportRowUpdatePayload,
  ImportSessionResponse,
  ImportSourceType,
  ImportSplitItem,
  ImportUploadResponse,
} from '@/types/import';
import { operationTypeLabels, transactionTypeLabels } from '@/components/transactions/constants';

const MAPPING_FIELDS: Array<{ key: string; label: string; required?: boolean }> = [
  { key: 'date', label: 'Дата', required: true },
  { key: 'description', label: 'Описание', required: true },
  { key: 'amount', label: 'Сумма' },
  { key: 'income', label: 'Доход' },
  { key: 'expense', label: 'Расход' },
  { key: 'direction', label: 'Направление' },
  { key: 'currency', label: 'Валюта' },
  { key: 'balance_after', label: 'Остаток после операции' },
  { key: 'counterparty', label: 'Контрагент' },
  { key: 'raw_type', label: 'Тип операции' },
  { key: 'account_hint', label: 'Подсказка по счёту' },
  { key: 'source_reference', label: 'Внешний ID / reference' },
];

type UploadFormState = {
  delimiter: string;
};

type MappingState = {
  account_id: string;
  currency: string;
  date_format: string;
  table_name: string;
  field_mapping: Record<string, string>;
  skip_duplicates: boolean;
};

type MainOperationType = 'regular' | 'investment' | 'debt' | 'refund' | 'transfer' | 'credit_operation';
type InvestmentDirection = '' | 'buy' | 'sell';
type DebtDirection = '' | 'lent' | 'borrowed' | 'repaid' | 'collected';
type CreditOperationKind = '' | 'disbursement' | 'payment' | 'early_repayment';

type RowEditState = {
  account_id: string;
  target_account_id: string;
  credit_account_id: string;
  category_id: string;
  counterparty_id: string;
  amount: string;
  credit_principal_amount: string;
  credit_interest_amount: string;
  type: 'income' | 'expense';
  operation_type: string;
  description: string;
  transaction_date: string;
  currency: string;
  main_type: MainOperationType;
  investment_direction: InvestmentDirection;
  debt_direction: DebtDirection;
  credit_operation_kind: CreditOperationKind;
};

type RowQueries = {
  account_id: string;
  target_account_id: string;
  credit_account_id: string;
  category_id: string;
  counterparty_id: string;
  main_type: string;
  investment_direction: string;
  debt_direction: string;
  credit_operation_kind: string;
  import_account: string;
};

type SplitRowState = {
  category_id: string;
  counterparty_id: string;
  amount: string;
  description: string;
};

type SplitRowQueries = {
  category_id: string;
};

type ImportWizardDraft = {
  uploadForm: UploadFormState;
  mappingForm: MappingState;
  uploadResult: ImportUploadResponse | null;
  previewResult: ImportPreviewResponse | null;
  commitResult: ImportCommitResponse | null;
  rowForms: Record<number, RowEditState>;
  rowQueries: Record<number, RowQueries>;
  splitExpanded: Record<number, boolean>;
  splitRows: Record<number, SplitRowState[]>;
  splitQueries: Record<number, SplitRowQueries[]>;
};

type PendingFieldTarget =
  | { rowId: number; field: 'account_id' | 'target_account_id' | 'credit_account_id' | 'category_id' | 'counterparty_id' }
  | { rowId: number; field: 'split_category_id'; splitIndex: number }
  | { rowId: null; field: 'import_account' };

const defaultUploadForm: UploadFormState = { delimiter: ',' };
const DEFAULT_SPLIT_ROW: SplitRowState = { category_id: '', counterparty_id: '', amount: '', description: '' };
const IMPORT_DRAFT_STORAGE_KEY = 'financeapp.import-wizard.draft.v2';

const priorityLabels: Record<CategoryPriority, string> = {
  expense_essential: 'Обязательный',
  expense_secondary: 'Второстепенный',
  expense_target: 'Целевой',
  income_active: 'Активный доход',
  income_passive: 'Пассивный доход',
};

const defaultCategoryPriorityByKind: Record<CategoryKind, CategoryPriority> = {
  expense: 'expense_secondary',
  income: 'income_active',
};

function sourceLabel(source: ImportSourceType) {
  if (source === 'csv') return 'CSV';
  if (source === 'xlsx') return 'XLSX';
  return 'PDF';
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function isCreditPaymentAccount(account: Account) {
  return account.account_type === 'credit' || account.account_type === 'credit_card' || account.account_type === 'installment_card' || account.is_credit;
}

function isSelectableTransactionAccount(account: Account) {
  return account.account_type !== 'credit';
}

function isImportAccount(account: Account) {
  return account.is_active;
}

function resolveTransactionAccountId(accounts: Account[], accountId: unknown, fallbackAccountId = '') {
  const normalizedAccountId = String(accountId ?? '').trim();
  if (!normalizedAccountId) return fallbackAccountId;

  const matchedAccount = accounts.find((account) => String(account.id) === normalizedAccountId);
  if (matchedAccount && isSelectableTransactionAccount(matchedAccount)) {
    return normalizedAccountId;
  }

  return fallbackAccountId;
}

function resolveCreditAccountId(accounts: Account[], accountId: unknown) {
  const normalizedAccountId = String(accountId ?? '').trim();
  if (!normalizedAccountId) return '';

  const matchedAccount = accounts.find((account) => String(account.id) === normalizedAccountId);
  if (matchedAccount && isCreditPaymentAccount(matchedAccount)) {
    return normalizedAccountId;
  }

  return '';
}

function buildMappingState(detection: ImportDetection, accounts: Account[], selectedAccountId?: string): MappingState {
  const chosenAccount = accounts.find((account) => String(account.id) === selectedAccountId) ?? accounts[0];
  const suggestedDateFormat = detection.suggested_date_formats[0] ?? '%d.%m.%Y';
  return {
    account_id: chosenAccount ? String(chosenAccount.id) : '',
    currency: chosenAccount?.currency ?? 'RUB',
    date_format: suggestedDateFormat,
    table_name: detection.selected_table ?? detection.available_tables[0]?.name ?? '',
    field_mapping: Object.fromEntries(MAPPING_FIELDS.map((field) => [field.key, String(detection.field_mapping?.[field.key] ?? '')])),
    skip_duplicates: true,
  };
}

function toPreviewPayload(mappingForm: MappingState): ImportMappingPayload {
  return {
    account_id: Number(mappingForm.account_id),
    currency: mappingForm.currency,
    date_format: mappingForm.date_format,
    table_name: mappingForm.table_name || null,
    field_mapping: Object.fromEntries(Object.entries(mappingForm.field_mapping).map(([key, value]) => [key, value || null])),
    skip_duplicates: mappingForm.skip_duplicates,
  };
}

function buildUploadResultFromSession(session: ImportSessionResponse): ImportUploadResponse {
  const parseSettings = (session.parse_settings ?? {}) as Record<string, unknown>;
  const detection = (session.mapping_json ?? {}) as ImportDetection;
  const tables = Array.isArray(parseSettings.tables) ? (parseSettings.tables as Array<Record<string, unknown>>) : [];
  const selectedTable = typeof detection.selected_table === 'string' ? detection.selected_table : null;
  const primaryTable = tables.find((table) => table.name === selectedTable) ?? tables[0];
  const rows = Array.isArray(primaryTable?.rows) ? (primaryTable.rows as Array<Record<string, unknown>>) : [];

  return {
    session_id: session.id,
    filename: session.filename,
    source_type: session.source_type,
    status: session.status,
    detected_columns: session.detected_columns,
    sample_rows: rows.slice(0, 5).map((row) =>
      Object.fromEntries(Object.entries(row).map(([key, value]) => [key, String(value ?? '')])),
    ),
    total_rows: rows.length,
    extraction: ((parseSettings.extraction as Record<string, unknown> | undefined) ?? {}),
    detection,
    suggested_account_id: session.account_id,
    contract_number: typeof parseSettings.contract_number === 'string' ? parseSettings.contract_number : null,
    contract_match_reason: null,
    contract_match_confidence: null,
    statement_account_number:
      typeof parseSettings.statement_account_number === 'string' ? parseSettings.statement_account_number : null,
    statement_account_match_reason: null,
    statement_account_match_confidence: null,
  };
}

function statCard(
  label: string,
  value: number,
  tone: 'default' | 'success' | 'warning' | 'danger' = 'default',
  onClick?: () => void,
  active?: boolean,
) {
  const toneClass =
    tone === 'success' ? 'border-emerald-100' : tone === 'warning' ? 'border-amber-100' : tone === 'danger' ? 'border-rose-100' : 'border-slate-200';
  const activeRing = active ? 'ring-2 ring-offset-1 ' + (
    tone === 'success' ? 'ring-emerald-400' : tone === 'warning' ? 'ring-amber-400' : tone === 'danger' ? 'ring-rose-400' : 'ring-slate-400'
  ) : '';

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`rounded-2xl border ${toneClass} ${activeRing} bg-white p-4 shadow-soft text-left transition hover:brightness-95 active:scale-95`}
      >
        <div className="text-sm text-slate-500">{label}</div>
        <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
      </button>
    );
  }

  return (
    <Card className={`rounded-2xl border ${toneClass} bg-white p-4 shadow-soft`}>
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </Card>
  );
}

function mapOperationToUi(
  operationType: string | undefined,
  txType: 'income' | 'expense',
  storedDebtDirection?: string | null,
): { mainType: MainOperationType; investmentDirection: InvestmentDirection; debtDirection: DebtDirection; creditOperationKind: CreditOperationKind } {
  if (operationType === 'transfer') return { mainType: 'transfer', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
  if (operationType === 'refund') return { mainType: 'refund', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
  if (operationType === 'investment_buy') return { mainType: 'investment', investmentDirection: 'buy', debtDirection: '', creditOperationKind: '' };
  if (operationType === 'investment_sell') return { mainType: 'investment', investmentDirection: 'sell', debtDirection: '', creditOperationKind: '' };
  if (operationType === 'debt') {
    const validDirections: DebtDirection[] = ['lent', 'borrowed', 'repaid', 'collected'];
    const debtDirection: DebtDirection =
      storedDebtDirection && (validDirections as string[]).includes(storedDebtDirection)
        ? (storedDebtDirection as DebtDirection)
        : txType === 'income' ? 'borrowed' : 'lent';
    return { mainType: 'debt', investmentDirection: '', debtDirection, creditOperationKind: '' };
  }
  if (operationType === 'credit_disbursement') {
    return { mainType: 'credit_operation', investmentDirection: '', debtDirection: '', creditOperationKind: 'disbursement' };
  }
  if (operationType === 'credit_payment') {
    return { mainType: 'credit_operation', investmentDirection: '', debtDirection: '', creditOperationKind: 'payment' };
  }
  if (operationType === 'credit_early_repayment') {
    return { mainType: 'credit_operation', investmentDirection: '', debtDirection: '', creditOperationKind: 'early_repayment' };
  }
  return { mainType: 'regular', investmentDirection: '', debtDirection: '', creditOperationKind: '' };
}

function resolveOperationFields(form: RowEditState): Pick<RowEditState, 'operation_type' | 'type'> {
  if (form.main_type === 'transfer') return { operation_type: 'transfer', type: form.type };
  if (form.main_type === 'refund') return { operation_type: 'refund', type: 'income' };
  if (form.main_type === 'investment') {
    return { operation_type: form.investment_direction === 'sell' ? 'investment_sell' : 'investment_buy', type: form.investment_direction === 'sell' ? 'income' : 'expense' };
  }
  if (form.main_type === 'debt') {
    return { operation_type: 'debt', type: form.debt_direction === 'borrowed' || form.debt_direction === 'collected' ? 'income' : 'expense' };
  }
  if (form.main_type === 'credit_operation') {
    const opTypeByKind: Record<CreditOperationKind, string> = {
      '': 'credit_payment',
      disbursement: 'credit_disbursement',
      payment: 'credit_payment',
      early_repayment: 'credit_early_repayment',
    };
    return {
      operation_type: opTypeByKind[form.credit_operation_kind] ?? 'credit_payment',
      type: form.credit_operation_kind === 'disbursement' ? 'income' : 'expense',
    };
  }
  return { operation_type: 'regular', type: form.type };
}


function getMainTypeLabel(value: MainOperationType) {
  if (value === 'regular') return 'Обычный';
  if (value === 'investment') return 'Инвестиционный';
  if (value === 'debt') return 'Долг';
  if (value === 'refund') return 'Возврат';
  if (value === 'transfer') return 'Перевод';
  return 'Кредитная операция';
}

function getCreditOperationKindLabel(value: CreditOperationKind) {
  if (value === 'disbursement') return 'Получение кредита';
  if (value === 'payment') return 'Платёж по кредиту';
  if (value === 'early_repayment') return 'Досрочное погашение';
  return '';
}

function getRowEditState(row: ImportPreviewRow, accounts: Account[], fallbackAccountId = ''): RowEditState {
  const rawType = (String(row.normalized_data.type ?? 'expense') as 'income' | 'expense') ?? 'expense';
  const operationType = String(row.normalized_data.operation_type ?? 'regular');
  const ui = mapOperationToUi(operationType, rawType, row.normalized_data.debt_direction as string | null);
  const resolvedAccountId = resolveTransactionAccountId(accounts, row.normalized_data.account_id, fallbackAccountId);
  const resolvedTargetAccountId = resolveTransactionAccountId(accounts, row.normalized_data.target_account_id, '');
  const resolvedCreditAccountId = resolveCreditAccountId(
    accounts,
    row.normalized_data.credit_account_id ?? row.normalized_data.target_account_id,
  );

  return {
    account_id: resolvedAccountId,
    target_account_id: resolvedTargetAccountId,
    credit_account_id: resolvedCreditAccountId,
    category_id: row.normalized_data.category_id ? String(row.normalized_data.category_id) : '',
    counterparty_id: row.normalized_data.counterparty_id ? String(row.normalized_data.counterparty_id) : '',
    amount: String(row.normalized_data.amount ?? ''),
    credit_principal_amount: String(row.normalized_data.credit_principal_amount ?? ''),
    credit_interest_amount: String(row.normalized_data.credit_interest_amount ?? ''),
    type: rawType,
    operation_type: operationType,
    description: String(row.normalized_data.description ?? ''),
    transaction_date: String(row.normalized_data.transaction_date ?? row.normalized_data.date ?? '').slice(0, 10),
    currency: String(row.normalized_data.currency ?? 'RUB'),
    main_type: ui.mainType,
    investment_direction: ui.investmentDirection,
    debt_direction: ui.debtDirection,
    credit_operation_kind: ui.creditOperationKind,
  };
}

function getInitialQueries(
  row: ImportPreviewRow,
  accounts: Account[],
  categories: Category[],
  counterparties: Counterparty[],
  importAccountName: string,
  fallbackAccountId = '',
): RowQueries {
  const state = getRowEditState(row, accounts, fallbackAccountId);
  return {
    account_id: accounts.find((item) => String(item.id) === state.account_id)?.name ?? '',
    target_account_id: accounts.find((item) => String(item.id) === state.target_account_id)?.name ?? '',
    credit_account_id: accounts.find((item) => String(item.id) === state.credit_account_id)?.name ?? '',
    category_id: categories.find((item) => String(item.id) === state.category_id)?.name ?? '',
    counterparty_id: counterparties.find((item) => String(item.id) === state.counterparty_id)?.name ?? '',
    main_type: getMainTypeLabel(state.main_type),
    investment_direction: state.investment_direction === 'sell' ? 'Продажа' : state.investment_direction === 'buy' ? 'Покупка' : '',
    debt_direction: state.debt_direction === 'borrowed' ? 'Мне заняли' : state.debt_direction === 'lent' ? 'Я занял' : state.debt_direction === 'repaid' ? 'Вернул' : state.debt_direction === 'collected' ? 'Мне вернули' : '',
    credit_operation_kind: getCreditOperationKindLabel(state.credit_operation_kind),
    import_account: importAccountName,
  };
}

function getSplitState(row: ImportPreviewRow): SplitRowState[] {
  const items = Array.isArray(row.normalized_data.split_items) ? row.normalized_data.split_items : [];
  if (!items.length) {
    return [{ ...DEFAULT_SPLIT_ROW }, { ...DEFAULT_SPLIT_ROW }];
  }
  return items.map((item) => ({
    category_id: item && typeof item === 'object' && 'category_id' in item ? String((item as Record<string, unknown>).category_id ?? '') : '',
    amount: item && typeof item === 'object' && 'amount' in item ? String((item as Record<string, unknown>).amount ?? '') : '',
    counterparty_id: '',
    description: item && typeof item === 'object' && 'description' in item ? String((item as Record<string, unknown>).description ?? '') : '',
  }));
}

function getSplitQueries(rows: SplitRowState[], categories: Category[]): SplitRowQueries[] {
  return rows.map((row) => ({
    category_id: categories.find((item) => String(item.id) === row.category_id)?.name ?? '',
  }));
}

function isRegularSplitApplicable(form: RowEditState) {
  return form.main_type === 'regular';
}

function toNumericValue(value: string) {
  if (!value.trim()) return null;
  return Number(value.replace(',', '.'));
}

function buildRowUpdatePayload(
  row: ImportPreviewRow,
  form: RowEditState,
  splitExpandedMap: Record<number, boolean>,
  splitRowsMap: Record<number, SplitRowState[]>,
): ImportRowUpdatePayload {
  const resolved = resolveOperationFields(form);
  const previewType =
    String(row.normalized_data.type ?? '') === 'income'
      ? 'income'
      : String(row.normalized_data.type ?? '') === 'expense'
        ? 'expense'
        : null;
  const effectiveType =
    resolved.operation_type === 'transfer'
      ? (previewType ?? resolved.type)
      : resolved.type;
  const activeSplit = Boolean(splitExpandedMap[row.id]) && form.main_type === 'regular';
  const splitPayload: ImportSplitItem[] | undefined = activeSplit
    ? (splitRowsMap[row.id] ?? getSplitState(row)).map((item) => ({
        category_id: Number(item.category_id),
        amount: Number(String(item.amount).replace(',', '.')),
        description: item.description || form.description || null,
      }))
    : [];

  const isCreditPayLike =
    resolved.operation_type === 'credit_payment' || resolved.operation_type === 'credit_early_repayment';
  return {
    account_id: form.account_id ? Number(form.account_id) : null,
    target_account_id: resolved.operation_type === 'transfer'
      ? (form.target_account_id ? Number(form.target_account_id) : null)
      : isCreditPayLike
        ? (form.credit_account_id ? Number(form.credit_account_id) : null)
        : null,
    credit_account_id: isCreditPayLike
      ? (form.credit_account_id ? Number(form.credit_account_id) : null)
      : null,
    category_id: resolved.operation_type === 'regular' || resolved.operation_type === 'refund' ? (splitPayload && splitPayload.length >= 2 ? null : form.category_id ? Number(form.category_id) : null) : null,
    counterparty_id: resolved.operation_type === 'debt' ? (form.counterparty_id ? Number(form.counterparty_id) : null) : null,
    amount: toNumericValue(form.amount),
    type: effectiveType,
    operation_type: resolved.operation_type,
    debt_direction: resolved.operation_type === 'debt' ? form.debt_direction || null : null,
    description: form.description,
    transaction_date: form.transaction_date ? new Date(form.transaction_date).toISOString() : null,
    currency: form.currency,
    credit_principal_amount: isCreditPayLike
      ? toNumericValue(form.credit_principal_amount)
      : null,
    credit_interest_amount:
      resolved.operation_type === 'credit_payment'
        ? toNumericValue(form.credit_interest_amount)
        : resolved.operation_type === 'credit_early_repayment'
          ? 0
          : null,
    split_items: splitPayload,
  };
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, innerValue]) => [key, stableValue(innerValue)])
    );
  }
  return value;
}

function arePayloadsEqual(left: ImportRowUpdatePayload, right: ImportRowUpdatePayload) {
  return JSON.stringify(stableValue(left)) === JSON.stringify(stableValue(right));
}

type Props = {
  initialSessionId?: number;
  onSessionCreated?: () => void;
  sidebar?: ReactNode;
};

export function ImportWizard({ initialSessionId, onSessionCreated, sidebar }: Props) {
  const queryClient = useQueryClient();
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'import-preview'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties', 'import-preview'], queryFn: getCounterparties });
  const categoryRulesQuery = useQuery({ queryKey: ['category-rules'], queryFn: getCategoryRules });

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [uploadForm, setUploadForm] = useState<UploadFormState>(defaultUploadForm);
  const [mappingForm, setMappingForm] = useState<MappingState>({
    account_id: '',
    currency: 'RUB',
    date_format: '%d.%m.%Y',
    table_name: '',
    field_mapping: {},
    skip_duplicates: true,
  });
  const [uploadResult, setUploadResult] = useState<ImportUploadResponse | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitResponse | null>(null);
  const [rowForms, setRowForms] = useState<Record<number, RowEditState>>({});
  const [rowQueries, setRowQueries] = useState<Record<number, RowQueries>>({});
  const [splitExpanded, setSplitExpanded] = useState<Record<number, boolean>>({});
  const [splitRows, setSplitRows] = useState<Record<number, SplitRowState[]>>({});
  const [splitQueries, setSplitQueries] = useState<Record<number, SplitRowQueries[]>>({});
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [counterpartyDialogOpen, setCounterpartyDialogOpen] = useState(false);
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);
  const [pendingCounterpartyDraft, setPendingCounterpartyDraft] = useState<Partial<CreateCounterpartyPayload> | null>(null);
  const [draftHydrated, setDraftHydrated] = useState(false);
  const [pendingFieldTarget, setPendingFieldTarget] = useState<PendingFieldTarget | null>(null);

  const accounts = accountsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const counterparties = counterpartiesQuery.data ?? [];
  const categoryRules = categoryRulesQuery.data ?? [];
  const previewRows = previewResult?.rows ?? [];

  const isRowDirty = (row: ImportPreviewRow) => {
    const currentPayload = buildRowUpdatePayload(row, getRowForm(row), splitExpanded, splitRows);
    const savedSplitRows = splitExpanded[row.id] ? { [row.id]: getSplitState(row) } : {};
    const savedPayload = buildRowUpdatePayload(row, getRowEditState(row, accounts, mappingForm.account_id), splitExpanded, savedSplitRows);
    return !arePayloadsEqual(currentPayload, savedPayload);
  };

  const previewSummary = useMemo(() => {
    if (!previewResult) return null;

    return previewRows.reduce(
      (summary, row) => {
        const effectiveStatus = isRowDirty(row) && row.status === 'ready' ? 'warning' : row.status;
        if (effectiveStatus === 'ready') summary.ready_rows += 1;
        else if (effectiveStatus === 'warning') summary.warning_rows += 1;
        else if (effectiveStatus === 'error') summary.error_rows += 1;
        else if (effectiveStatus === 'duplicate') summary.duplicate_rows += 1;
        else if (effectiveStatus === 'skipped') summary.skipped_rows += 1;
        return summary;
      },
      {
        total_rows: previewRows.length,
        ready_rows: 0,
        warning_rows: 0,
        error_rows: 0,
        duplicate_rows: 0,
        skipped_rows: 0,
      }
    );
  }, [previewResult, previewRows, rowForms, splitExpanded, splitRows, accounts, mappingForm.account_id]);

  useEffect(() => {
    if (!previewRows.length) return;

    setRowForms((prev) => {
      let changed = false;
      const nextEntries = Object.entries(prev).map(([rowId, form]) => {
        const fallbackAccountId = resolveTransactionAccountId(accounts, mappingForm.account_id, '');
        const nextAccountId = resolveTransactionAccountId(accounts, form.account_id, fallbackAccountId);
        const nextTargetAccountId = form.main_type === 'transfer'
          ? resolveTransactionAccountId(accounts, form.target_account_id, '')
          : '';
        const nextCreditAccountId = form.main_type === 'credit_operation' && (form.credit_operation_kind === 'payment' || form.credit_operation_kind === 'early_repayment')
          ? resolveCreditAccountId(accounts, form.credit_account_id)
          : '';

        if (nextAccountId === form.account_id && nextTargetAccountId === form.target_account_id && nextCreditAccountId === form.credit_account_id) {
          return [rowId, form] as const;
        }

        changed = true;
        return [
          rowId,
          {
            ...form,
            account_id: nextAccountId,
            target_account_id: nextTargetAccountId,
            credit_account_id: nextCreditAccountId,
          },
        ] as const;
      });

      return changed ? Object.fromEntries(nextEntries) : prev;
    });
  }, [accounts, mappingForm.account_id, previewRows]);

    useEffect(() => {
    if (draftHydrated || typeof window === 'undefined') return;

    if (initialSessionId) {
      setDraftHydrated(true);
      return;
    }

    try {
      const rawDraft = window.localStorage.getItem(IMPORT_DRAFT_STORAGE_KEY);

      if (!rawDraft) {
        setDraftHydrated(true);
        return;
      }

      const draft = JSON.parse(rawDraft) as ImportWizardDraft;

      setUploadForm(draft.uploadForm ?? defaultUploadForm);
      setMappingForm(
        draft.mappingForm ?? {
          account_id: '',
          currency: 'RUB',
          date_format: '%d.%m.%Y',
          table_name: '',
          field_mapping: {},
          skip_duplicates: true,
        },
      );
      setUploadResult(draft.uploadResult ?? null);
      setPreviewResult(draft.previewResult ?? null);
      setCommitResult(draft.commitResult ?? null);
      setRowForms(draft.rowForms ?? {});
      setRowQueries(draft.rowQueries ?? {});
      setSplitExpanded(draft.splitExpanded ?? {});
      setSplitRows(draft.splitRows ?? {});
      setSplitQueries(draft.splitQueries ?? {});
    } catch (error) {
      console.error('Не удалось восстановить черновик импорта', error);
      window.localStorage.removeItem(IMPORT_DRAFT_STORAGE_KEY);
    } finally {
      setDraftHydrated(true);
    }
  }, [draftHydrated, initialSessionId]);

  // After draft hydration: if we restored a previewResult from localStorage,
  // re-fetch existing rows from server to sync with latest state (IDs, edits).
  // Uses GET /preview (read-only) to preserve user edits — POST would
  // rebuild rows from scratch and destroy all manual category/type changes.
  useEffect(() => {
    if (!draftHydrated) return;
    if (initialSessionId) return; // handled by the other effect below
    if (!uploadResult?.session_id) return;
    if (!previewResult) return;
    const sid = uploadResult.session_id;
    getImportPreview(sid)
      .then((fresh) => setPreviewResult(fresh))
      .catch(() => { /* stale cache — user can rebuild manually */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftHydrated]);

  const loadedSessionIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (!initialSessionId || !draftHydrated || accounts.length === 0) return;
    if (loadedSessionIdRef.current === initialSessionId) return;
    loadedSessionIdRef.current = initialSessionId;

    let cancelled = false;

    async function loadSession() {
      try {
        const session = await getImportSession(initialSessionId!);
        if (cancelled) return;

        const queuedSession = getQueuedImportSession(initialSessionId!);
        const fallbackAccountId = queuedSession?.accountId ?? mappingForm.account_id;
        const restoredUploadResult = buildUploadResultFromSession(session);
        const nextMapping = buildMappingState(
          restoredUploadResult.detection,
          accounts,
          session.account_id ? String(session.account_id) : fallbackAccountId,
        );
        const delimiter =
          typeof (session.parse_settings as Record<string, unknown> | undefined)?.delimiter === 'string'
            ? String((session.parse_settings as Record<string, unknown>).delimiter)
            : defaultUploadForm.delimiter;

        setSelectedFile(null);
        setUploadForm({ delimiter });
        setUploadResult(restoredUploadResult);
        setPreviewResult(null);
        setCommitResult(null);
        setRowForms({});
        setRowQueries({});
        setSplitExpanded({});
        setSplitRows({});
        setSplitQueries({});
        setMappingForm({
          ...nextMapping,
          account_id: session.account_id ? String(session.account_id) : nextMapping.account_id,
          currency: session.currency ?? nextMapping.currency,
        });

        const resolvedMapping = {
          ...nextMapping,
          account_id: session.account_id ? String(session.account_id) : nextMapping.account_id,
          currency: session.currency ?? nextMapping.currency,
        };
        const hasDetectedFields = Object.values(restoredUploadResult.detection.field_mapping ?? {}).some(Boolean);

        if (session.status === 'preview_ready') {
          const preview = await getImportPreview(session.id);
          if (cancelled) return;

          setPreviewResult(preview);
          setCommitResult(null);
          setRowForms({});
          setRowQueries({});
          setSplitExpanded({});
          setSplitRows({});
          setSplitQueries({});
        } else if (session.status === 'analyzed' && resolvedMapping.account_id && hasDetectedFields) {
          const preview = await previewImport(session.id, toPreviewPayload({
            ...resolvedMapping,
          }));
          if (cancelled) return;

          setPreviewResult(preview);
          setCommitResult(null);
          setRowForms({});
          setRowQueries({});
          setSplitExpanded({});
          setSplitRows({});
          setSplitQueries({});
        }

        dequeueImportSession(session.id);
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : 'Не удалось загрузить сессию импорта';
          toast.error(message);
        }
      }
    }

    loadSession();

    return () => {
      cancelled = true;
    };
  }, [accounts, draftHydrated, initialSessionId, mappingForm.account_id]);

  useEffect(() => {
    if (!draftHydrated || typeof window === 'undefined') return;

    const hasDraft = Boolean(uploadResult || (previewResult && previewResult.rows.length > 0));

    if (!hasDraft) {
      window.localStorage.removeItem(IMPORT_DRAFT_STORAGE_KEY);
      return;
    }

    const draft: ImportWizardDraft = {
      uploadForm,
      mappingForm,
      uploadResult,
      previewResult,
      commitResult,
      rowForms,
      rowQueries,
      splitExpanded,
      splitRows,
      splitQueries,
    };

    window.localStorage.setItem(IMPORT_DRAFT_STORAGE_KEY, JSON.stringify(draft));
  }, [
    draftHydrated,
    uploadForm,
    mappingForm,
    uploadResult,
    previewResult,
    commitResult,
    rowForms,
    rowQueries,
    splitExpanded,
    splitRows,
    splitQueries,
  ]);

  const importAccount = useMemo(
    () => accounts.find((account) => String(account.id) === mappingForm.account_id) ?? null,
    [accounts, mappingForm.account_id],
  );

  const importAccountItems = useMemo<SearchSelectItem[]>(() => accounts.filter(isImportAccount).map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}`, badge: account.currency })), [accounts]);
  const accountItems = useMemo<SearchSelectItem[]>(() => accounts.filter(isSelectableTransactionAccount).map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}`, badge: account.currency })), [accounts]);
  const creditAccountItems = useMemo<SearchSelectItem[]>(() => accounts.filter(isCreditPaymentAccount).map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}`, badge: account.currency })), [accounts]);
  const mainTypeItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'regular', label: 'Обычный', searchText: 'обычный обычная regular' },
    { value: 'investment', label: 'Инвестиционный', searchText: 'инвестиционный инвестиции investment' },
    { value: 'debt', label: 'Долг', searchText: 'долг заем занял мне заняли вернул мне вернули debt' },
    { value: 'refund', label: 'Возврат', searchText: 'возврат refund' },
    { value: 'transfer', label: 'Перевод', searchText: 'перевод transfer между счетами' },
    { value: 'credit_operation', label: 'Кредитная операция', searchText: 'кредитная операция кредит loan credit payment disbursement' },
  ], []);
  const investmentDirectionItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'buy', label: 'Покупка', searchText: 'покупка buy' },
    { value: 'sell', label: 'Продажа', searchText: 'продажа sell' },
  ], []);
  const debtDirectionItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'lent', label: 'Я занял', searchText: 'я занял выдал дал в долг расход' },
    { value: 'borrowed', label: 'Мне заняли', searchText: 'мне заняли взял в долг доход' },
    { value: 'repaid', label: 'Вернул', searchText: 'вернул погасил долг отдал долг' },
    { value: 'collected', label: 'Мне вернули', searchText: 'мне вернули возврат долга вернули деньги' },
  ], []);
  const counterpartyItems = useMemo<SearchSelectItem[]>(() =>
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
  const creditOperationKindItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'disbursement', label: 'Получение кредита', searchText: 'получение кредита кредит получен disbursement loan' },
    { value: 'payment', label: 'Платёж по кредиту', searchText: 'платеж по кредиту погашение кредита payment loan' },
    { value: 'early_repayment', label: 'Досрочное погашение', searchText: 'досрочное погашение досрочка early repayment prepayment' },
  ], []);

  const previewMutation = useMutation({
    mutationFn: ({ sessionId, payload }: { sessionId: number; payload: ImportMappingPayload }) => previewImport(sessionId, payload),
    onSuccess: (data) => {
      setPreviewResult(data);
      setCommitResult(null);
      setRowForms({});
      setRowQueries({});
      setSplitExpanded({});
      setSplitRows({});
      setSplitQueries({});
      toast.success('Черновик импорта обновлён');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось построить preview'),
  });

  const uploadMutation = useMutation({
    mutationFn: uploadImportFile,
    onError: (error: Error) => toast.error(error.message || 'Не удалось загрузить источник'),
  });

    const commitMutation = useMutation({
    mutationFn: ({ sessionId, importReadyOnly }: { sessionId: number; importReadyOnly: boolean }) => commitImport(sessionId, importReadyOnly),
    onSuccess: async (data) => {
      const remainingRows = Array.isArray(data?.remaining_rows) ? data.remaining_rows : [];

      setCommitResult(data);

      setPreviewResult((prev) =>
        prev
          ? {
              ...prev,
              status: data.status,
              summary: data.summary,
              rows: remainingRows,
            }
          : prev
      );

      setRowForms((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([rowId]) =>
            remainingRows.some((row) => String(row.id) === rowId)
          )
        )
      );

      setRowQueries((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([rowId]) =>
            remainingRows.some((row) => String(row.id) === rowId)
          )
        )
      );

      setSplitExpanded((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([rowId]) =>
            remainingRows.some((row) => String(row.id) === rowId)
          )
        )
      );

      setSplitRows((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([rowId]) =>
            remainingRows.some((row) => String(row.id) === rowId)
          )
        )
      );

      setSplitQueries((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([rowId]) =>
            remainingRows.some((row) => String(row.id) === rowId)
          )
        )
      );

      if (remainingRows.length === 0) {
        setUploadResult(null);
      }

      toast.success(
        data.imported_count > 0
          ? 'Готовые транзакции импортированы'
          : 'Нет готовых транзакций для импорта'
      );

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
        queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось завершить импорт'),
  });

  const rowMutation = useMutation({
    mutationFn: ({ rowId, payload }: { rowId: number; payload: Parameters<typeof updateImportRow>[1] }) => updateImportRow(rowId, payload),
    onSuccess: (data) => {
      setPreviewResult((prev) => prev ? ({ ...prev, summary: data.summary, rows: prev.rows.map((row) => row.id === data.row.id ? data.row : row) }) : prev);
      setRowForms((prev) => ({ ...prev, [data.row.id]: getRowEditState(data.row, accounts, mappingForm.account_id) }));
      setRowQueries((prev) => ({
        ...prev,
        [data.row.id]: getInitialQueries(data.row, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id),
      }));
      if (Array.isArray(data.row.normalized_data.split_items) && data.row.normalized_data.split_items.length > 0) {
        const nextRows = getSplitState(data.row);
        setSplitRows((prev) => ({ ...prev, [data.row.id]: nextRows }));
        setSplitQueries((prev) => ({ ...prev, [data.row.id]: getSplitQueries(nextRows, categories) }));
        setSplitExpanded((prev) => ({ ...prev, [data.row.id]: true }));
      }
      toast.success(data.row.status === 'ready' ? 'Статус изменён на «Готов»' : 'Строка обновлена');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось обновить строку'),
  });

  const createAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      if (pendingFieldTarget?.field === 'import_account') {
        setMappingForm((prev) => ({ ...prev, account_id: String(created.id), currency: created.currency }));
        setRowQueries((prev) => Object.fromEntries(Object.entries(prev).map(([rowId, value]) => [rowId, { ...value, import_account: created.name }])));
      }
      if (pendingFieldTarget && pendingFieldTarget.field === 'account_id') {
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, mappingForm.account_id)), account_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id)), account_id: created.name } }));
      }
      if (pendingFieldTarget && pendingFieldTarget.field === 'target_account_id') {
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, mappingForm.account_id)), target_account_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id)), target_account_id: created.name } }));
      }
      setPendingFieldTarget(null);
      setPendingAccountDraft(null);
      setAccountDialogOpen(false);
      toast.success('Счёт создан');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать счёт'),
  });

  const createCategoryMutation = useMutation({
    mutationFn: createCategory,
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
      if (pendingFieldTarget && pendingFieldTarget.field === 'category_id') {
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, mappingForm.account_id)), category_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id)), category_id: created.name } }));
      }
      if (pendingFieldTarget && pendingFieldTarget.field === 'split_category_id') {
        setSplitRows((prev) => ({
          ...prev,
          [pendingFieldTarget.rowId]: (prev[pendingFieldTarget.rowId] ?? [{ ...DEFAULT_SPLIT_ROW }, { ...DEFAULT_SPLIT_ROW }]).map((item, index) => index === pendingFieldTarget.splitIndex ? { ...item, category_id: String(created.id) } : item),
        }));
        setSplitQueries((prev) => ({
          ...prev,
          [pendingFieldTarget.rowId]: (prev[pendingFieldTarget.rowId] ?? getSplitQueries(splitRows[pendingFieldTarget.rowId] ?? [{ ...DEFAULT_SPLIT_ROW }, { ...DEFAULT_SPLIT_ROW }], categories)).map((item, index) => index === pendingFieldTarget.splitIndex ? { ...item, category_id: created.name } : item),
        }));
      }
      setPendingFieldTarget(null);
      setPendingCategoryDraft(null);
      setCategoryDialogOpen(false);
      toast.success('Категория создана');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать категорию'),
  });


  const createCounterpartyMutation = useMutation({
    mutationFn: createCounterparty,
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties', 'import-preview'] });
      if (pendingFieldTarget && pendingFieldTarget.field === 'counterparty_id') {
        setRowForms((prev) => ({
          ...prev,
          [pendingFieldTarget.rowId]: {
            ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, mappingForm.account_id)),
            counterparty_id: String(created.id),
          },
        }));
        setRowQueries((prev) => ({
          ...prev,
          [pendingFieldTarget.rowId]: {
            ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id)),
            counterparty_id: created.name,
          },
        }));
      }
      setPendingFieldTarget(null);
      setPendingCounterpartyDraft(null);
      setCounterpartyDialogOpen(false);
      toast.success('Контрагент создан');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать контрагента'),
  });

  const deleteCounterpartyMutation = useMutation({
    mutationFn: deleteCounterparty,
    onSuccess: async (_, counterpartyId) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties', 'import-preview'] });
      setRowForms((prev) => Object.fromEntries(Object.entries(prev).map(([rowId, form]) => [rowId, form.counterparty_id === String(counterpartyId) ? { ...form, counterparty_id: '' } : form])));
      setRowQueries((prev) => Object.fromEntries(Object.entries(prev).map(([rowId, query]) => [rowId, query.counterparty_id && (rowForms[Number(rowId)]?.counterparty_id === String(counterpartyId)) ? { ...query, counterparty_id: '' } : query])));
      toast.success('Контрагент удалён');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось удалить контрагента'),
  });

  function resetAll() {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(IMPORT_DRAFT_STORAGE_KEY);
    }
    setSelectedFile(null);
    setUploadForm(defaultUploadForm);
    setUploadResult(null);
    setPreviewResult(null);
    setCommitResult(null);
    setRowForms({});
    setRowQueries({});
    setSplitExpanded({});
    setSplitRows({});
    setSplitQueries({});
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
  }

  function handleUpload({ goToPreview }: { goToPreview: boolean }) {
    if (!selectedFile) {
      toast.error('Выбери CSV, XLSX или PDF');
      return;
    }
    if (!mappingForm.account_id) {
      toast.error('Выбери счёт, на который импортируется выписка');
      return;
    }
    uploadMutation.mutate(
      { file: selectedFile, delimiter: uploadForm.delimiter },
      {
        onSuccess: (data) => {
          const suggestedId = data.suggested_account_id ? String(data.suggested_account_id) : undefined;
          const nextMapping = buildMappingState(
            data.detection,
            accounts,
            suggestedId ?? mappingForm.account_id,
          );

          setUploadResult(data);
          setPreviewResult(null);
          setCommitResult(null);
          setMappingForm(nextMapping);
          queryClient.invalidateQueries({ queryKey: ['import-sessions'] });

          const hasDetectedFields = Object.values(data.detection.field_mapping).some(Boolean);
          if (!hasDetectedFields) {
            const extraction = data.extraction as Record<string, unknown>;
            const isPdf = data.source_type === 'pdf';
            const parsedCount = typeof extraction?.parsed_transaction_count === 'number' ? extraction.parsed_transaction_count : -1;
            if (isPdf && parsedCount === 0) {
              toast.error('Выписка не содержит транзакций — проверь период выгрузки в приложении банка');
            } else {
              toast.error('Формат файла не распознан — структура выписки не поддерживается');
            }
            return;
          }

          if (!goToPreview) {
            enqueueImportSession({ id: data.session_id, accountId: nextMapping.account_id });
            toast.success('Выписка добавлена в очередь');
            resetAll();
            onSessionCreated?.();
            return;
          }

          toast.success('Источник загружен и распознан');
          if (data.suggested_account_id) {
            const accountName = accounts.find((account) => account.id === data.suggested_account_id)?.name;
            toast.success(`Определён счёт: ${accountName ?? 'счёт'}. Проверь и подтверди.`);
          }
          if (!nextMapping.account_id) {
            toast.error('Сначала создай или выбери счёт для импорта');
            return;
          }
          previewMutation.mutate({ sessionId: data.session_id, payload: toPreviewPayload(nextMapping) });
        },
      },
    );
  }

  function rebuildPreview(nextForm: MappingState) {
    if (!uploadResult) return;
    if (previewMutation.isPending) return;
    if (!nextForm.account_id) {
      toast.error('Выбери счёт для импорта');
      return;
    }
    const hasDetectedFields = Object.values(uploadResult.detection.field_mapping).some(Boolean);
    if (!hasDetectedFields) return;
    setMappingForm(nextForm);
    previewMutation.mutate({ sessionId: uploadResult.session_id, payload: toPreviewPayload(nextForm) });
  }

  function getRowForm(row: ImportPreviewRow) {
    return rowForms[row.id] ?? getRowEditState(row, accounts, mappingForm.account_id);
  }

  function updateRowForm(rowId: number, patch: Partial<RowEditState>) {
    setRowForms((prev) => ({
      ...prev,
      [rowId]: {
        ...(prev[rowId] ?? getRowEditState(previewRows.find((item) => item.id === rowId)!, accounts, mappingForm.account_id)),
        ...patch,
      },
    }));
  }

  function getRowQuery(row: ImportPreviewRow) {
    return rowQueries[row.id] ?? getInitialQueries(row, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id);
  }

  function updateRowQuery(rowId: number, patch: Partial<RowQueries>) {
    const baseRow = previewRows.find((item) => item.id === rowId);
    if (!baseRow) return;
    setRowQueries((prev) => ({
      ...prev,
      [rowId]: {
        ...(prev[rowId] ?? getInitialQueries(baseRow, accounts, categories, counterparties, importAccount?.name ?? '', mappingForm.account_id)),
        ...patch,
      },
    }));
  }

  function getSplitRowsForRow(row: ImportPreviewRow) {
    return splitRows[row.id] ?? getSplitState(row);
  }

  function getSplitQueriesForRow(row: ImportPreviewRow) {
    const rows = getSplitRowsForRow(row);
    return splitQueries[row.id] ?? getSplitQueries(rows, categories);
  }

  function updateSplitRow(rowId: number, index: number, patch: Partial<SplitRowState>) {
    const sourceRow = previewRows.find((item) => item.id === rowId);
    if (!sourceRow) return;
    const current = getSplitRowsForRow(sourceRow);
    setSplitRows((prev) => ({
      ...prev,
      [rowId]: current.map((item, currentIndex) => currentIndex === index ? { ...item, ...patch } : item),
    }));
  }

  function updateSplitQuery(rowId: number, index: number, patch: Partial<SplitRowQueries>) {
    const sourceRow = previewRows.find((item) => item.id === rowId);
    if (!sourceRow) return;
    const current = getSplitQueriesForRow(sourceRow);
    setSplitQueries((prev) => ({
      ...prev,
      [rowId]: current.map((item, currentIndex) => currentIndex === index ? { ...item, ...patch } : item),
    }));
  }

  function toggleSplit(row: ImportPreviewRow) {
    const form = getRowForm(row);
    if (!isRegularSplitApplicable(form)) return;
    const nextOpen = !splitExpanded[row.id];
    setSplitExpanded((prev) => ({ ...prev, [row.id]: nextOpen }));
    if (!splitRows[row.id]) {
      const rows = getSplitRowsForRow(row);
      setSplitRows((prev) => ({ ...prev, [row.id]: rows }));
      setSplitQueries((prev) => ({ ...prev, [row.id]: getSplitQueries(rows, categories) }));
    }
  }

  function addSplitRow(row: ImportPreviewRow) {
    const currentRows = getSplitRowsForRow(row);
    const currentQueries = getSplitQueriesForRow(row);
    setSplitRows((prev) => ({ ...prev, [row.id]: [...currentRows, { ...DEFAULT_SPLIT_ROW }] }));
    setSplitQueries((prev) => ({ ...prev, [row.id]: [...currentQueries, { category_id: '' }] }));
  }

  function removeSplitRow(row: ImportPreviewRow, index: number) {
    const currentRows = getSplitRowsForRow(row);
    const currentQueries = getSplitQueriesForRow(row);
    if (currentRows.length <= 2) return;
    setSplitRows((prev) => ({ ...prev, [row.id]: currentRows.filter((_, currentIndex) => currentIndex !== index) }));
    setSplitQueries((prev) => ({ ...prev, [row.id]: currentQueries.filter((_, currentIndex) => currentIndex !== index) }));
  }

  function submitRow(row: ImportPreviewRow, action: 'confirm' | 'exclude' | 'restore') {
    if (action === 'exclude' || action === 'restore') {
      rowMutation.mutate({ rowId: row.id, payload: { action } });
      return;
    }

    rowMutation.mutate({
      rowId: row.id,
      payload: {
        ...buildRowUpdatePayload(row, getRowForm(row), splitExpanded, splitRows),
        action: 'confirm',
      },
    });
  }

  function categoryItemsByKind(kind?: CategoryKind): SearchSelectItem[] {
    return categories
      .filter((category) => (kind ? category.kind === kind : true))
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
      .map((category) => ({
        value: String(category.id),
        label: category.name,
        searchText: `${category.name} ${priorityLabels[category.priority]} ${transactionTypeLabels[category.kind]}`,
        badge: `${transactionTypeLabels[category.kind]} · ${priorityLabels[category.priority]}`,
      }));
  }

  const extractedStatementIdentifier = uploadResult?.contract_number
    ? {
        label: 'Номер договора',
        value: uploadResult.contract_number,
        reason: uploadResult.contract_match_reason,
        confidence: uploadResult.contract_match_confidence,
      }
    : uploadResult?.statement_account_number
      ? {
          label: 'Лицевой счёт',
          value: uploadResult.statement_account_number,
          reason: uploadResult.statement_account_match_reason,
          confidence: uploadResult.statement_account_match_confidence,
        }
      : null;

  if (accountsQuery.isLoading || categoriesQuery.isLoading || counterpartiesQuery.isLoading) {
    return <LoadingState title="Подготавливаем импорт" description="Загружаем счета и категории для корректного сопоставления строк." />;
  }

  if (accountsQuery.isError || categoriesQuery.isError || counterpartiesQuery.isError) {
    return <ErrorState title="Не удалось загрузить справочники" description="Проверь доступность API и повтори попытку." />;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statCard('Источник', uploadResult ? 1 : 0, uploadResult ? 'success' : 'default')}
        {statCard('Preview готов', previewResult ? 1 : 0, previewResult ? 'success' : 'default')}
        {statCard('Готово к импорту', previewSummary?.ready_rows ?? 0, 'success')}
        {statCard('Требуют внимания', previewSummary?.warning_rows ?? 0, 'warning')}
      </div>

      <div className={cn('grid gap-6 lg:items-start', sidebar ? 'lg:grid-cols-[minmax(0,1fr)_420px]' : 'grid-cols-1')}>
        <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
          <div>
            <form className="space-y-4" onSubmit={(event) => event.preventDefault()}>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">1. Загрузка источника</h3>
                <p className="mt-1 text-sm text-slate-500">Загрузи CSV, XLSX или PDF. После распознавания все строки редактируются сразу внутри блока транзакции.</p>
              </div>
              <div className="grid gap-4 md:grid-cols-[1fr_160px]">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Файл</label>
                  <Input type="file" accept=".csv,.xlsx,.xls,.pdf" onChange={handleFileChange} />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Разделитель CSV</label>
                  <Input value={uploadForm.delimiter} onChange={(event) => setUploadForm((prev) => ({ ...prev, delimiter: event.target.value }))} />
                </div>
              </div>
              <SearchSelect
                id="import-account"
                label="Счёт импорта"
                placeholder="Выбери счёт, куда импортируется выписка"
                widthClassName="w-full"
                query={rowQueries[0]?.import_account ?? importAccount?.name ?? ''}
                setQuery={(value) => {
                  setRowQueries((prev) => ({ ...prev, 0: { account_id: '', target_account_id: '', credit_account_id: '', category_id: '', counterparty_id: '', main_type: '', investment_direction: '', debt_direction: '', credit_operation_kind: '', import_account: value } }));
                }}
                items={importAccountItems}
                selectedValue={mappingForm.account_id}
                onSelect={(item) => {
                  const nextMapping = { ...mappingForm, account_id: item.value, currency: accounts.find((account) => String(account.id) === item.value)?.currency ?? mappingForm.currency };
                  setRowQueries((prev) => ({ ...prev, 0: { account_id: '', target_account_id: '', credit_account_id: '', category_id: '', counterparty_id: '', main_type: '', investment_direction: '', debt_direction: '', credit_operation_kind: '', import_account: item.label } }));
                  if (uploadResult) {
                    rebuildPreview(nextMapping);
                  } else {
                    setMappingForm(nextMapping);
                  }
                }}
                showAllOnFocus
                createAction={{
                  visible: Boolean((rowQueries[0]?.import_account ?? '').trim()) && !importAccountItems.some((item) => normalize(item.label) === normalize(rowQueries[0]?.import_account ?? '')),
                  label: 'Создать счёт',
                  onClick: () => {
                    setPendingFieldTarget({ rowId: null, field: 'import_account' });
                    setPendingAccountDraft({ name: (rowQueries[0]?.import_account ?? '').trim(), currency: mappingForm.currency || 'RUB', balance: 0, is_active: true, account_type: 'regular', is_credit: false });
                    setAccountDialogOpen(true);
                  },
                }}
              />
              <div className="flex flex-wrap items-start gap-3">
                <Button
                  type="button"
                  disabled={!selectedFile || uploadMutation.isPending || previewMutation.isPending}
                  onClick={() => handleUpload({ goToPreview: true })}
                >
                  <FileUp className="size-4" />
                  {uploadMutation.isPending ? 'Загрузка...' : 'Загрузить и проверить'}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!selectedFile || uploadMutation.isPending}
                  onClick={() => handleUpload({ goToPreview: false })}
                >
                  Добавить в очередь
                </Button>
                <Button type="button" variant="secondary" onClick={resetAll}>Сбросить</Button>
                <div className="min-w-[220px] flex-1 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                    Идентификатор из выписки
                  </p>
                  <p className="mt-1 text-xs font-medium text-slate-500">
                    {uploadResult?.source_type === 'pdf'
                      ? extractedStatementIdentifier?.label ?? 'Не найден'
                      : 'Появится после загрузки PDF-выписки'}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-slate-900">
                    {uploadResult?.source_type === 'pdf'
                      ? extractedStatementIdentifier?.value ?? 'Не найден'
                      : 'Появится после загрузки PDF-выписки'}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {uploadResult?.source_type === 'pdf'
                      ? 'Система показывает, какой постоянный идентификатор был извлечён из этой выписки.'
                      : 'После загрузки файла здесь появится то, что система смогла распознать в шапке PDF.'}
                  </p>
                  {uploadResult?.source_type === 'pdf' && extractedStatementIdentifier?.reason ? (
                    <p className="mt-1 text-xs text-slate-400">
                      {extractedStatementIdentifier.reason}
                      {typeof extractedStatementIdentifier.confidence === 'number'
                        ? ` · ${Math.round(extractedStatementIdentifier.confidence * 100)}%`
                        : ''}
                    </p>
                  ) : null}
                </div>
              </div>
            </form>
          </div>
        </Card>

        {sidebar ? (
          <div className="space-y-3 lg:max-h-[430px] lg:overflow-y-auto lg:overscroll-contain lg:pr-2">
            {sidebar}
          </div>
        ) : null}
      </div>

      {previewResult && !mappingForm.account_id ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          ⚠️ Счёт не выбран — выбери счёт в блоке «Загрузка источника» выше, и preview пересчитается автоматически.
        </div>
      ) : null}

      {previewResult && mappingForm.account_id && uploadResult?.suggested_account_id === null ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          ⚠️ Счёт не был определён автоматически из выписки. Убедись, что выбран правильный счёт выше — при необходимости смени его, и preview пересчитается.
        </div>
      ) : null}

      {previewResult ? (
        <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">2. Импорт перед коммитом</h3>
              <p className="mt-1 text-sm text-slate-500">Исправляй тип, счёт, категорию и разбивку прямо внутри каждой строки. Блок сопоставления убран из сценария.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button onClick={() => {
                commitMutation.mutate({ sessionId: previewResult.session_id, importReadyOnly: true });
              }} disabled={commitMutation.isPending}>
                <CheckCircle2 className="size-4" />
                Импортировать готовые
              </Button>
            </div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-5">
            {statCard('Всего строк', previewSummary?.total_rows ?? 0, 'default', () => setStatusFilter(null), statusFilter === null)}
            {statCard('Готово', previewSummary?.ready_rows ?? 0, 'success', () => setStatusFilter(s => s === 'ready' ? null : 'ready'), statusFilter === 'ready')}
            {statCard('Требуют внимания', previewSummary?.warning_rows ?? 0, 'warning', () => setStatusFilter(s => s === 'warning' ? null : 'warning'), statusFilter === 'warning')}
            {statCard('Ошибки', previewSummary?.error_rows ?? 0, 'danger', () => setStatusFilter(s => s === 'error' ? null : 'error'), statusFilter === 'error')}
            {statCard('Исключено / пропущено', previewSummary?.skipped_rows ?? 0, 'default', () => setStatusFilter(s => s === 'skipped' ? null : 'skipped'), statusFilter === 'skipped')}
          </div>

          <div className="mt-6 space-y-4">
            {previewRows.filter((row) => {
              if (!statusFilter) return true;
              const effectiveStatus = isRowDirty(row) && row.status === 'ready' ? 'warning' : row.status;
              if (statusFilter === 'skipped') return effectiveStatus === 'skipped' || effectiveStatus === 'duplicate';
              return effectiveStatus === statusFilter;
            }).map((row) => {
              const normalized = row.normalized_data;
              const form = getRowForm(row);
              const queries = getRowQuery(row);
              const splitOpen = Boolean(splitExpanded[row.id]);
              const currentSplitRows = getSplitRowsForRow(row);
              const currentSplitQueries = getSplitQueriesForRow(row);
              const categoryKind: CategoryKind = form.type === 'income' ? 'income' : 'expense';
              const categoryItems = form.main_type === 'refund' ? categoryItemsByKind() : categoryItemsByKind(categoryKind);

              return (
                <div key={row.id} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 shadow-soft">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <ImportStatusBadge status={isRowDirty(row) && row.status === 'ready' ? 'warning' : row.status} />
                        {normalized.type === 'income' ? (
                          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">Доход</span>
                        ) : normalized.type === 'expense' ? (
                          <span className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700">Расход</span>
                        ) : null}
                      </div>
                      <div className="text-sm text-slate-700">
                        <div className="font-medium text-slate-950 break-words [overflow-wrap:anywhere]">{String(normalized.description ?? 'Без описания')}</div>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2">
                      {row.status !== 'skipped' ? (
                        <>
                          {isRegularSplitApplicable(form) ? (
                            <Button type="button" variant="secondary" onClick={() => toggleSplit(row)}>
                              <Split className="size-4" />
                              Разбить по категориям
                            </Button>
                          ) : null}
                          <Button type="button" onClick={() => submitRow(row, 'confirm')} disabled={rowMutation.isPending}>
                            Подтвердить
                          </Button>
                          <Button type="button" variant="ghost" onClick={() => submitRow(row, 'exclude')} disabled={rowMutation.isPending}>
                            <ShieldOff className="size-4" />
                            Исключить
                          </Button>
                        </>
                      ) : (
                        <Button type="button" variant="secondary" onClick={() => submitRow(row, 'restore')} disabled={rowMutation.isPending}>
                          <Undo2 className="size-4" />
                          Вернуть в импорт
                        </Button>
                      )}
                    </div>
                  </div>

                  {row.status === 'duplicate' && normalized.transfer_pair_hint != null ? (
                    (() => {
                      const hint = normalized.transfer_pair_hint as { date?: string; source_account_name?: string | null };
                      const hintDate = hint.date
                        ? new Date(hint.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
                        : null;
                      return (
                        <div className="mt-3 flex items-start gap-3 rounded-xl border border-violet-200 bg-violet-50 px-4 py-3">
                          <Info className="mt-0.5 size-4 shrink-0 text-violet-500" />
                          <p className="flex-1 text-sm text-violet-800">
                            Это поступление уже учтено как перевод
                            {hintDate ? <> от <span className="font-medium">{hintDate}</span></> : null}
                            {hint.source_account_name ? <> со счёта <span className="font-medium">{hint.source_account_name}</span></> : null}
                          </p>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="shrink-0 text-violet-700 hover:bg-violet-100 hover:text-violet-900"
                            onClick={() => submitRow(row, 'exclude')}
                            disabled={rowMutation.isPending}
                          >
                            <ShieldOff className="size-3.5" />
                            Исключить
                          </Button>
                        </div>
                      );
                    })()
                  ) : null}

                  {row.status !== 'skipped' ? (
                    <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-2 xl:grid-cols-4">
                      <SearchSelect
                        id={`row-account-${row.id}`}
                        label={form.main_type === 'transfer' ? 'Счёт (из выписки)' : 'Счёт'}
                        placeholder="Начни вводить..."
                        widthClassName="w-full"
                        query={queries.account_id}
                        setQuery={(value) => updateRowQuery(row.id, { account_id: value })}
                        items={accountItems}
                        selectedValue={form.account_id}
                        onSelect={(item) => {
                          updateRowForm(row.id, { account_id: item.value });
                          updateRowQuery(row.id, { account_id: item.label });
                        }}
                        showAllOnFocus
                        createAction={{
                          visible: Boolean(queries.account_id.trim()) && !accountItems.some((item) => normalize(item.label) === normalize(queries.account_id)),
                          label: 'Создать счёт',
                          onClick: () => {
                            setPendingFieldTarget({ rowId: row.id, field: 'account_id' });
                            setPendingAccountDraft({ name: queries.account_id.trim(), currency: form.currency, balance: 0, is_active: true, account_type: 'regular', is_credit: false });
                            setAccountDialogOpen(true);
                          },
                        }}
                      />

                      <SearchSelect
                        id={`row-main-type-${row.id}`}
                        label="Тип транзакции"
                        placeholder="Начни вводить..."
                        widthClassName="w-full"
                        query={queries.main_type}
                        setQuery={(value) => updateRowQuery(row.id, { main_type: value })}
                        items={mainTypeItems}
                        selectedValue={form.main_type}
                        onSelect={(item) => {
                          const nextMainType = item.value as MainOperationType;
                          const patch: Partial<RowEditState> = { main_type: nextMainType };
                          if (nextMainType === 'transfer') {
                            patch.target_account_id = form.target_account_id || mappingForm.account_id;
                            patch.credit_account_id = '';
                            patch.credit_principal_amount = '';
                            patch.credit_interest_amount = '';
                            patch.credit_operation_kind = '';
                            patch.category_id = '';
                            patch.type = normalized.type === 'income' ? 'income' : 'expense';
                          }
                          if (nextMainType === 'regular') {
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                            patch.counterparty_id = '';
                            patch.credit_account_id = '';
                            patch.credit_principal_amount = '';
                            patch.credit_interest_amount = '';
                            patch.credit_operation_kind = '';
                          }
                          if (nextMainType === 'refund') {
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                            patch.counterparty_id = '';
                            patch.credit_account_id = '';
                            patch.credit_principal_amount = '';
                            patch.credit_interest_amount = '';
                            patch.credit_operation_kind = '';
                            patch.type = 'income';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'investment') {
                            patch.investment_direction = form.investment_direction || 'buy';
                            patch.debt_direction = '';
                            patch.counterparty_id = '';
                            patch.credit_account_id = '';
                            patch.credit_principal_amount = '';
                            patch.credit_interest_amount = '';
                            patch.credit_operation_kind = '';
                            patch.category_id = '';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'debt') {
                            patch.debt_direction = form.debt_direction || 'lent';
                            patch.counterparty_id = form.counterparty_id || '';
                            patch.investment_direction = '';
                            patch.credit_account_id = '';
                            patch.credit_principal_amount = '';
                            patch.credit_interest_amount = '';
                            patch.credit_operation_kind = '';
                            patch.category_id = '';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'credit_operation') {
                            const nextKind = form.credit_operation_kind || 'payment';
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                            patch.counterparty_id = '';
                            patch.category_id = '';
                            patch.credit_operation_kind = nextKind;
                            patch.type = nextKind === 'disbursement' ? 'income' : 'expense';
                            patch.target_account_id = '';
                            if (nextKind === 'payment') {
                              patch.credit_account_id = form.credit_account_id || form.target_account_id || '';
                            } else {
                              patch.credit_account_id = '';
                              patch.credit_principal_amount = '';
                              patch.credit_interest_amount = '';
                            }
                          }
                          updateRowForm(row.id, patch);
                          updateRowQuery(row.id, { main_type: item.label });
                        }}
                        showAllOnFocus
                      />

                      {form.main_type === 'investment' ? (
                        <SearchSelect
                          id={`row-investment-direction-${row.id}`}
                          label="Действие"
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={queries.investment_direction}
                          setQuery={(value) => updateRowQuery(row.id, { investment_direction: value })}
                          items={investmentDirectionItems}
                          selectedValue={form.investment_direction}
                          onSelect={(item) => {
                            updateRowForm(row.id, { investment_direction: item.value as InvestmentDirection });
                            updateRowQuery(row.id, { investment_direction: item.label });
                          }}
                          showAllOnFocus
                        />
                      ) : form.main_type === 'debt' ? (
                        <>
                          <SearchSelect
                            id={`row-debt-direction-${row.id}`}
                            label="Направление долга"
                            placeholder="Начни вводить..."
                            widthClassName="w-full"
                            query={queries.debt_direction}
                            setQuery={(value) => updateRowQuery(row.id, { debt_direction: value })}
                            items={debtDirectionItems}
                            selectedValue={form.debt_direction}
                            onSelect={(item) => {
                              updateRowForm(row.id, { debt_direction: item.value as DebtDirection });
                              updateRowQuery(row.id, { debt_direction: item.label });
                            }}
                            showAllOnFocus
                          />

                          <SearchSelect
                            id={`row-counterparty-${row.id}`}
                            label="Контрагент"
                            placeholder="Начни вводить..."
                            widthClassName="w-full"
                            query={queries.counterparty_id}
                            setQuery={(value) => updateRowQuery(row.id, { counterparty_id: value })}
                            items={counterpartyItems}
                            selectedValue={form.counterparty_id}
                            onSelect={(item) => {
                              updateRowForm(row.id, { counterparty_id: item.value });
                              updateRowQuery(row.id, { counterparty_id: item.label });
                            }}
                            showAllOnFocus
                            onDeleteItem={(item) => deleteCounterpartyMutation.mutate(Number(item.value))}
                            deleteItemLabel="Удалить контрагента"
                            createAction={{
                              visible: Boolean((queries.counterparty_id ?? '').trim()) && !counterpartyItems.some((item) => normalize(item.label) === normalize(queries.counterparty_id ?? '')),
                              label: 'Создать контрагента',
                              onClick: () => {
                                setPendingFieldTarget({ rowId: row.id, field: 'counterparty_id' });
                                setPendingCounterpartyDraft({
                                  name: (queries.counterparty_id ?? '').trim(),
                                  opening_balance: 0,
                                  opening_balance_kind: form.debt_direction === 'borrowed' || form.debt_direction === 'repaid' ? 'payable' : 'receivable',
                                });
                                setCounterpartyDialogOpen(true);
                              },
                            }}
                          />
                        </>
                      ) : form.main_type === 'transfer' ? (
                        <SearchSelect
                          id={`row-target-account-${row.id}`}
                          label={normalized.type === 'income' ? 'Счёт списания' : 'Счёт поступления'}
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={queries.target_account_id}
                          setQuery={(value) => updateRowQuery(row.id, { target_account_id: value })}
                          items={accountItems.filter((item) => item.value !== form.account_id)}
                          selectedValue={form.target_account_id}
                          onSelect={(item) => {
                            updateRowForm(row.id, { target_account_id: item.value });
                            updateRowQuery(row.id, { target_account_id: item.label });
                          }}
                          showAllOnFocus
                          createAction={{
                            visible: Boolean(queries.target_account_id.trim()) && !accountItems.some((item) => normalize(item.label) === normalize(queries.target_account_id)),
                            label: 'Создать счёт',
                            onClick: () => {
                              setPendingFieldTarget({ rowId: row.id, field: 'target_account_id' });
                              setPendingAccountDraft({ name: queries.target_account_id.trim(), currency: form.currency, balance: 0, is_active: true, account_type: 'regular', is_credit: false });
                              setAccountDialogOpen(true);
                            },
                          }}
                        />
                      ) : form.main_type === 'credit_operation' ? (
                        <>
                          <SearchSelect
                            id={`row-credit-kind-${row.id}`}
                            label="Вид операции"
                            placeholder="Выбери вид операции"
                            widthClassName="w-full"
                            query={queries.credit_operation_kind}
                            setQuery={(value) => updateRowQuery(row.id, { credit_operation_kind: value })}
                            items={creditOperationKindItems}
                            selectedValue={form.credit_operation_kind}
                            onSelect={(item) => {
                              const nextKind = item.value as CreditOperationKind;
                              updateRowForm(row.id, {
                                credit_operation_kind: nextKind,
                                type: nextKind === 'disbursement' ? 'income' : 'expense',
                                category_id: '',
                                target_account_id: '',
                                credit_account_id: nextKind === 'payment' || nextKind === 'early_repayment' ? form.credit_account_id : '',
                                credit_principal_amount: nextKind === 'payment' || nextKind === 'early_repayment' ? form.credit_principal_amount : '',
                                credit_interest_amount: nextKind === 'payment' ? form.credit_interest_amount : nextKind === 'early_repayment' ? '0' : '',
                              });
                              updateRowQuery(row.id, { credit_operation_kind: item.label });
                            }}
                            showAllOnFocus
                          />
                          {form.credit_operation_kind === 'payment' || form.credit_operation_kind === 'early_repayment' ? (
                            <SearchSelect
                              id={`row-credit-account-${row.id}`}
                              label="Кредит"
                              placeholder="Выбери кредитный счёт"
                              widthClassName="w-full"
                              query={queries.credit_account_id}
                              setQuery={(value) => updateRowQuery(row.id, { credit_account_id: value })}
                              items={creditAccountItems.filter((item) => item.value !== form.account_id)}
                              selectedValue={form.credit_account_id}
                              onSelect={(item) => {
                                updateRowForm(row.id, { credit_account_id: item.value });
                                updateRowQuery(row.id, { credit_account_id: item.label });
                              }}
                              showAllOnFocus
                            />
                          ) : null}
                        </>
                      ) : (
                        <SearchSelect
                          id={`row-category-${row.id}`}
                          label="Категория"
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={queries.category_id}
                          setQuery={(value) => updateRowQuery(row.id, { category_id: value })}
                          items={categoryItems}
                          selectedValue={form.category_id}
                          onSelect={(item) => {
                            updateRowForm(row.id, { category_id: item.value });
                            updateRowQuery(row.id, { category_id: item.label });
                          }}
                          showAllOnFocus
                          createAction={{
                            visible: Boolean(queries.category_id.trim()) && !categoryItems.some((item) => normalize(item.label) === normalize(queries.category_id)),
                            label: 'Создать категорию',
                            onClick: () => {
                              setPendingFieldTarget({ rowId: row.id, field: 'category_id' });
                              setPendingCategoryDraft({ name: queries.category_id.trim(), kind: categoryKind, priority: defaultCategoryPriorityByKind[categoryKind] });
                              setCategoryDialogOpen(true);
                            },
                          }}
                        />
                      )}

                      {form.main_type === 'credit_operation' && (form.credit_operation_kind === 'payment' || form.credit_operation_kind === 'early_repayment') ? (
                        <>
                          <div>
                            <label className="mb-2 block text-sm font-medium text-slate-700">Основной долг</label>
                            <Input value={form.credit_principal_amount} onChange={(event) => updateRowForm(row.id, { credit_principal_amount: event.target.value })} />
                          </div>
                          {form.credit_operation_kind === 'payment' ? (
                            <div>
                              <label className="mb-2 block text-sm font-medium text-slate-700">Проценты</label>
                              <Input value={form.credit_interest_amount} onChange={(event) => updateRowForm(row.id, { credit_interest_amount: event.target.value })} />
                            </div>
                          ) : null}
                        </>
                      ) : null}

                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700">Сумма</label>
                        <Input value={form.amount} onChange={(event) => updateRowForm(row.id, { amount: event.target.value })} />
                      </div>

                      <div className="md:col-span-2 xl:col-span-2">
                        <label className="mb-2 block text-sm font-medium text-slate-700">Описание</label>
                        <DescriptionAutocomplete
                          value={form.description}
                          onChange={(value) => updateRowForm(row.id, { description: value })}
                          rowNormalizedDescription={String(row.normalized_data.normalized_description ?? '')}
                          rules={categoryRules}
                        />
                      </div>

                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700">Дата</label>
                        <Input type="date" value={form.transaction_date} onChange={(event) => updateRowForm(row.id, { transaction_date: event.target.value })} />
                      </div>

                      {splitOpen ? (
                        <div className="md:col-span-2 xl:col-span-4 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-slate-900">Разбивка по категориям</div>
                              <div className="text-xs text-slate-500">Работает только для обычных транзакций. Сумма частей должна совпадать с общей суммой.</div>
                            </div>
                            <Button type="button" variant="secondary" onClick={() => addSplitRow(row)}>
                              <Plus className="size-4" />
                              Добавить часть
                            </Button>
                          </div>
                          {currentSplitRows.map((splitItem, index) => {
                            const splitCategoryItems = categoryItemsByKind('expense');
                            const splitQuery = currentSplitQueries[index] ?? { category_id: '' };
                            return (
                              <div key={`${row.id}-${index}`} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-3 md:grid-cols-[1.4fr_0.7fr_1fr_auto]">
                                <SearchSelect
                                  id={`split-category-${row.id}-${index}`}
                                  label="Категория"
                                  placeholder="Начни вводить..."
                                  widthClassName="w-full"
                                  query={splitQuery.category_id}
                                  setQuery={(value) => updateSplitQuery(row.id, index, { category_id: value })}
                                  items={splitCategoryItems}
                                  selectedValue={splitItem.category_id}
                                  onSelect={(item) => {
                                    updateSplitRow(row.id, index, { category_id: item.value });
                                    updateSplitQuery(row.id, index, { category_id: item.label });
                                  }}
                                  showAllOnFocus
                                  createAction={{
                                    visible: Boolean(splitQuery.category_id.trim()) && !splitCategoryItems.some((item) => normalize(item.label) === normalize(splitQuery.category_id)),
                                    label: 'Создать категорию',
                                    onClick: () => {
                                      setPendingFieldTarget({ rowId: row.id, field: 'split_category_id', splitIndex: index });
                                      setPendingCategoryDraft({ name: splitQuery.category_id.trim(), kind: 'expense', priority: defaultCategoryPriorityByKind.expense });
                                      setCategoryDialogOpen(true);
                                    },
                                  }}
                                />
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-slate-700">Сумма</label>
                                  <Input value={splitItem.amount} onChange={(event) => updateSplitRow(row.id, index, { amount: event.target.value })} />
                                </div>
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-slate-700">Описание части</label>
                                  <Input value={splitItem.description} onChange={(event) => updateSplitRow(row.id, index, { description: event.target.value })} placeholder="Можно оставить пустым" />
                                </div>
                                <div className="flex items-end justify-end">
                                  <Button type="button" variant="ghost" onClick={() => removeSplitRow(row, index)} disabled={currentSplitRows.length <= 2}>
                                    <Trash2 className="size-4" />
                                  </Button>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {commitResult ? (
            <div className="mt-6 rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-800">
              Импорт завершён: создано {commitResult.imported_count}, пропущено {commitResult.skipped_count}, дубликатов {commitResult.duplicate_count}, ошибок {commitResult.error_count}.
            </div>
          ) : null}
        </Card>
      ) : (
        <EmptyState title="Preview пока нет" description={previewMutation.isPending ? 'Строим preview...' : 'После загрузки файла preview появится здесь автоматически.'} />
      )}

      <AccountDialog
        open={accountDialogOpen}
        mode="create"
        initialValues={pendingAccountDraft}
        isSubmitting={createAccountMutation.isPending}
        onClose={() => {
          setAccountDialogOpen(false);
          setPendingAccountDraft(null);
          setPendingFieldTarget(null);
        }}
        onSubmit={(values) => createAccountMutation.mutate(values)}
      />

      <CounterpartyDialog
        open={counterpartyDialogOpen}
        draft={pendingCounterpartyDraft}
        isSubmitting={createCounterpartyMutation.isPending}
        onClose={() => {
          setCounterpartyDialogOpen(false);
          setPendingCounterpartyDraft(null);
          setPendingFieldTarget(null);
        }}
        onSubmit={(values) => createCounterpartyMutation.mutate(values)}
      />

      <CategoryDialog
        open={categoryDialogOpen}
        mode="create"
        initialValues={pendingCategoryDraft}
        isSubmitting={createCategoryMutation.isPending}
        onClose={() => {
          setCategoryDialogOpen(false);
          setPendingCategoryDraft(null);
          setPendingFieldTarget(null);
        }}
        onSubmit={(values) => createCategoryMutation.mutate(values)}
      />
    </div>
  );
}

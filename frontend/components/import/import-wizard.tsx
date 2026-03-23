'use client';

import { ChangeEvent, FormEvent, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, FileUp, Plus, ShieldOff, Sparkles, Split, Trash2, Undo2 } from 'lucide-react';
import { toast } from 'sonner';

import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategories, createCategory } from '@/lib/api/categories';
import { commitImport, previewImport, updateImportRow, uploadImportFile } from '@/lib/api/imports';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { ImportStatusBadge } from '@/components/import/import-status-badge';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import type { Account, CreateAccountPayload } from '@/types/account';
import type { Category, CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';
import type {
  ImportCommitResponse,
  ImportDetection,
  ImportMappingPayload,
  ImportPreviewResponse,
  ImportPreviewRow,
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

type MainOperationType = 'regular' | 'investment' | 'debt' | 'refund' | 'transfer' | 'credit_payment';
type InvestmentDirection = '' | 'buy' | 'sell';
type DebtDirection = '' | 'lent' | 'borrowed';

type RowEditState = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  amount: string;
  type: 'income' | 'expense';
  operation_type: string;
  description: string;
  transaction_date: string;
  currency: string;
  main_type: MainOperationType;
  investment_direction: InvestmentDirection;
  debt_direction: DebtDirection;
};

type RowQueries = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  main_type: string;
  investment_direction: string;
  debt_direction: string;
  import_account: string;
};

type SplitRowState = {
  category_id: string;
  amount: string;
  description: string;
};

type SplitRowQueries = {
  category_id: string;
};

type PendingFieldTarget =
  | { rowId: number; field: 'account_id' | 'target_account_id' | 'category_id' }
  | { rowId: number; field: 'split_category_id'; splitIndex: number }
  | { rowId: null; field: 'import_account' };

const defaultUploadForm: UploadFormState = { delimiter: ',' };
const DEFAULT_SPLIT_ROW: SplitRowState = { category_id: '', amount: '', description: '' };

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

function statCard(label: string, value: number, tone: 'default' | 'success' | 'warning' | 'danger' = 'default') {
  const toneClass =
    tone === 'success' ? 'border-emerald-100' : tone === 'warning' ? 'border-amber-100' : tone === 'danger' ? 'border-rose-100' : 'border-slate-200';

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
): { mainType: MainOperationType; investmentDirection: InvestmentDirection; debtDirection: DebtDirection } {
  if (operationType === 'transfer') return { mainType: 'transfer', investmentDirection: '', debtDirection: '' };
  if (operationType === 'refund') return { mainType: 'refund', investmentDirection: '', debtDirection: '' };
  if (operationType === 'investment_buy') return { mainType: 'investment', investmentDirection: 'buy', debtDirection: '' };
  if (operationType === 'investment_sell') return { mainType: 'investment', investmentDirection: 'sell', debtDirection: '' };
  if (operationType === 'debt') return { mainType: 'debt', investmentDirection: '', debtDirection: txType === 'income' ? 'borrowed' : 'lent' };
  if (operationType === 'credit_payment' || operationType === 'credit_disbursement') {
    return { mainType: 'credit_payment', investmentDirection: '', debtDirection: '' };
  }
  return { mainType: 'regular', investmentDirection: '', debtDirection: '' };
}

function resolveOperationFields(form: RowEditState): Pick<RowEditState, 'operation_type' | 'type'> {
  if (form.main_type === 'transfer') return { operation_type: 'transfer', type: 'expense' };
  if (form.main_type === 'refund') return { operation_type: 'refund', type: 'income' };
  if (form.main_type === 'investment') {
    return { operation_type: form.investment_direction === 'sell' ? 'investment_sell' : 'investment_buy', type: form.investment_direction === 'sell' ? 'income' : 'expense' };
  }
  if (form.main_type === 'debt') {
    return { operation_type: 'debt', type: form.debt_direction === 'borrowed' ? 'income' : 'expense' };
  }
  if (form.main_type === 'credit_payment') return { operation_type: 'credit_payment', type: 'expense' };
  return { operation_type: 'regular', type: form.type };
}

function getDirectionLabel(value: unknown) {
  if (value === 'income') return transactionTypeLabels.income;
  if (value === 'expense') return transactionTypeLabels.expense;
  return '—';
}

function getOperationLabel(value: unknown) {
  if (typeof value !== 'string') return '—';
  return operationTypeLabels[value as keyof typeof operationTypeLabels] ?? value;
}

function findAccountName(accounts: Account[], value: unknown) {
  const accountId = Number(value ?? 0);
  if (!accountId) return null;
  return accounts.find((item) => item.id === accountId)?.name ?? null;
}

function findCategoryName(categories: Category[], value: unknown) {
  const categoryId = Number(value ?? 0);
  if (!categoryId) return null;
  return categories.find((item) => item.id === categoryId)?.name ?? null;
}

function getMainTypeLabel(value: MainOperationType) {
  if (value === 'regular') return 'Обычный';
  if (value === 'investment') return 'Инвестиционный';
  if (value === 'debt') return 'Долг';
  if (value === 'refund') return 'Возврат';
  if (value === 'transfer') return 'Перевод';
  return 'Тело кредита';
}

function getRowEditState(row: ImportPreviewRow): RowEditState {
  const rawType = (String(row.normalized_data.type ?? 'expense') as 'income' | 'expense') ?? 'expense';
  const operationType = String(row.normalized_data.operation_type ?? 'regular');
  const ui = mapOperationToUi(operationType, rawType);
  return {
    account_id: row.normalized_data.account_id ? String(row.normalized_data.account_id) : '',
    target_account_id: row.normalized_data.target_account_id ? String(row.normalized_data.target_account_id) : '',
    category_id: row.normalized_data.category_id ? String(row.normalized_data.category_id) : '',
    amount: String(row.normalized_data.amount ?? ''),
    type: rawType,
    operation_type: operationType,
    description: String(row.normalized_data.description ?? ''),
    transaction_date: String(row.normalized_data.transaction_date ?? row.normalized_data.date ?? '').slice(0, 10),
    currency: String(row.normalized_data.currency ?? 'RUB'),
    main_type: ui.mainType,
    investment_direction: ui.investmentDirection,
    debt_direction: ui.debtDirection,
  };
}

function getInitialQueries(row: ImportPreviewRow, accounts: Account[], categories: Category[], importAccountName: string): RowQueries {
  const state = getRowEditState(row);
  return {
    account_id: accounts.find((item) => String(item.id) === state.account_id)?.name ?? '',
    target_account_id: accounts.find((item) => String(item.id) === state.target_account_id)?.name ?? '',
    category_id: categories.find((item) => String(item.id) === state.category_id)?.name ?? '',
    main_type: getMainTypeLabel(state.main_type),
    investment_direction: state.investment_direction === 'sell' ? 'Продажа' : state.investment_direction === 'buy' ? 'Покупка' : '',
    debt_direction: state.debt_direction === 'borrowed' ? 'Мне заняли' : state.debt_direction === 'lent' ? 'Занял' : '',
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

export function ImportWizard() {
  const queryClient = useQueryClient();
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'import-preview'], queryFn: () => getCategories() });

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
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
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);
  const [pendingFieldTarget, setPendingFieldTarget] = useState<PendingFieldTarget | null>(null);

  const accounts = accountsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const previewRows = previewResult?.rows ?? [];

  const importAccount = useMemo(
    () => accounts.find((account) => String(account.id) === mappingForm.account_id) ?? null,
    [accounts, mappingForm.account_id],
  );

  const accountItems = useMemo<SearchSelectItem[]>(() => accounts.map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}`, badge: account.currency })), [accounts]);
  const mainTypeItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'regular', label: 'Обычный', searchText: 'обычный обычная regular' },
    { value: 'investment', label: 'Инвестиционный', searchText: 'инвестиционный инвестиции investment' },
    { value: 'debt', label: 'Долг', searchText: 'долг заем занял мне заняли debt' },
    { value: 'refund', label: 'Возврат', searchText: 'возврат refund' },
    { value: 'transfer', label: 'Перевод', searchText: 'перевод transfer между счетами' },
    { value: 'credit_payment', label: 'Тело кредита', searchText: 'тело кредита credit payment' },
  ], []);
  const investmentDirectionItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'buy', label: 'Покупка', searchText: 'покупка buy' },
    { value: 'sell', label: 'Продажа', searchText: 'продажа sell' },
  ], []);
  const debtDirectionItems = useMemo<SearchSelectItem[]>(() => [
    { value: 'lent', label: 'Занял', searchText: 'занял выдал дал в долг расход' },
    { value: 'borrowed', label: 'Мне заняли', searchText: 'мне заняли взял в долг доход' },
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
    onSuccess: (data) => {
      const nextMapping = buildMappingState(data.detection, accounts, mappingForm.account_id);
      setUploadResult(data);
      setPreviewResult(null);
      setCommitResult(null);
      setMappingForm(nextMapping);
      toast.success('Источник загружен и распознан');
      if (!nextMapping.account_id) {
        toast.error('Сначала создай или выбери счёт для импорта');
        return;
      }
      previewMutation.mutate({ sessionId: data.session_id, payload: toPreviewPayload(nextMapping) });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось загрузить источник'),
  });

  const commitMutation = useMutation({
    mutationFn: ({ sessionId, importReadyOnly }: { sessionId: number; importReadyOnly: boolean }) => commitImport(sessionId, importReadyOnly),
    onSuccess: (data) => {
      setCommitResult(data);
      toast.success('Импорт завершён');
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось завершить импорт'),
  });

  const rowMutation = useMutation({
    mutationFn: ({ rowId, payload }: { rowId: number; payload: Parameters<typeof updateImportRow>[1] }) => updateImportRow(rowId, payload),
    onSuccess: (data) => {
      setPreviewResult((prev) => prev ? ({ ...prev, summary: data.summary, rows: prev.rows.map((row) => row.id === data.row.id ? data.row : row) }) : prev);
      setRowForms((prev) => ({ ...prev, [data.row.id]: getRowEditState(data.row) }));
      setRowQueries((prev) => ({
        ...prev,
        [data.row.id]: getInitialQueries(data.row, accounts, categories, importAccount?.name ?? ''),
      }));
      if (Array.isArray(data.row.normalized_data.split_items) && data.row.normalized_data.split_items.length > 0) {
        const nextRows = getSplitState(data.row);
        setSplitRows((prev) => ({ ...prev, [data.row.id]: nextRows }));
        setSplitQueries((prev) => ({ ...prev, [data.row.id]: getSplitQueries(nextRows, categories) }));
        setSplitExpanded((prev) => ({ ...prev, [data.row.id]: true }));
      }
      toast.success('Строка обновлена');
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
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!)), account_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, importAccount?.name ?? '')), account_id: created.name } }));
      }
      if (pendingFieldTarget && pendingFieldTarget.field === 'target_account_id') {
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!)), target_account_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, importAccount?.name ?? '')), target_account_id: created.name } }));
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
        setRowForms((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!)), category_id: String(created.id) } }));
        setRowQueries((prev) => ({ ...prev, [pendingFieldTarget.rowId]: { ...(prev[pendingFieldTarget.rowId] ?? getInitialQueries(previewRows.find((item) => item.id === pendingFieldTarget.rowId)!, accounts, categories, importAccount?.name ?? '')), category_id: created.name } }));
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

  function resetAll() {
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

  function handleUploadSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      toast.error('Выбери CSV, XLSX или PDF');
      return;
    }
    if (!mappingForm.account_id) {
      toast.error('Выбери счёт, на который импортируется выписка');
      return;
    }
    uploadMutation.mutate({ file: selectedFile, delimiter: uploadForm.delimiter });
  }

  function rebuildPreview(nextForm: MappingState) {
    if (!uploadResult) return;
    if (!nextForm.account_id) {
      toast.error('Выбери счёт для импорта');
      return;
    }
    setMappingForm(nextForm);
    previewMutation.mutate({ sessionId: uploadResult.session_id, payload: toPreviewPayload(nextForm) });
  }

  function getRowForm(row: ImportPreviewRow) {
    return rowForms[row.id] ?? getRowEditState(row);
  }

  function updateRowForm(rowId: number, patch: Partial<RowEditState>) {
    setRowForms((prev) => ({
      ...prev,
      [rowId]: {
        ...(prev[rowId] ?? getRowEditState(previewRows.find((item) => item.id === rowId)!)),
        ...patch,
      },
    }));
  }

  function getRowQuery(row: ImportPreviewRow) {
    return rowQueries[row.id] ?? getInitialQueries(row, accounts, categories, importAccount?.name ?? '');
  }

  function updateRowQuery(rowId: number, patch: Partial<RowQueries>) {
    const baseRow = previewRows.find((item) => item.id === rowId);
    if (!baseRow) return;
    setRowQueries((prev) => ({
      ...prev,
      [rowId]: {
        ...(prev[rowId] ?? getInitialQueries(baseRow, accounts, categories, importAccount?.name ?? '')),
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

    const form = getRowForm(row);
    const resolved = resolveOperationFields(form);
    const activeSplit = splitExpanded[row.id] && form.main_type === 'regular';
    const splitPayload: ImportSplitItem[] | undefined = activeSplit
      ? getSplitRowsForRow(row).map((item) => ({
          category_id: Number(item.category_id),
          amount: Number(String(item.amount).replace(',', '.')),
          description: item.description || form.description || null,
        }))
      : [];

    rowMutation.mutate({
      rowId: row.id,
      payload: {
        account_id: form.account_id ? Number(form.account_id) : null,
        target_account_id: resolved.operation_type === 'transfer' ? (form.target_account_id ? Number(form.target_account_id) : null) : null,
        category_id: resolved.operation_type === 'regular' || resolved.operation_type === 'refund' ? (splitPayload && splitPayload.length >= 2 ? null : form.category_id ? Number(form.category_id) : null) : null,
        amount: form.amount ? Number(form.amount.replace(',', '.')) : null,
        type: resolved.type,
        operation_type: resolved.operation_type,
        description: form.description,
        transaction_date: form.transaction_date ? new Date(form.transaction_date).toISOString() : null,
        currency: form.currency,
        split_items: splitPayload,
        action: 'confirm',
      },
    });
  }

  function categoryItemsByKind(kind: CategoryKind): SearchSelectItem[] {
    return categories
      .filter((category) => category.kind === kind)
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
      .map((category) => ({
        value: String(category.id),
        label: category.name,
        searchText: `${category.name} ${priorityLabels[category.priority]}`,
        badge: priorityLabels[category.priority],
      }));
  }

  if (accountsQuery.isLoading || categoriesQuery.isLoading) {
    return <LoadingState title="Подготавливаем импорт" description="Загружаем счета и категории для корректного сопоставления строк." />;
  }

  if (accountsQuery.isError || categoriesQuery.isError) {
    return <ErrorState title="Не удалось загрузить справочники" description="Проверь доступность API и повтори попытку." />;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statCard('Источник', uploadResult ? 1 : 0, uploadResult ? 'success' : 'default')}
        {statCard('Preview готов', previewResult ? 1 : 0, previewResult ? 'success' : 'default')}
        {statCard('Готово к импорту', previewResult?.summary.ready_rows ?? 0, 'success')}
        {statCard('Требуют внимания', previewResult?.summary.warning_rows ?? 0, 'warning')}
      </div>

      <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
        <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <form className="space-y-4" onSubmit={handleUploadSubmit}>
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
                setRowQueries((prev) => ({ ...prev, 0: { account_id: '', target_account_id: '', category_id: '', main_type: '', investment_direction: '', debt_direction: '', import_account: value } }));
              }}
              items={accountItems}
              selectedValue={mappingForm.account_id}
              onSelect={(item) => {
                const nextMapping = { ...mappingForm, account_id: item.value, currency: accounts.find((account) => String(account.id) === item.value)?.currency ?? mappingForm.currency };
                setRowQueries((prev) => ({ ...prev, 0: { account_id: '', target_account_id: '', category_id: '', main_type: '', investment_direction: '', debt_direction: '', import_account: item.label } }));
                if (uploadResult) {
                  rebuildPreview(nextMapping);
                } else {
                  setMappingForm(nextMapping);
                }
              }}
              showAllOnFocus
              createAction={{
                visible: Boolean((rowQueries[0]?.import_account ?? '').trim()) && !accountItems.some((item) => normalize(item.label) === normalize(rowQueries[0]?.import_account ?? '')),
                label: 'Создать счёт',
                onClick: () => {
                  setPendingFieldTarget({ rowId: null, field: 'import_account' });
                  setPendingAccountDraft({ name: (rowQueries[0]?.import_account ?? '').trim(), currency: mappingForm.currency || 'RUB', balance: 0, is_active: true, is_credit: false });
                  setAccountDialogOpen(true);
                },
              }}
            />
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={uploadMutation.isPending || previewMutation.isPending}>
                <FileUp className="size-4" />
                {uploadMutation.isPending ? 'Загрузка...' : 'Загрузить файл'}
              </Button>
              <Button type="button" variant="secondary" onClick={resetAll}>Сбросить</Button>
            </div>
          </form>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <Sparkles className="size-4" />
              Автоматическое распознавание
            </div>
            {uploadResult ? (
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                <div><span className="font-medium text-slate-900">Файл:</span> {uploadResult.filename}</div>
                <div><span className="font-medium text-slate-900">Тип:</span> {sourceLabel(uploadResult.source_type)}</div>
                <div><span className="font-medium text-slate-900">Строк:</span> {uploadResult.total_rows}</div>
                <div><span className="font-medium text-slate-900">Счёт импорта:</span> {importAccount?.name ?? '—'}</div>
                <div><span className="font-medium text-slate-900">Уверенность:</span> {Math.round((uploadResult.detection.overall_confidence ?? 0) * 100)}%</div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">После загрузки здесь появится краткая сводка по распознаванию и составу файла.</p>
            )}
          </div>
        </div>
      </Card>

      {previewResult ? (
        <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">2. Импорт перед коммитом</h3>
              <p className="mt-1 text-sm text-slate-500">Исправляй тип, счёт, категорию и разбивку прямо внутри каждой строки. Блок сопоставления убран из сценария.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button onClick={() => commitMutation.mutate({ sessionId: previewResult.session_id, importReadyOnly: true })} disabled={commitMutation.isPending}>
                <CheckCircle2 className="size-4" />
                Импортировать готовые
              </Button>
            </div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-5">
            {statCard('Всего строк', previewResult.summary.total_rows)}
            {statCard('Готово', previewResult.summary.ready_rows, 'success')}
            {statCard('Требуют внимания', previewResult.summary.warning_rows, 'warning')}
            {statCard('Ошибки', previewResult.summary.error_rows, 'danger')}
            {statCard('Исключено / пропущено', previewResult.summary.skipped_rows, 'default')}
          </div>

          <div className="mt-6 space-y-4">
            {previewRows.map((row) => {
              const normalized = row.normalized_data;
              const form = getRowForm(row);
              const queries = getRowQuery(row);
              const splitOpen = Boolean(splitExpanded[row.id]);
              const currentSplitRows = getSplitRowsForRow(row);
              const currentSplitQueries = getSplitQueriesForRow(row);
              const accountName = findAccountName(accounts, normalized.account_id);
              const targetAccountName = findAccountName(accounts, normalized.target_account_id);
              const categoryName = findCategoryName(categories, normalized.category_id);
              const categoryKind: CategoryKind = form.main_type === 'refund' || form.type === 'income' ? 'income' : 'expense';
              const categoryItems = categoryItemsByKind(categoryKind);

              return (
                <div key={row.id} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 shadow-soft">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <ImportStatusBadge status={row.status} />
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-600">Строка {row.row_index}</span>
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-600">{Math.round((row.confidence ?? 0) * 100)}%</span>
                      </div>
                      <div className="text-sm text-slate-700">
                        <div className="font-medium text-slate-950">{String(normalized.description ?? 'Без описания')}</div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-slate-500">
                          <span>Дата: {String(normalized.transaction_date ?? normalized.date ?? '—').slice(0, 10) || '—'}</span>
                          <span>Сумма: {String(normalized.amount ?? '—')} {String(normalized.currency ?? 'RUB')}</span>
                          <span>Направление: {getDirectionLabel(normalized.type)}</span>
                          <span>Тип: {getOperationLabel(normalized.operation_type)}</span>
                          <span>Счёт: {accountName ?? '—'}</span>
                          {(normalized.operation_type === 'transfer' || normalized.target_account_id) ? <span>Счёт поступления: {targetAccountName ?? '—'}</span> : null}
                          {normalized.operation_type !== 'transfer' ? <span>Категория: {categoryName ?? '—'}</span> : null}
                        </div>
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

                  {row.status !== 'skipped' ? (
                    <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-2 xl:grid-cols-4">
                      <SearchSelect
                        id={`row-account-${row.id}`}
                        label={form.main_type === 'transfer' ? 'Счёт отправления' : 'Счёт'}
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
                            setPendingAccountDraft({ name: queries.account_id.trim(), currency: form.currency, balance: 0, is_active: true, is_credit: false });
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
                            patch.category_id = '';
                            patch.type = 'expense';
                          }
                          if (nextMainType === 'regular') {
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                          }
                          if (nextMainType === 'refund') {
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                            patch.type = 'income';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'investment') {
                            patch.investment_direction = form.investment_direction || 'buy';
                            patch.debt_direction = '';
                            patch.category_id = '';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'debt') {
                            patch.debt_direction = form.debt_direction || 'lent';
                            patch.investment_direction = '';
                            patch.category_id = '';
                            patch.target_account_id = '';
                          }
                          if (nextMainType === 'credit_payment') {
                            patch.investment_direction = '';
                            patch.debt_direction = '';
                            patch.category_id = '';
                            patch.target_account_id = '';
                            patch.type = 'expense';
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
                      ) : form.main_type === 'transfer' ? (
                        <SearchSelect
                          id={`row-target-account-${row.id}`}
                          label="Счёт поступления"
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
                              setPendingAccountDraft({ name: queries.target_account_id.trim(), currency: form.currency, balance: 0, is_active: true, is_credit: false });
                              setAccountDialogOpen(true);
                            },
                          }}
                        />
                      ) : form.main_type !== 'credit_payment' ? (
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
                              setPendingCategoryDraft({ name: queries.category_id.trim(), kind: categoryKind, priority: defaultCategoryPriorityByKind[categoryKind], color: null });
                              setCategoryDialogOpen(true);
                            },
                          }}
                        />
                      ) : null}

                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700">Сумма</label>
                        <Input value={form.amount} onChange={(event) => updateRowForm(row.id, { amount: event.target.value })} />
                      </div>

                      <div className="md:col-span-2 xl:col-span-2">
                        <label className="mb-2 block text-sm font-medium text-slate-700">Описание</label>
                        <Input value={form.description} onChange={(event) => updateRowForm(row.id, { description: event.target.value })} />
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
                                      setPendingCategoryDraft({ name: splitQuery.category_id.trim(), kind: 'expense', priority: defaultCategoryPriorityByKind.expense, color: null });
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

'use client';

import { ChangeEvent, FormEvent, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, FileUp, Pencil, RefreshCcw, ShieldOff, Sparkles, Undo2 } from 'lucide-react';
import { toast } from 'sonner';

import { getAccounts, createAccount } from '@/lib/api/accounts';
import { getCategories, createCategory } from '@/lib/api/categories';
import { commitImport, previewImport, updateImportRow, uploadImportFile } from '@/lib/api/imports';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
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
  ImportRowStatus,
  ImportSourceType,
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
  { key: 'account_hint', label: 'Подсказка по счету' },
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
};

type RowQueries = {
  account_id: string;
  target_account_id: string;
  category_id: string;
  operation_type: string;
};

const defaultUploadForm: UploadFormState = { delimiter: ',' };
const defaultMappingState: MappingState = {
  account_id: '',
  currency: 'RUB',
  date_format: '%d.%m.%Y',
  table_name: '',
  field_mapping: {},
  skip_duplicates: true,
};

const operationItems: SearchSelectItem[] = [
  { value: 'regular', label: 'Обычная', searchText: 'обычная regular расход доход' },
  { value: 'transfer', label: 'Перевод', searchText: 'перевод transfer между счетами' },
  { value: 'refund', label: 'Возврат', searchText: 'возврат refund' },
  { value: 'adjustment', label: 'Корректировка', searchText: 'корректировка adjustment' },
  { value: 'credit_payment', label: 'Погашение тела кредита', searchText: 'погашение кредита credit payment' },
];

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

function buildMappingState(detection: ImportDetection, accounts: Account[]): MappingState {
  const firstAccount = accounts[0];
  const suggestedDateFormat = detection.suggested_date_formats[0] ?? '%d.%m.%Y';
  return {
    account_id: firstAccount ? String(firstAccount.id) : '',
    currency: firstAccount?.currency ?? 'RUB',
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

function getDirectionLabel(value: unknown) {
  if (value === 'income') return transactionTypeLabels.income;
  if (value === 'expense') return transactionTypeLabels.expense;
  return '—';
}

function getOperationLabel(value: unknown) {
  if (typeof value !== 'string') return '—';
  if (value === 'credit_payment') return 'Погашение тела кредита';
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

function getRowEditState(row: ImportPreviewRow): RowEditState {
  return {
    account_id: row.normalized_data.account_id ? String(row.normalized_data.account_id) : '',
    target_account_id: row.normalized_data.target_account_id ? String(row.normalized_data.target_account_id) : '',
    category_id: row.normalized_data.category_id ? String(row.normalized_data.category_id) : '',
    amount: String(row.normalized_data.amount ?? ''),
    type: (String(row.normalized_data.type ?? 'expense') as 'income' | 'expense') ?? 'expense',
    operation_type: String(row.normalized_data.operation_type ?? 'regular'),
    description: String(row.normalized_data.description ?? ''),
    transaction_date: String(row.normalized_data.transaction_date ?? row.normalized_data.date ?? '').slice(0, 10),
    currency: String(row.normalized_data.currency ?? 'RUB'),
  };
}

function getInitialQueries(row: ImportPreviewRow, accounts: Account[], categories: Category[]): RowQueries {
  const state = getRowEditState(row);
  return {
    account_id: accounts.find((item) => String(item.id) === state.account_id)?.name ?? '',
    target_account_id: accounts.find((item) => String(item.id) === state.target_account_id)?.name ?? '',
    category_id: categories.find((item) => String(item.id) === state.category_id)?.name ?? '',
    operation_type: getOperationLabel(state.operation_type),
  };
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}


export function ImportWizard() {
  const queryClient = useQueryClient();
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'import-preview'], queryFn: () => getCategories() });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadForm, setUploadForm] = useState<UploadFormState>(defaultUploadForm);
  const [mappingForm, setMappingForm] = useState<MappingState>(defaultMappingState);
  const [uploadResult, setUploadResult] = useState<ImportUploadResponse | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitResponse | null>(null);
  const [editingRowId, setEditingRowId] = useState<number | null>(null);
  const [rowForms, setRowForms] = useState<Record<number, RowEditState>>({});
  const [rowQueries, setRowQueries] = useState<Record<number, RowQueries>>({});
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [pendingAccountDraft, setPendingAccountDraft] = useState<Partial<CreateAccountPayload> | null>(null);
  const [pendingCategoryDraft, setPendingCategoryDraft] = useState<Partial<CreateCategoryPayload> | null>(null);
  const [pendingRowField, setPendingRowField] = useState<{ rowId: number; field: 'account_id' | 'target_account_id' | 'category_id' } | null>(null);

  const accounts = accountsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  const accountItems = useMemo<SearchSelectItem[]>(() => accounts.map((account) => ({ value: String(account.id), label: account.name, searchText: `${account.name} ${account.currency}` })), [accounts]);

  const previewRows = previewResult?.rows ?? [];

  const previewMutation = useMutation({
    mutationFn: ({ sessionId, payload }: { sessionId: number; payload: ImportMappingPayload }) => previewImport(sessionId, payload),
    onSuccess: (data) => {
      setPreviewResult(data);
      setCommitResult(null);
      setEditingRowId(null);
      setRowForms({});
      setRowQueries({});
      toast.success('Черновик импорта обновлён');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось построить preview'),
  });

  const uploadMutation = useMutation({
    mutationFn: uploadImportFile,
    onSuccess: (data) => {
      const nextMapping = buildMappingState(data.detection, accounts);
      setUploadResult(data);
      setPreviewResult(null);
      setCommitResult(null);
      setMappingForm(nextMapping);
      toast.success('Источник загружен и распознан');
      if (!nextMapping.account_id) {
        toast.error('Нет доступного счёта для построения preview');
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
      setEditingRowId(null);
      toast.success('Строка обновлена');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось обновить строку'),
  });

  const createAccountMutation = useMutation({
    mutationFn: createAccount,
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      if (pendingRowField) {
        setRowForms((prev) => ({
          ...prev,
          [pendingRowField.rowId]: { ...(prev[pendingRowField.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingRowField.rowId)!)), [pendingRowField.field]: String(created.id) },
        }));
        setRowQueries((prev) => ({
          ...prev,
          [pendingRowField.rowId]: { ...(prev[pendingRowField.rowId] ?? { account_id: '', target_account_id: '', category_id: '', operation_type: '' }), [pendingRowField.field]: created.name },
        }));
      }
      setPendingRowField(null);
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
      if (pendingRowField) {
        setRowForms((prev) => ({
          ...prev,
          [pendingRowField.rowId]: { ...(prev[pendingRowField.rowId] ?? getRowEditState(previewRows.find((item) => item.id === pendingRowField.rowId)!)), category_id: String(created.id) },
        }));
        setRowQueries((prev) => ({
          ...prev,
          [pendingRowField.rowId]: { ...(prev[pendingRowField.rowId] ?? { account_id: '', target_account_id: '', category_id: '', operation_type: '' }), category_id: created.name },
        }));
      }
      setPendingRowField(null);
      setPendingCategoryDraft(null);
      setCategoryDialogOpen(false);
      toast.success('Категория создана');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать категорию'),
  });

  function resetAll() {
    setSelectedFile(null);
    setUploadForm(defaultUploadForm);
    setMappingForm(defaultMappingState);
    setUploadResult(null);
    setPreviewResult(null);
    setCommitResult(null);
    setEditingRowId(null);
    setRowForms({});
    setRowQueries({});
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

  function startEditing(row: ImportPreviewRow) {
    setEditingRowId(row.id);
    setRowForms((prev) => ({ ...prev, [row.id]: getRowEditState(row) }));
    setRowQueries((prev) => ({ ...prev, [row.id]: getInitialQueries(row, accounts, categories) }));
  }

  function updateRowForm(rowId: number, patch: Partial<RowEditState>) {
    setRowForms((prev) => ({ ...prev, [rowId]: { ...(prev[rowId] ?? getRowEditState(previewRows.find((item) => item.id === rowId)!), ...patch } }));
  }

  function updateRowQuery(rowId: number, patch: Partial<RowQueries>) {
    setRowQueries((prev) => ({ ...prev, [rowId]: { account_id: '', target_account_id: '', category_id: '', operation_type: '', ...(prev[rowId] ?? {}), ...patch } }));
  }

  function getRowForm(row: ImportPreviewRow) {
    return rowForms[row.id] ?? getRowEditState(row);
  }

  function getRowQuery(row: ImportPreviewRow) {
    return rowQueries[row.id] ?? getInitialQueries(row, accounts, categories);
  }

  function submitRow(row: ImportPreviewRow, action: 'confirm' | 'exclude' | 'restore') {
    if (action === 'exclude' || action === 'restore') {
      rowMutation.mutate({ rowId: row.id, payload: { action } });
      return;
    }

    const form = getRowForm(row);
    rowMutation.mutate({
      rowId: row.id,
      payload: {
        account_id: form.account_id ? Number(form.account_id) : null,
        target_account_id: form.operation_type === 'transfer' ? (form.target_account_id ? Number(form.target_account_id) : null) : null,
        category_id: form.operation_type === 'regular' || form.operation_type === 'refund' ? (form.category_id ? Number(form.category_id) : null) : null,
        amount: form.amount ? Number(form.amount.replace(',', '.')) : null,
        type: form.type,
        operation_type: form.operation_type,
        description: form.description,
        transaction_date: form.transaction_date ? new Date(form.transaction_date).toISOString() : null,
        currency: form.currency,
        action: 'confirm',
      },
    });
  }

  const categoryItemsByKind = (kind: CategoryKind): SearchSelectItem[] =>
    categories
      .filter((category) => category.kind === kind)
      .map((category) => ({
        value: String(category.id),
        label: category.name,
        searchText: `${category.name} ${priorityLabels[category.priority]}`,
        badge: priorityLabels[category.priority],
      }));

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
              <p className="mt-1 text-sm text-slate-500">Загрузи CSV, XLSX или PDF. После распознавания все спорные строки редактируются прямо здесь, без отдельной страницы проверки.</p>
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
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={uploadMutation.isPending || previewMutation.isPending}>
                <FileUp className="size-4" />
                {uploadMutation.isPending ? 'Загрузка...' : 'Загрузить файл'}
              </Button>
              <Button type="button" variant="secondary" onClick={resetAll}>
                Сбросить
              </Button>
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
                <div><span className="font-medium text-slate-900">Уверенность:</span> {Math.round((uploadResult.detection.overall_confidence ?? 0) * 100)}%</div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">После загрузки здесь появится краткая сводка по распознаванию и составу файла.</p>
            )}
          </div>
        </div>
      </Card>

      {uploadResult ? (
        <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">2. Настройка сопоставления</h3>
              <p className="mt-1 text-sm text-slate-500">Здесь задаётся счёт выписки и колонка для каждого поля. После изменения preview можно перестроить.</p>
            </div>
            <Button variant="secondary" onClick={() => rebuildPreview(mappingForm)} disabled={previewMutation.isPending}>
              <RefreshCcw className="size-4" />
              {previewMutation.isPending ? 'Обновляем...' : 'Обновить preview'}
            </Button>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-4">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Счёт выписки</label>
              <Select value={mappingForm.account_id} onChange={(event) => setMappingForm((prev) => ({ ...prev, account_id: event.target.value, currency: accounts.find((item) => String(item.id) === event.target.value)?.currency ?? prev.currency }))}>
                {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
              </Select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Валюта</label>
              <Input value={mappingForm.currency} onChange={(event) => setMappingForm((prev) => ({ ...prev, currency: event.target.value.toUpperCase() }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Формат даты</label>
              <Input value={mappingForm.date_format} onChange={(event) => setMappingForm((prev) => ({ ...prev, date_format: event.target.value }))} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Таблица</label>
              <Select value={mappingForm.table_name} onChange={(event) => setMappingForm((prev) => ({ ...prev, table_name: event.target.value }))}>
                {(uploadResult.detection.available_tables ?? []).map((table) => <option key={table.name} value={table.name}>{table.name}</option>)}
              </Select>
            </div>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {MAPPING_FIELDS.map((field) => (
              <div key={field.key}>
                <label className="mb-2 block text-sm font-medium text-slate-700">{field.label}</label>
                <Select value={mappingForm.field_mapping[field.key] ?? ''} onChange={(event) => setMappingForm((prev) => ({ ...prev, field_mapping: { ...prev.field_mapping, [field.key]: event.target.value } }))}>
                  <option value="">Не использовать</option>
                  {(uploadResult.detected_columns ?? []).map((column) => <option key={`${field.key}-${column}`} value={column}>{column}</option>)}
                </Select>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {previewResult ? (
        <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">3. Проверка перед импортом</h3>
              <p className="mt-1 text-sm text-slate-500">Исправляй строки прямо в таблице. Отдельная очередь проверки больше не нужна в основном сценарии.</p>
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
              const isEditing = editingRowId === row.id;
              const form = getRowForm(row);
              const queries = getRowQuery(row);
              const accountName = findAccountName(accounts, normalized.account_id);
              const targetAccountName = findAccountName(accounts, normalized.target_account_id);
              const categoryName = findCategoryName(categories, normalized.category_id);
              const categoryKind = form.type === 'income' && form.operation_type !== 'refund' ? 'income' : 'expense';

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
                      {row.issues.length ? (
                        <ul className="list-disc pl-5 text-sm text-amber-700">
                          {row.issues.map((issue) => <li key={issue}>{issue}</li>)}
                        </ul>
                      ) : null}
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2">
                      {row.status !== 'skipped' ? (
                        <>
                          <Button type="button" variant="secondary" onClick={() => startEditing(row)}>
                            <Pencil className="size-4" />
                            Изменить
                          </Button>
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

                  {isEditing ? (
                    <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-2 xl:grid-cols-4">
                      <SearchSelect
                        id={`row-account-${row.id}`}
                        label={form.operation_type === 'transfer' ? 'Счёт списания' : 'Счёт'}
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
                            setPendingRowField({ rowId: row.id, field: 'account_id' });
                            setPendingAccountDraft({ name: queries.account_id.trim(), currency: form.currency, balance: 0, is_active: true, is_credit: false });
                            setAccountDialogOpen(true);
                          },
                        }}
                      />

                      <SearchSelect
                        id={`row-operation-${row.id}`}
                        label="Тип операции"
                        placeholder="Начни вводить..."
                        widthClassName="w-full"
                        query={queries.operation_type}
                        setQuery={(value) => updateRowQuery(row.id, { operation_type: value })}
                        items={operationItems}
                        selectedValue={form.operation_type}
                        onSelect={(item) => {
                          updateRowForm(row.id, {
                            operation_type: item.value,
                            type: item.value === 'refund' ? 'income' : form.type,
                            target_account_id: item.value === 'transfer' ? form.target_account_id : '',
                            category_id: item.value === 'transfer' ? '' : form.category_id,
                          });
                          updateRowQuery(row.id, { operation_type: item.label });
                        }}
                        showAllOnFocus
                      />

                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700">Направление</label>
                        <Select value={form.type} onChange={(event) => updateRowForm(row.id, { type: event.target.value as 'income' | 'expense' })}>
                          <option value="expense">Расход</option>
                          <option value="income">Доход</option>
                        </Select>
                      </div>

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

                      {form.operation_type === 'transfer' ? (
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
                              setPendingRowField({ rowId: row.id, field: 'target_account_id' });
                              setPendingAccountDraft({ name: queries.target_account_id.trim(), currency: form.currency, balance: 0, is_active: true, is_credit: false });
                              setAccountDialogOpen(true);
                            },
                          }}
                        />
                      ) : (
                        <SearchSelect
                          id={`row-category-${row.id}`}
                          label="Категория"
                          placeholder="Начни вводить..."
                          widthClassName="w-full"
                          query={queries.category_id}
                          setQuery={(value) => updateRowQuery(row.id, { category_id: value })}
                          items={categoryItemsByKind(categoryKind)}
                          selectedValue={form.category_id}
                          onSelect={(item) => {
                            updateRowForm(row.id, { category_id: item.value });
                            updateRowQuery(row.id, { category_id: item.label });
                          }}
                          showAllOnFocus
                          createAction={{
                            visible: Boolean(queries.category_id.trim()) && !categoryItemsByKind(categoryKind).some((item) => normalize(item.label) === normalize(queries.category_id)),
                            label: 'Создать категорию',
                            onClick: () => {
                              setPendingRowField({ rowId: row.id, field: 'category_id' });
                              setPendingCategoryDraft({ name: queries.category_id.trim(), kind: categoryKind, priority: defaultCategoryPriorityByKind[categoryKind], color: null });
                              setCategoryDialogOpen(true);
                            },
                          }}
                        />
                      )}

                      <div className="flex items-end justify-end gap-2 md:col-span-2 xl:col-span-4">
                        <Button type="button" variant="ghost" onClick={() => setEditingRowId(null)}>Отмена</Button>
                        <Button type="button" onClick={() => submitRow(row, 'confirm')} disabled={rowMutation.isPending}>Сохранить и подтвердить</Button>
                      </div>
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
          setPendingRowField(null);
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
          setPendingRowField(null);
        }}
        onSubmit={(values) => createCategoryMutation.mutate(values)}
      />
    </div>
  );
}

'use client';

import { ChangeEvent, FormEvent, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, FileUp, RefreshCcw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import { getAccounts } from '@/lib/api/accounts';
import { getCategories } from '@/lib/api/categories';
import { commitImport, previewImport, sendImportRowToReview, uploadImportFile } from '@/lib/api/imports';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { ImportStatusBadge } from '@/components/import/import-status-badge';
import type { Account } from '@/types/account';
import type { Category } from '@/types/category';
import type {
  ImportCommitResponse,
  ImportDetection,
  ImportMappingPayload,
  ImportPreviewResponse,
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

const defaultUploadForm: UploadFormState = {
  delimiter: ',',
};

const defaultMappingState: MappingState = {
  account_id: '',
  currency: 'RUB',
  date_format: '%d.%m.%Y',
  table_name: '',
  field_mapping: {},
  skip_duplicates: true,
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
    field_mapping: Object.fromEntries(
      MAPPING_FIELDS.map((field) => [field.key, String(detection.field_mapping?.[field.key] ?? '')]),
    ),
    skip_duplicates: true,
  };
}


function getDirectionLabel(value: unknown) {
  if (value === 'income') return transactionTypeLabels.income;
  if (value === 'expense') return transactionTypeLabels.expense;
  return '—';
}

function getOperationTypeLabel(value: unknown) {
  if (typeof value !== 'string') return '—';
  return operationTypeLabels[value as keyof typeof operationTypeLabels] ?? value;
}

function findAccountName(accounts: Account[], normalizedData: Record<string, unknown>) {
  const accountId = Number(normalizedData.suggested_account_id ?? normalizedData.account_id ?? 0);
  if (!accountId) return null;
  return accounts.find((item) => item.id === accountId)?.name ?? null;
}

function findTargetAccountName(accounts: Account[], normalizedData: Record<string, unknown>) {
  const targetAccountId = Number(normalizedData.suggested_target_account_id ?? normalizedData.target_account_id ?? 0);
  if (!targetAccountId) return null;
  return accounts.find((item) => item.id === targetAccountId)?.name ?? null;
}

function findCategoryName(categories: Category[], normalizedData: Record<string, unknown>) {
  const categoryId = Number(normalizedData.suggested_category_id ?? normalizedData.category_id ?? 0);
  if (!categoryId) return null;
  return categories.find((item) => item.id === categoryId)?.name ?? null;
}

function statCard(label: string, value: number, tone: 'default' | 'success' | 'warning' | 'danger' = 'default') {
  const toneClass =
    tone === 'success'
      ? 'border-emerald-100'
      : tone === 'warning'
        ? 'border-amber-100'
        : tone === 'danger'
          ? 'border-rose-100'
          : 'border-slate-200';

  return (
    <Card className={`rounded-2xl border ${toneClass} bg-white p-4 shadow-soft`}>
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </Card>
  );
}

function toPreviewPayload(mappingForm: MappingState): ImportMappingPayload {
  return {
    account_id: Number(mappingForm.account_id),
    currency: mappingForm.currency,
    date_format: mappingForm.date_format,
    table_name: mappingForm.table_name || null,
    field_mapping: Object.fromEntries(
      Object.entries(mappingForm.field_mapping).map(([key, value]) => [key, value || null]),
    ),
    skip_duplicates: mappingForm.skip_duplicates,
  };
}

export function ImportWizard() {
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'import-preview'], queryFn: () => getCategories() });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadForm, setUploadForm] = useState<UploadFormState>(defaultUploadForm);
  const [mappingForm, setMappingForm] = useState<MappingState>(defaultMappingState);
  const [uploadResult, setUploadResult] = useState<ImportUploadResponse | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitResponse | null>(null);

  const accounts = accountsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  const previewMutation = useMutation({
    mutationFn: ({ sessionId, payload }: { sessionId: number; payload: ImportMappingPayload }) => previewImport(sessionId, payload),
    onSuccess: (data) => {
      setPreviewResult(data);
      setCommitResult(null);
      toast.success('Preview подготовлен');
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

      previewMutation.mutate({
        sessionId: data.session_id,
        payload: toPreviewPayload(nextMapping),
      });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось загрузить источник'),
  });

  const sendToReviewMutation = useMutation({
    mutationFn: (rowId: number) => sendImportRowToReview(rowId),
    onSuccess: (updatedRow) => {
      setPreviewResult((prev) => {
        if (!prev) return prev;
        const previousRow = prev.rows.find((row) => row.id === updatedRow.id);
        if (!previousRow) return prev;

        return {
          ...prev,
          summary: {
            ...prev.summary,
            ready_rows: previousRow.status === 'ready' ? Math.max(0, prev.summary.ready_rows - 1) : prev.summary.ready_rows,
            warning_rows: previousRow.status === 'ready' ? prev.summary.warning_rows + 1 : prev.summary.warning_rows,
          },
          rows: prev.rows.map((row) => (row.id === updatedRow.id ? updatedRow : row)),
        };
      });
      toast.success('Строка отправлена на проверку');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось отправить строку на проверку'),
  });

  const commitMutation = useMutation({
    mutationFn: ({ sessionId, importReadyOnly }: { sessionId: number; importReadyOnly: boolean }) =>
      commitImport(sessionId, importReadyOnly),
    onSuccess: (data) => {
      setCommitResult(data);
      toast.success('Импорт завершён');
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось завершить импорт'),
  });

  const detection = uploadResult?.detection;
  const previewTopRows = useMemo(() => (previewResult?.rows ?? []).slice(0, 25), [previewResult]);

  function resetAll() {
    setSelectedFile(null);
    setUploadForm(defaultUploadForm);
    setMappingForm(defaultMappingState);
    setUploadResult(null);
    setPreviewResult(null);
    setCommitResult(null);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
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
    previewMutation.mutate({
      sessionId: uploadResult.session_id,
      payload: toPreviewPayload(nextForm),
    });
  }

  if (accountsQuery.isLoading || categoriesQuery.isLoading) return <LoadingState title="Загружаем данные для импорта..." />;
  if (accountsQuery.isError || categoriesQuery.isError) {
    return <ErrorState title="Не удалось открыть импорт" description="Проверь подключение к API и доступность списка счетов." />;
  }
  if (!accounts.length) {
    return <EmptyState title="Нет счетов для импорта" description="Сначала создай хотя бы один счёт, чтобы привязать к нему импортируемые транзакции." />;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        {statCard('Источник загружен', uploadResult ? 1 : 0, uploadResult ? 'success' : 'default')}
        {statCard('Preview готов', previewResult ? 1 : 0, previewResult ? 'success' : 'default')}
        {statCard('Готово к commit', previewResult?.summary.ready_rows ?? 0, 'success')}
        {statCard('Требуют проверки', previewResult?.summary.warning_rows ?? 0, 'warning')}
      </div>

      <Card className="rounded-2xl bg-white p-5 shadow-soft">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">1. Источник</h3>
            <p className="mt-1 text-sm text-slate-500">
              Загрузи CSV, XLSX или text-based PDF. После распознавания preview строится автоматически без ручного шага настройки.
            </p>
          </div>
          <Button variant="secondary" onClick={resetAll}>
            <RefreshCcw className="size-4" />
            Сбросить
          </Button>
        </div>

        <form className="grid gap-4 md:grid-cols-3" onSubmit={handleUploadSubmit}>
          <div className="md:col-span-2">
            <label className="mb-2 block text-sm font-medium text-slate-700">Файл источника</label>
            <Input type="file" accept=".csv,.xlsx,.pdf" onChange={handleFileChange} />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">Разделитель CSV</label>
            <Input
              value={uploadForm.delimiter}
              onChange={(event) => setUploadForm((prev) => ({ ...prev, delimiter: event.target.value || ',' }))}
              maxLength={1}
            />
          </div>
          <div className="md:col-span-3 flex justify-end">
            <Button type="submit" disabled={uploadMutation.isPending || previewMutation.isPending}>
              <FileUp className="size-4" />
              {uploadMutation.isPending ? 'Загрузка...' : 'Загрузить и распознать'}
            </Button>
          </div>
        </form>

        {uploadResult ? (
          <div className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-2xl border border-slate-200 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <Sparkles className="size-4 text-primary" />
                Результат извлечения
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600">
                <p><span className="font-medium text-slate-900">Файл:</span> {uploadResult.filename}</p>
                <p><span className="font-medium text-slate-900">Тип:</span> {sourceLabel(uploadResult.source_type)}</p>
                <p><span className="font-medium text-slate-900">Найдено строк:</span> {uploadResult.total_rows}</p>
                <p><span className="font-medium text-slate-900">Таблиц:</span> {String(uploadResult.extraction.tables_found ?? '—')}</p>
                <p>
                  <span className="font-medium text-slate-900">Уверенность распознавания:</span>{' '}
                  {Math.round((uploadResult.detection.overall_confidence ?? 0) * 100)}%
                </p>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 p-4">
              <div className="text-sm font-medium text-slate-900">Автоопределение полей</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(uploadResult.detection.field_mapping).map(([field, value]) => (
                  <span key={field} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">
                    {field}: {value || '—'}
                  </span>
                ))}
              </div>
              {!!uploadResult.detection.unresolved_fields.length && (
                <div className="mt-3 flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <div>Нужно проверить: {uploadResult.detection.unresolved_fields.join(', ')}</div>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </Card>

      {uploadResult ? (
        <Card className="rounded-2xl bg-white p-5 shadow-soft">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">2. Preview и commit</h3>
              <p className="mt-1 text-sm text-slate-500">
                Preview строится автоматически. Здесь можно только сменить счёт и перестроить результат.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-[260px_auto]">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Счёт</label>
                <Select
                  value={mappingForm.account_id}
                  onChange={(event) => {
                    const account = accounts.find((item) => String(item.id) === event.target.value);
                    setMappingForm((prev) => ({
                      ...prev,
                      account_id: event.target.value,
                      currency: account?.currency ?? prev.currency,
                    }));
                  }}
                >
                  {accounts.map((account) => (
                    <option key={account.id} value={String(account.id)}>
                      {account.name} · {account.currency}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex items-end">
                <Button variant="secondary" onClick={() => rebuildPreview(mappingForm)} disabled={previewMutation.isPending}>
                  {previewMutation.isPending ? 'Строим preview...' : 'Обновить preview'}
                </Button>
              </div>
            </div>
          </div>

          {previewResult ? (
            <>
              <div className="mb-5 flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-sm text-emerald-700 w-fit">
                <CheckCircle2 className="size-4" />
                {Math.round((previewResult.detection.overall_confidence ?? 0) * 100)}% confidence
              </div>

              <div className="grid gap-4 md:grid-cols-5">
                {statCard('Всего строк', previewResult.summary.total_rows)}
                {statCard('Готово', previewResult.summary.ready_rows, 'success')}
                {statCard('Проверить', previewResult.summary.warning_rows, 'warning')}
                {statCard('Ошибки', previewResult.summary.error_rows, 'danger')}
                {statCard('Дубликаты', previewResult.summary.duplicate_rows, 'warning')}
              </div>

              <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-200 text-sm">
                    <thead className="bg-slate-50 text-left text-slate-600">
                      <tr>
                        <th className="px-4 py-3">#</th>
                        <th className="px-4 py-3">Статус</th>
                        <th className="px-4 py-3">Уверенность</th>
                        <th className="px-4 py-3">Нормализованные данные</th>
                        <th className="px-4 py-3">Проблемы</th>
                        <th className="px-4 py-3 text-right">Действие</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {previewTopRows.map((row) => (
                        <tr key={row.row_index} className="align-top">
                          <td className="px-4 py-3 text-slate-500">{row.row_index}</td>
                          <td className="px-4 py-3"><ImportStatusBadge status={row.status} /></td>
                          <td className="px-4 py-3 text-slate-700">{Math.round((row.confidence ?? 0) * 100)}%</td>
                          <td className="px-4 py-3 text-slate-700">
                            {(() => {
                              const accountName = findAccountName(accounts, row.normalized_data);
                              const targetAccountName = findTargetAccountName(accounts, row.normalized_data);
                              const categoryName = findCategoryName(categories, row.normalized_data);
                              return (
                                <>
                                  <div>Дата: {String(row.normalized_data.date ?? '—')}</div>
                                  <div>Описание: {String(row.normalized_data.description ?? '—')}</div>
                                  <div>Сумма: {String(row.normalized_data.amount ?? '—')} {String(row.normalized_data.currency ?? '')}</div>
                                  <div>Направление: {getDirectionLabel(row.normalized_data.direction ?? row.normalized_data.type)}</div>
                                  <div>Тип: {getOperationTypeLabel(row.normalized_data.suggested_operation_type ?? row.normalized_data.operation_type)}</div>
                                  <div>Категория: {categoryName ?? '—'}</div>
                                  <div>Счёт: {accountName ?? '—'}</div>
                                  {targetAccountName ? <div>Счёт поступления: {targetAccountName}</div> : null}
                                </>
                              );
                            })()}
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {row.issues?.length ? row.issues.join('; ') : row.error_message || '—'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            {row.status === 'ready' ? (
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => sendToReviewMutation.mutate(row.id)}
                                disabled={sendToReviewMutation.isPending}
                              >
                                На проверку
                              </Button>
                            ) : (
                              <span className="text-xs text-slate-400">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
                <Button
                  variant="secondary"
                  onClick={() => commitMutation.mutate({ sessionId: previewResult.session_id, importReadyOnly: true })}
                  disabled={commitMutation.isPending}
                >
                  Импортировать только ready
                </Button>
                <Button
                  onClick={() => commitMutation.mutate({ sessionId: previewResult.session_id, importReadyOnly: false })}
                  disabled={commitMutation.isPending}
                >
                  Импортировать всё, кроме error
                </Button>
                <div className="w-full text-right text-xs text-slate-500">
                  Строки, которые вручную отправлены на проверку, попадут в очередь проверки при импорте через кнопку «Импортировать всё, кроме error».
                </div>
              </div>

              {commitResult ? (
                <div className="mt-6 rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-900">
                  Импорт завершён. Создано: {commitResult.imported_count}, пропущено: {commitResult.skipped_count},
                  дубликатов: {commitResult.duplicate_count}, ошибок: {commitResult.error_count}, требует review: {commitResult.review_count}.
                </div>
              ) : null}
            </>
          ) : (
            <div className="rounded-2xl border border-slate-200 p-6 text-sm text-slate-500">
              {previewMutation.isPending ? 'Строим preview...' : 'После загрузки файла preview появится здесь автоматически.'}
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}

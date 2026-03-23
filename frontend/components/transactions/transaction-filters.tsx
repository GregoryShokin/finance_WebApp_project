'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CalendarDays, CalendarRange, ChevronDown, ChevronUp, SlidersHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import type { Account } from '@/types/account';
import type { Category, CategoryPriority } from '@/types/category';
import type { TransactionKind, TransactionOperationType } from '@/types/transaction';
import { getOperationOptionsByKind } from '@/components/transactions/constants';
import { cn } from '@/lib/utils/cn';

const categoryPriorityLabels: Record<CategoryPriority, string> = {
  expense_essential: 'Обязательные расходы',
  expense_secondary: 'Второстепенные расходы',
  expense_target: 'Целевые расходы',
  income_active: 'Активный доход',
  income_passive: 'Пассивный доход',
};

function formatDisplayDate(value: string) {
  if (!value) return 'дд.мм.гггг';
  const [year, month, day] = value.split('-');
  if (!year || !month || !day) return value;
  return `${day}.${month}.${year}`;
}

function toDateInputValue(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function getDatePreset(preset: 'today' | 'yesterday' | 'week' | 'currentMonth' | 'previousMonth') {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  if (preset === 'today') {
    const value = toDateInputValue(today);
    return { date_from: value, date_to: value };
  }

  if (preset === 'yesterday') {
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const value = toDateInputValue(yesterday);
    return { date_from: value, date_to: value };
  }

  if (preset === 'week') {
    const start = new Date(today);
    const day = start.getDay();
    const diff = day === 0 ? 6 : day - 1;
    start.setDate(start.getDate() - diff);
    return { date_from: toDateInputValue(start), date_to: toDateInputValue(today) };
  }

  if (preset === 'currentMonth') {
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return { date_from: toDateInputValue(start), date_to: toDateInputValue(end) };
  }

  const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const end = new Date(today.getFullYear(), today.getMonth(), 0);
  return { date_from: toDateInputValue(start), date_to: toDateInputValue(end) };
}

function FilterBlock({
  icon,
  title,
  description,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
      <div className="mb-4 flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-white text-slate-600 shadow-sm">
          {icon}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

function DateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className="grid gap-1.5">
      <label className="text-xs font-medium text-slate-600">{label}</label>
      <div className="relative">
        <button
          type="button"
          className="flex h-11 w-full items-center justify-between rounded-xl border bg-white px-3 py-2 text-sm text-slate-900 transition hover:border-slate-400"
          onClick={() => {
            if (inputRef.current && 'showPicker' in inputRef.current) {
              (inputRef.current as HTMLInputElement & { showPicker?: () => void }).showPicker?.();
            }
            inputRef.current?.focus();
          }}
        >
          <span className={cn(value ? 'text-slate-900' : 'text-slate-400')}>{formatDisplayDate(value)}</span>
          <CalendarDays className="size-4 text-slate-500" />
        </button>
        <input
          ref={inputRef}
          type="date"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          aria-label={label}
        />
      </div>
    </div>
  );
}

export function TransactionFilters({
  value,
  accounts,
  categories,
  collapsed,
  onToggle,
  onChange,
}: {
  value: {
    search: string;
    account_id: string;
    category_id: string;
    category_priority: 'all' | CategoryPriority;
    type: 'all' | TransactionKind;
    operation_type: 'all' | TransactionOperationType;
    date_from: string;
    date_to: string;
    min_amount: string;
    max_amount: string;
    needs_review: 'all' | 'true' | 'false';
  };
  accounts: Account[];
  categories: Category[];
  collapsed: boolean;
  onToggle: () => void;
  onChange: (next: {
    search: string;
    account_id: string;
    category_id: string;
    category_priority: 'all' | CategoryPriority;
    type: 'all' | TransactionKind;
    operation_type: 'all' | TransactionOperationType;
    date_from: string;
    date_to: string;
    min_amount: string;
    max_amount: string;
    needs_review: 'all' | 'true' | 'false';
  }) => void;
}) {
  const [typeQuery, setTypeQuery] = useState('Все виды');
  const [operationQuery, setOperationQuery] = useState('Все типы операций');
  const [accountQuery, setAccountQuery] = useState('Все счета');
  const [priorityQuery, setPriorityQuery] = useState('Все признаки категорий');
  const [categoryQuery, setCategoryQuery] = useState('Все категории');
  const [reviewQuery, setReviewQuery] = useState('Все статусы проверки');

  const transactionTypeItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'all', label: 'Все виды', searchText: 'все виды все типы' },
      { value: 'expense', label: 'Только расходы', searchText: 'расход расходные expense' },
      { value: 'income', label: 'Только доходы', searchText: 'доход доходные income' },
    ],
    [],
  );

  const operationOptions =
    value.type === 'all'
      ? [
          ...getOperationOptionsByKind('expense'),
          ...getOperationOptionsByKind('income').filter((i) => i.value !== 'regular' && i.value !== 'transfer'),
        ].filter((item, index, self) => self.findIndex((x) => x.value === item.value) === index)
      : getOperationOptionsByKind(value.type);

  const operationItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'all', label: 'Все типы операций', searchText: 'все типы операций' },
      ...operationOptions.map((item) => ({
        value: item.value,
        label: item.label,
        searchText: `${item.label} ${item.value}`,
      })),
    ],
    [operationOptions],
  );

  const accountItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: '', label: 'Все счета', searchText: 'все счета все аккаунты' },
      ...accounts.map((account) => ({
        value: String(account.id),
        label: account.name,
        searchText: `${account.name} ${account.currency}`,
        badge: account.currency,
      })),
    ],
    [accounts],
  );

  const categoryPriorityItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'all', label: 'Все признаки категорий', searchText: 'все признаки категорий' },
      ...Object.entries(categoryPriorityLabels)
        .filter(([priority]) => value.type === 'all' || (value.type === 'expense' ? priority.startsWith('expense_') : priority.startsWith('income_')))
        .map(([priority, label]) => ({
          value: priority,
          label,
          searchText: `${label} ${priority}`,
        })),
    ],
    [value.type],
  );

  const visibleCategories = useMemo(
    () =>
      categories.filter((category) => {
        const kindMatch = value.type === 'all' || category.kind === value.type;
        const priorityMatch = value.category_priority === 'all' || category.priority === value.category_priority;
        return kindMatch && priorityMatch;
      }),
    [categories, value.category_priority, value.type],
  );

  const categoryItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: '', label: 'Все категории', searchText: 'все категории' },
      ...visibleCategories.map((category) => ({
        value: String(category.id),
        label: category.name,
        searchText: `${category.name} ${category.kind} ${category.priority}`,
        badge: category.kind === 'income' ? 'Доход' : 'Расход',
        badgeClassName: category.kind === 'income' ? 'text-emerald-600' : 'text-rose-600',
      })),
    ],
    [visibleCategories],
  );

  const reviewItems = useMemo<SearchSelectItem[]>(
    () => [
      { value: 'all', label: 'Все статусы проверки', searchText: 'все статусы проверки' },
      { value: 'true', label: 'Только требующие проверки', searchText: 'требует проверки review' },
      { value: 'false', label: 'Только подтверждённые', searchText: 'подтверждена подтвержденные' },
    ],
    [],
  );

  useEffect(() => {
    setTypeQuery(transactionTypeItems.find((item) => item.value === value.type)?.label ?? 'Все виды');
  }, [transactionTypeItems, value.type]);

  useEffect(() => {
    setOperationQuery(operationItems.find((item) => item.value === value.operation_type)?.label ?? 'Все типы операций');
  }, [operationItems, value.operation_type]);

  useEffect(() => {
    setAccountQuery(accountItems.find((item) => item.value === value.account_id)?.label ?? 'Все счета');
  }, [accountItems, value.account_id]);

  useEffect(() => {
    setPriorityQuery(categoryPriorityItems.find((item) => item.value === value.category_priority)?.label ?? 'Все признаки категорий');
  }, [categoryPriorityItems, value.category_priority]);

  useEffect(() => {
    setCategoryQuery(categoryItems.find((item) => item.value === value.category_id)?.label ?? 'Все категории');
  }, [categoryItems, value.category_id]);

  useEffect(() => {
    setReviewQuery(reviewItems.find((item) => item.value === value.needs_review)?.label ?? 'Все статусы проверки');
  }, [reviewItems, value.needs_review]);

  return (
    <Card className="rounded-2xl bg-white p-4 shadow-soft">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Фильтр транзакций</h2>
          <p className="text-xs text-slate-500">Поиск по признакам, диапазону дат и сумме.</p>
        </div>
        <Button variant="secondary" onClick={onToggle}>
          {collapsed ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
          {collapsed ? 'Показать фильтр' : 'Скрыть фильтр'}
        </Button>
      </div>

      {!collapsed ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <FilterBlock
            icon={<SlidersHorizontal className="size-4" />}
            title="Поиск по признакам"
            description="Сузь список по виду операции, типу, счёту, категории, признаку категории, сумме и статусу проверки."
          >
            <div className="grid gap-3">
              <SearchSelect
                id="transaction-filter-type"
                label="Вид операции"
                placeholder="Выбери вид операции"
                widthClassName="w-full"
                query={typeQuery}
                setQuery={setTypeQuery}
                items={transactionTypeItems}
                selectedValue={value.type}
                onSelect={(item) =>
                  onChange({
                    ...value,
                    type: item.value as 'all' | TransactionKind,
                    operation_type: 'all',
                    category_id: '',
                    category_priority: 'all',
                  })
                }
                showAllOnFocus
                limit={12}
              />

              <SearchSelect
                id="transaction-filter-operation"
                label="Тип операции"
                placeholder="Выбери тип операции"
                widthClassName="w-full"
                query={operationQuery}
                setQuery={setOperationQuery}
                items={operationItems}
                selectedValue={value.operation_type}
                onSelect={(item) => onChange({ ...value, operation_type: item.value as 'all' | TransactionOperationType })}
                showAllOnFocus
                limit={12}
              />

              <SearchSelect
                id="transaction-filter-account"
                label="Счёт"
                placeholder="Выбери счёт"
                widthClassName="w-full"
                query={accountQuery}
                setQuery={setAccountQuery}
                items={accountItems}
                selectedValue={value.account_id}
                onSelect={(item) => onChange({ ...value, account_id: item.value })}
                showAllOnFocus
                limit={12}
              />

              <SearchSelect
                id="transaction-filter-category-priority"
                label="Признак категории"
                placeholder="Выбери признак категории"
                widthClassName="w-full"
                query={priorityQuery}
                setQuery={setPriorityQuery}
                items={categoryPriorityItems}
                selectedValue={value.category_priority}
                onSelect={(item) =>
                  onChange({
                    ...value,
                    category_priority: item.value as 'all' | CategoryPriority,
                    category_id: '',
                  })
                }
                showAllOnFocus
                limit={12}
              />

              <SearchSelect
                id="transaction-filter-category"
                label="Категория"
                placeholder="Выбери категорию"
                widthClassName="w-full"
                query={categoryQuery}
                setQuery={setCategoryQuery}
                items={categoryItems}
                selectedValue={value.category_id}
                onSelect={(item) => onChange({ ...value, category_id: item.value })}
                showAllOnFocus
                limit={12}
              />

              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  type="number"
                  step="0.01"
                  placeholder="Мин. сумма"
                  value={value.min_amount}
                  onChange={(event) => onChange({ ...value, min_amount: event.target.value })}
                />

                <Input
                  type="number"
                  step="0.01"
                  placeholder="Макс. сумма"
                  value={value.max_amount}
                  onChange={(event) => onChange({ ...value, max_amount: event.target.value })}
                />
              </div>

              <SearchSelect
                id="transaction-filter-review"
                label="Статус проверки"
                placeholder="Выбери статус проверки"
                widthClassName="w-full"
                query={reviewQuery}
                setQuery={setReviewQuery}
                items={reviewItems}
                selectedValue={value.needs_review}
                onSelect={(item) => onChange({ ...value, needs_review: item.value as 'all' | 'true' | 'false' })}
                showAllOnFocus
                limit={12}
              />
            </div>
          </FilterBlock>

          <FilterBlock
            icon={<CalendarRange className="size-4" />}
            title="Поиск по дате"
            description="Укажи период, чтобы увидеть транзакции за нужный промежуток времени."
          >
            <div className="grid gap-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <DateField
                  label="От"
                  value={value.date_from}
                  onChange={(nextValue) => onChange({ ...value, date_from: nextValue })}
                />
                <DateField
                  label="До"
                  value={value.date_to}
                  onChange={(nextValue) => onChange({ ...value, date_to: nextValue })}
                />
              </div>

              <div className="grid gap-1.5">
                <span className="text-xs font-medium text-slate-600">Выбор периода</span>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" onClick={() => onChange({ ...value, ...getDatePreset('today') })}>
                    Сегодня
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => onChange({ ...value, ...getDatePreset('yesterday') })}>
                    Вчера
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => onChange({ ...value, ...getDatePreset('week') })}>
                    Неделя
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => onChange({ ...value, ...getDatePreset('currentMonth') })}>
                    Текущий месяц
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => onChange({ ...value, ...getDatePreset('previousMonth') })}>
                    Прошлый месяц
                  </Button>
                </div>
              </div>
            </div>
          </FilterBlock>
        </div>
      ) : null}
    </Card>
  );
}

'use client';

/**
 * Entity-aware selects for the import moderator (warm redesign, 2026-04-30).
 *
 * Wraps <CreatableSelect> with 4 ready-to-use variants:
 *   • CategorySelect      — opens existing CategoryDialog (full kind+priority form)
 *   • CounterpartySelect  — inline create (name only)
 *   • DebtPartnerSelect   — inline create (name only; opening balances = 0)
 *   • AccountSelect       — opens existing AccountDialog (4+ required fields)
 *
 * After a successful create, all four variants invalidate their query keys and
 * call setValue on the new id so the row immediately reflects the choice.
 */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Pencil } from 'lucide-react';

import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { CounterpartyDialog } from '@/components/counterparties/counterparty-dialog';
import { createCategory } from '@/lib/api/categories';
import { createCounterparty, updateCounterparty } from '@/lib/api/counterparties';
import { createDebtPartner } from '@/lib/api/debt-partners';
import { createAccount } from '@/lib/api/accounts';
import type {
  Category,
  CategoryKind,
  CategoryPriority,
  CreateCategoryPayload,
} from '@/types/category';
import type { Counterparty } from '@/types/counterparty';
import type { DebtPartner } from '@/types/debt-partner';
import type { Account, CreateAccountPayload } from '@/types/account';

// ──────────────────────────────────────────────────────────────────────────
// Category
// ──────────────────────────────────────────────────────────────────────────

const DEFAULT_PRIORITY_BY_KIND: Record<CategoryKind, CategoryPriority> = {
  expense: 'expense_secondary',
  income: 'income_active',
};

export function CategorySelect({
  value,
  options,
  onChange,
  kind,
  width,
  placeholder = '— выбрать категорию —',
  disabled = false,
}: {
  value: number | null | undefined;
  options: CreatableOption[];
  onChange: (id: number) => void;
  /** Drives default kind & priority for the create dialog prefill. */
  kind: CategoryKind;
  width?: number | string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [prefill, setPrefill] = useState<Partial<CreateCategoryPayload> | null>(null);

  const createMut = useMutation({
    mutationFn: (payload: CreateCategoryPayload) => createCategory(payload),
    onSuccess: async (cat: Category) => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
      onChange(cat.id);
      toast.success(`Категория «${cat.name}» создана`);
      setDialogOpen(false);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать категорию'),
  });

  return (
    <>
      <CreatableSelect
        value={value != null ? String(value) : null}
        options={options}
        onChange={(v) => onChange(Number(v))}
        placeholder={placeholder}
        width={width}
        disabled={disabled}
        createMode={{
          kind: 'dialog',
          createLabel: 'Создать категорию…',
          onOpenCreateDialog: (q) => {
            setPrefill({
              name: q,
              kind,
              priority: DEFAULT_PRIORITY_BY_KIND[kind],
            });
            setDialogOpen(true);
          },
        }}
      />

      <CategoryDialog
        open={dialogOpen}
        mode="create"
        initialValues={prefill}
        isSubmitting={createMut.isPending}
        onClose={() => setDialogOpen(false)}
        onSubmit={(values) => createMut.mutate(values)}
      />
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Counterparty
// ──────────────────────────────────────────────────────────────────────────

export function CounterpartySelect({
  value,
  options,
  onChange,
  width,
  placeholder = '— контрагент —',
  disabled = false,
}: {
  value: number | null | undefined;
  options: CreatableOption[];
  onChange: (id: number) => void;
  width?: number | string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);

  const createMut = useMutation({
    mutationFn: (name: string) => createCounterparty({ name }),
    onSuccess: async (cp) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      toast.success(`Контрагент «${cp.name}» создан`);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать контрагента'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => updateCounterparty(id, { name }),
    onSuccess: async (cp) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      toast.success(`Контрагент переименован в «${cp.name}»`);
      setEditOpen(false);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось обновить контрагента'),
  });

  // Initial value for the edit dialog — the currently selected counterparty's
  // name. Pulled from the options prop to avoid a second fetch.
  const currentName =
    value != null ? options.find((o) => o.value === String(value))?.label ?? '' : '';

  return (
    <>
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <CreatableSelect
            value={value != null ? String(value) : null}
            options={options}
            onChange={(v) => onChange(Number(v))}
            placeholder={placeholder}
            width={width}
            disabled={disabled}
            createMode={{
              kind: 'inline',
              onCreate: async (name) => {
                const cp: Counterparty = await createMut.mutateAsync(name);
                return { value: String(cp.id), label: cp.name };
              },
            }}
          />
        </div>
        {value != null && !disabled ? (
          <button
            type="button"
            onClick={() => setEditOpen(true)}
            title="Переименовать контрагента"
            aria-label="Переименовать контрагента"
            className="grid size-7 shrink-0 place-items-center rounded-md border border-line bg-bg-surface text-ink-3 transition hover:border-ink-3 hover:bg-bg-surface2 hover:text-ink"
          >
            <Pencil className="size-3.5" />
          </button>
        ) : null}
      </div>

      <CounterpartyDialog
        open={editOpen}
        mode="edit"
        draft={{ name: currentName }}
        isSubmitting={updateMut.isPending}
        onClose={() => setEditOpen(false)}
        onSubmit={(values) => {
          if (value != null) updateMut.mutate({ id: value, name: values.name });
        }}
      />
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Debt partner (debtors / creditors)
// ──────────────────────────────────────────────────────────────────────────

export function DebtPartnerSelect({
  value,
  options,
  onChange,
  width,
  placeholder = '— дебитор / кредитор —',
  disabled = false,
}: {
  value: number | null | undefined;
  options: CreatableOption[];
  onChange: (id: number) => void;
  width?: number | string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();

  const createMut = useMutation({
    mutationFn: (name: string) => createDebtPartner({ name }),
    onSuccess: async (dp) => {
      await queryClient.invalidateQueries({ queryKey: ['debt-partners'] });
      toast.success(`«${dp.name}» добавлен`);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать запись'),
  });

  return (
    <CreatableSelect
      value={value != null ? String(value) : null}
      options={options}
      onChange={(v) => onChange(Number(v))}
      placeholder={placeholder}
      width={width}
      disabled={disabled}
      createMode={{
        kind: 'inline',
        onCreate: async (name) => {
          const dp: DebtPartner = await createMut.mutateAsync(name);
          return { value: String(dp.id), label: dp.name };
        },
      }}
    />
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Account — full dialog (option (b) per 2026-04-30 design decision)
// ──────────────────────────────────────────────────────────────────────────

export function AccountSelect({
  value,
  options,
  onChange,
  width,
  placeholder = '— счёт —',
  disabled = false,
  filterFn,
}: {
  value: number | null | undefined;
  options: CreatableOption[];
  onChange: (id: number) => void;
  width?: number | string;
  placeholder?: string;
  disabled?: boolean;
  /** Optional filter applied before passing options through (e.g. only credit accounts). */
  filterFn?: (option: CreatableOption) => boolean;
}) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [prefillName, setPrefillName] = useState('');

  const createMut = useMutation({
    mutationFn: (payload: CreateAccountPayload) => createAccount(payload),
    onSuccess: async (acc: Account) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      onChange(acc.id);
      toast.success(`Счёт «${acc.name}» создан`);
      setDialogOpen(false);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать счёт'),
  });

  const filteredOptions = filterFn ? options.filter(filterFn) : options;

  return (
    <>
      <CreatableSelect
        value={value != null ? String(value) : null}
        options={filteredOptions}
        onChange={(v) => onChange(Number(v))}
        placeholder={placeholder}
        width={width}
        disabled={disabled}
        createMode={{
          kind: 'dialog',
          createLabel: 'Создать счёт…',
          onOpenCreateDialog: (q) => {
            setPrefillName(q);
            setDialogOpen(true);
          },
        }}
      />

      <AccountDialog
        open={dialogOpen}
        mode="create"
        initialValues={prefillName ? { name: prefillName } : null}
        isSubmitting={createMut.isPending}
        onClose={() => setDialogOpen(false)}
        onSubmit={(values) => createMut.mutate(values)}
      />
    </>
  );
}

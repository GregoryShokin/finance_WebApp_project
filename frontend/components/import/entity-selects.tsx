'use client';

/**
 * Entity-aware selects for the import moderator (warm redesign, 2026-04-30).
 *
 * Wraps <CreatableSelect> with 4 ready-to-use variants:
 *   • CategorySelect      — inline create (name only; kind & priority defaulted)
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

import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { createCategory } from '@/lib/api/categories';
import { createCounterparty } from '@/lib/api/counterparties';
import { createDebtPartner } from '@/lib/api/debt-partners';
import { createAccount } from '@/lib/api/accounts';
import type { Category, CategoryKind, CategoryPriority } from '@/types/category';
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
  /** Drives default priority when creating a new category inline. */
  kind: CategoryKind;
  width?: number | string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();

  const createMut = useMutation({
    mutationFn: (name: string) =>
      createCategory({ name, kind, priority: DEFAULT_PRIORITY_BY_KIND[kind] }),
    onSuccess: async (cat) => {
      await queryClient.invalidateQueries({ queryKey: ['categories'] });
      toast.success(`Категория «${cat.name}» создана`);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать категорию'),
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
        createLabel: undefined,
        onCreate: async (name) => {
          const cat: Category = await createMut.mutateAsync(name);
          return { value: String(cat.id), label: cat.name };
        },
      }}
    />
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

  const createMut = useMutation({
    mutationFn: (name: string) => createCounterparty({ name }),
    onSuccess: async (cp) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      toast.success(`Контрагент «${cp.name}» создан`);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать контрагента'),
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
          const cp: Counterparty = await createMut.mutateAsync(name);
          return { value: String(cp.id), label: cp.name };
        },
      }}
    />
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

'use client';

/**
 * Entity-aware selects for the import moderator (warm redesign, 2026-04-30).
 *
 * Wraps <CreatableSelect> with the variants the live moderator uses:
 *   • CategorySelect    — opens existing CategoryDialog (full kind+priority form)
 *   • BrandSelect       — inline create (Phase C successor to CounterpartySelect)
 *   • DebtPartnerSelect — inline create (name only; opening balances = 0)
 *   • AccountSelect     — opens existing AccountDialog (4+ required fields)
 *
 * After a successful create, all variants invalidate their query keys and
 * call setValue on the new id so the row immediately reflects the choice.
 *
 * Phase C step 5: CounterpartySelect was removed alongside the dropped
 * Counterparty table. BrandSelect covers the same UX surface for the
 * merchant entity.
 */

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { AccountDialog } from '@/components/accounts/account-dialog';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { createCategory } from '@/lib/api/categories';
import { createBrand, type Brand } from '@/lib/api/brands';
import { createDebtPartner } from '@/lib/api/debt-partners';
import { createAccount } from '@/lib/api/accounts';
import type {
  Category,
  CategoryKind,
  CategoryPriority,
  CreateCategoryPayload,
} from '@/types/category';
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

// CounterpartySelect was removed in Phase C step 5 — see the BrandSelect
// below for the live merchant picker.

// ──────────────────────────────────────────────────────────────────────────
// Brand (Phase C — successor to CounterpartySelect for the import moderator).
//
// Differences from CounterpartySelect:
//   • options come from /brands (private + global merged), not /counterparties
//   • inline-create produces a private brand via /brands POST
//   • no inline rename — Brand renames live in the Brand management surface,
//     and a per-user display label edit goes through UserBrandDisplayName
//     (not exposed here yet; row-level brand-prompt handles it)
// ──────────────────────────────────────────────────────────────────────────

export function BrandSelect({
  value,
  options,
  onChange,
  width,
  placeholder = '— бренд —',
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
    mutationFn: (name: string) =>
      createBrand({ canonical_name: name, category_hint: null }),
    onSuccess: async (b: Brand) => {
      await queryClient.invalidateQueries({ queryKey: ['brands'] });
      toast.success(`Бренд «${b.canonical_name}» создан`);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать бренд'),
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
          const b: Brand = await createMut.mutateAsync(name);
          return { value: String(b.id), label: b.canonical_name };
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

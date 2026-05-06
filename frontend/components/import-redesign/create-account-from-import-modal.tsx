'use client';

/**
 * Auto-account-recognition Шаг 3 (2026-05-06).
 *
 * When the upload response carries `requires_account_creation=true`, the
 * extractor recognised the bank+account_type combination but the user
 * doesn't own a matching account yet. Instead of dropping them into the
 * generic queue, we open this modal pre-filled with everything we already
 * know — bank, account_type, contract_number, statement_account_number —
 * so the user only needs to confirm a name and the balance.
 *
 * On success, the new account is bound to the session via
 * `assignSessionAccount(sessionId, accountId)` (the same endpoint the queue
 * picker uses), preserving the existing auto-preview path.
 */

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { AccountDialog } from '@/components/accounts/account-dialog';
import { createAccount } from '@/lib/api/accounts';
import { getBanks } from '@/lib/api/banks';
import { assignSessionAccount } from '@/lib/api/imports';
import type { AccountType, Bank, CreateAccountPayload } from '@/types/account';

// Map import-side `account_type_hint` strings (mirroring backend
// `Account.account_type`) to the form's AccountType enum. The cast is safe
// because both sides share the same string codes — the indirection exists
// to keep the form type-checked when the backend adds new ones.
function asAccountType(hint: string | null | undefined): AccountType | undefined {
  if (!hint) return undefined;
  const allowed: AccountType[] = [
    'main', 'cash', 'marketplace', 'loan', 'credit_card',
    'installment_card', 'broker', 'savings', 'savings_account', 'currency',
  ];
  return allowed.includes(hint as AccountType) ? (hint as AccountType) : undefined;
}

export function CreateAccountFromImportModal({
  open,
  sessionId,
  bankId,
  accountTypeHint,
  contractNumber,
  statementAccountNumber,
  onClose,
  onAttached,
}: {
  open: boolean;
  sessionId: number;
  bankId: number;
  accountTypeHint: string | null | undefined;
  contractNumber: string | null | undefined;
  statementAccountNumber: string | null | undefined;
  onClose: () => void;
  // Called after the account is created AND attached to the session, so the
  // parent can refresh queries + setActive(sessionId).
  onAttached: () => void;
}) {
  const queryClient = useQueryClient();
  const [submitting, setSubmitting] = useState(false);

  // Resolve the Bank from the id. Backend has no `/banks/{id}` endpoint, but
  // the full list is short (≤ 50 records) and already cached elsewhere; one
  // shared query keeps the picker pre-selected without a roundtrip per modal.
  const banksQuery = useQuery({
    queryKey: ['banks', { supportedOnly: false }],
    queryFn: () => getBanks(undefined, { supportedOnly: false }),
    staleTime: 60_000,
  });
  const bank = useMemo<Bank | null>(() => {
    const all = banksQuery.data ?? [];
    return all.find((b) => b.id === bankId) ?? null;
  }, [banksQuery.data, bankId]);

  const createAndAttachMut = useMutation({
    mutationFn: async (payload: CreateAccountPayload) => {
      const account = await createAccount(payload);
      // Backend returns the account; types/account.ts has it as `Account`.
      const accountId = (account as { id?: number } | null | undefined)?.id;
      if (!accountId) throw new Error('Сервер не вернул идентификатор счёта.');
      await assignSessionAccount(sessionId, accountId);
      return { accountId };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Счёт создан и привязан к выписке');
      onAttached();
    },
    onError: (e: Error) => {
      setSubmitting(false);
      toast.error(e.message || 'Не удалось создать счёт');
    },
  });

  const initialAccountType = asAccountType(accountTypeHint) ?? 'main';
  // Pre-fill name with «<Bank> <Type>» so the user can hit Enter when the
  // default is fine. The form's required-min-1 validation passes immediately.
  const typeLabelMap: Record<AccountType, string> = {
    main: 'Дебет',
    cash: 'Наличные',
    marketplace: 'Маркетплейс',
    loan: 'Кредит',
    credit_card: 'Кредитка',
    installment_card: 'Рассрочка',
    broker: 'Брокерский',
    savings: 'Вклад',
    savings_account: 'Накопительный',
    currency: 'Валютный',
  };
  const defaultName = bank
    ? `${bank.name} ${typeLabelMap[initialAccountType]}`
    : '';

  const initialValues: Partial<CreateAccountPayload> = {
    name: defaultName,
    account_type: initialAccountType,
    is_credit: initialAccountType === 'loan',
    contract_number: contractNumber ?? null,
    statement_account_number: statementAccountNumber ?? null,
  };

  return (
    <AccountDialog
      open={open}
      mode="create"
      initialValues={initialValues}
      initialBank={bank}
      isSubmitting={submitting || createAndAttachMut.isPending}
      onClose={onClose}
      onSubmit={(values) => {
        setSubmitting(true);
        createAndAttachMut.mutate(values);
      }}
    />
  );
}

'use client';

/**
 * Auto-account-recognition Шаг 3+ (2026-05-06).
 *
 * Lightweight confirmation prompt shown BEFORE the full create-account form.
 * The extractor already knows the bank and (often) the account_type, so the
 * common case is "yes, create that exact account" — one click instead of a
 * full form. Two layouts depending on how confident the extractor is:
 *
 *   • bank + type known (e.g. Yandex credit_card from §9.10 / Sber credit
 *     card from headers) — single big "Создать «<Bank> <Type>»" button.
 *   • bank known but type ambiguous (Tbank, Ozon — universal pipeline
 *     can't yet disambiguate from the PDF body) — pick from a small set
 *     of likely types: debit / credit / installment / other. The first
 *     three create immediately; "other" routes to the full form.
 *
 * Either path falls back to the full CreateAccountFromImportModal via the
 * `onCustomize` callback when the user wants to set name / balance / extra
 * fields manually.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Dialog } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { createAccount } from '@/lib/api/accounts';
import { getBanks } from '@/lib/api/banks';
import { assignSessionAccount } from '@/lib/api/imports';
import type { AccountType, CreateAccountPayload } from '@/types/account';

const TYPE_LABEL: Record<AccountType, string> = {
  main: 'Дебетовая карта',
  cash: 'Наличные',
  credit_card: 'Кредитная карта',
  installment_card: 'Карта рассрочки',
  loan: 'Кредит',
  marketplace: 'Маркетплейс',
  broker: 'Брокерский счёт',
  savings: 'Вклад',
  savings_account: 'Накопительный счёт',
  currency: 'Валютный счёт',
};

// When the extractor knows the bank but not the account type (Tbank, Ozon,
// some Sber edge-cases), we show this curated set of pickable types. Order
// reflects how common each one is in real Russian retail banking.
const PICKABLE_TYPES: AccountType[] = ['main', 'credit_card', 'installment_card'];

export function AccountTypeConfirmModal({
  open,
  sessionId,
  bankId,
  bankNameHint,
  accountTypeHint,
  contractNumber,
  statementAccountNumber,
  onClose,
  onAttached,
  onCustomize,
}: {
  open: boolean;
  sessionId: number;
  bankId: number;
  // The bank's display name from the upload payload's account_candidates or
  // a previous request — saves an extra render when we already know it. The
  // banks query below resolves it authoritatively but optimistic-renders
  // this hint immediately to avoid a flash of "?".
  bankNameHint?: string | null;
  accountTypeHint: string | null | undefined;
  contractNumber: string | null | undefined;
  statementAccountNumber: string | null | undefined;
  onClose: () => void;
  // Account created + attached. Parent should setActive(sessionId).
  onAttached: () => void;
  // User wants the full form — parent opens CreateAccountFromImportModal
  // with the same upload payload.
  onCustomize: () => void;
}) {
  const queryClient = useQueryClient();

  const banksQuery = useQuery({
    queryKey: ['banks', { supportedOnly: false }],
    queryFn: () => getBanks(undefined, { supportedOnly: false }),
    staleTime: 60_000,
  });
  const bank = (banksQuery.data ?? []).find((b) => b.id === bankId) ?? null;
  const bankName = bank?.name ?? bankNameHint ?? 'банка';

  const createMut = useMutation({
    mutationFn: async (accountType: AccountType) => {
      const payload: CreateAccountPayload = {
        name: `${bankName} ${TYPE_LABEL[accountType]}`,
        currency: 'RUB',
        balance: 0,
        is_active: true,
        account_type: accountType,
        is_credit: accountType === 'loan',
        bank_id: bankId,
        contract_number: contractNumber || null,
        statement_account_number: statementAccountNumber || null,
      };
      const account = await createAccount(payload);
      const accountId = (account as { id?: number } | null | undefined)?.id;
      if (!accountId) throw new Error('Сервер не вернул id счёта');
      await assignSessionAccount(sessionId, accountId);
      return accountId;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Счёт создан и привязан');
      onAttached();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать счёт'),
  });

  // Layout 1: extractor knows the type → one-button confirm.
  const knownType: AccountType | null =
    accountTypeHint && (accountTypeHint as AccountType) in TYPE_LABEL
      ? (accountTypeHint as AccountType)
      : null;

  if (knownType) {
    return (
      <Dialog
        open={open}
        onClose={onClose}
        title="Создать счёт?"
        description={`Из выписки видно, что это «${bankName} ${TYPE_LABEL[knownType]}».`}
      >
        <div className="space-y-2">
          <Button
            type="button"
            disabled={createMut.isPending}
            onClick={() => createMut.mutate(knownType)}
            className="w-full"
          >
            Да, создать «{bankName} {TYPE_LABEL[knownType]}»
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={createMut.isPending}
            onClick={onCustomize}
            className="w-full"
          >
            Изменить параметры
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={createMut.isPending}
            onClick={onClose}
            className="w-full"
          >
            Отмена
          </Button>
        </div>
        {(contractNumber || statementAccountNumber) && (
          <p className="mt-3 text-xs text-slate-500">
            {contractNumber ? `Договор: ${contractNumber}` : ''}
            {contractNumber && statementAccountNumber ? ' · ' : ''}
            {statementAccountNumber ? `Счёт: ${statementAccountNumber}` : ''}
          </p>
        )}
      </Dialog>
    );
  }

  // Layout 2: extractor knows the bank but not the type → small picker.
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Какой это счёт?"
      description={`Распознан банк «${bankName}», но тип счёта определить не удалось. Уточни сам:`}
    >
      <div className="space-y-2">
        {PICKABLE_TYPES.map((t) => (
          <Button
            key={t}
            type="button"
            disabled={createMut.isPending}
            onClick={() => createMut.mutate(t)}
            className="w-full"
            variant={t === 'main' ? 'primary' : 'secondary'}
          >
            {bankName} {TYPE_LABEL[t]}
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          disabled={createMut.isPending}
          onClick={onCustomize}
          className="w-full"
        >
          Другое — указать вручную
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={createMut.isPending}
          onClick={onClose}
          className="w-full"
        >
          Отмена
        </Button>
      </div>
      {(contractNumber || statementAccountNumber) && (
        <p className="mt-3 text-xs text-slate-500">
          {contractNumber ? `Договор: ${contractNumber}` : ''}
          {contractNumber && statementAccountNumber ? ' · ' : ''}
          {statementAccountNumber ? `Счёт: ${statementAccountNumber}` : ''}
        </p>
      )}
    </Dialog>
  );
}

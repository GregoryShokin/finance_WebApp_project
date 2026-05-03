/**
 * OrphanTransferHint — banner shown for rows the matcher classified as
 * orphan transfer but where committed-history says "you've done this many
 * times before, target was X" (spec §5.2 v1.20).
 *
 * Three actions:
 *   • «Подтвердить»  — accept the suggestion, set target_account_id and
 *     stamp confirm. Backend creates the transfer pair (with mirror tx
 *     on the suggested account, even if it's closed).
 *   • «Изменить счёт» — open the account dropdown for manual choice.
 *   • «Это не перевод» — demote to regular (clear hint, set was_orphan_transfer).
 */
'use client';

import { Repeat } from 'lucide-react';

export type OrphanHint = {
  suggestedTargetAccountId: number;
  suggestedTargetAccountName: string;
  suggestedTargetIsClosed: boolean;
  suggestedReason: string;  // e.g. "transfer-history 12/12"
};

export function OrphanTransferHint({
  hint,
  onConfirm,
  onPickManually,
  onReject,
  isPending,
}: {
  hint: OrphanHint;
  onConfirm: () => void;
  onPickManually?: () => void;
  onReject: () => void;
  isPending?: boolean;
}) {
  const closedSuffix = hint.suggestedTargetIsClosed ? ' (закрыт)' : '';
  // Parse "transfer-history N/M" → render "N из M прошлых случаев".
  const m = /^transfer-history (\d+)\/(\d+)$/.exec(hint.suggestedReason);
  const reasonText = m
    ? `${m[1]} из ${m[2]} прошлых случаев`
    : hint.suggestedReason;

  return (
    <div className="mt-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-[13px]">
      <div className="flex items-start gap-2">
        <Repeat className="mt-0.5 size-4 shrink-0 text-blue-600" />
        <div className="min-w-0 flex-1">
          <p className="text-blue-900">
            По истории — это перевод с/на{' '}
            <span className="font-semibold">«{hint.suggestedTargetAccountName}{closedSuffix}»</span>
          </p>
          <p className="mt-0.5 text-xs text-blue-700">{reasonText}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={isPending}
              onClick={onConfirm}
              className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              ✓ Подтвердить
            </button>
            {onPickManually ? (
              <button
                type="button"
                disabled={isPending}
                onClick={onPickManually}
                className="rounded-md border border-blue-300 bg-white px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-60"
              >
                Изменить счёт
              </button>
            ) : null}
            <button
              type="button"
              disabled={isPending}
              onClick={onReject}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              Это не перевод
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

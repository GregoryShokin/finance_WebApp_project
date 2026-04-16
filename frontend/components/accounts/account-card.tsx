"use client";

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CreditCard, Pencil, RotateCcw, SlidersHorizontal, Trash2, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { adjustAccountBalance } from '@/lib/api/accounts';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import type { Account } from '@/types/account';
import type { Transaction } from '@/types/transaction';

function CreditCardLimitBar({ account }: { account: Account }) {
  const limit = Number(account.credit_limit_original ?? 0);
  if (limit <= 0) return null;

  const isInstallment = account.account_type === 'installment_card';
  const used = isInstallment
    ? Math.abs(Number(account.credit_current_amount ?? 0))
    : Math.max(0, limit - Number(account.balance));
  const pct = Math.min(100, (used / limit) * 100);

  const barColor = pct > 80 ? 'bg-rose-500' : pct > 50 ? 'bg-amber-400' : 'bg-emerald-500';
  const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

  return (
    <div className="mt-4">
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>Использовано лимита</span>
        <span>{fmt(used)} из {fmt(limit)} ₽</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function AccountCard({
  account,
  onEdit,
  onDelete,
  onCancelDelete,
  isDeletePending,
  isDeleting,
  transactions,
}: {
  account: Account;
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  onCancelDelete: (accountId: number) => void;
  isDeletePending?: boolean;
  isDeleting?: boolean;
  transactions?: Transaction[];
}) {
  const numericBalance = Number(account.balance);
  const isCreditCard = account.account_type === 'credit_card';
  const isInstallmentCard = account.account_type === 'installment_card';
  const [showCalc, setShowCalc] = useState(false);
  const [showAdjust, setShowAdjust] = useState(false);
  const [adjustValue, setAdjustValue] = useState('');
  const [adjustComment, setAdjustComment] = useState('');
  const queryClient = useQueryClient();

  const adjustMutation = useMutation({
    mutationFn: () => adjustAccountBalance(account.id, parseFloat(adjustValue), adjustComment || undefined),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      await queryClient.invalidateQueries({ queryKey: ['transactions'] });
      setShowAdjust(false);
      setAdjustValue('');
      setAdjustComment('');
      toast.success('Баланс скорректирован');
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось скорректировать баланс'),
  });

  return (
    <>
    <Card className="p-5 lg:p-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
              {account.is_credit || isCreditCard ? <CreditCard className="size-5" /> : <Wallet className="size-5" />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-lg font-semibold text-slate-950">{account.name}</h3>
                <StatusBadge tone={account.is_active ? 'success' : 'neutral'}>
                  {account.is_active ? 'Активный' : 'Неактивный'}
                </StatusBadge>
                {isCreditCard ? <StatusBadge tone="warning">Кредитная карта</StatusBadge> : null}
                {account.is_credit && !isCreditCard ? <StatusBadge tone="warning">Кредит</StatusBadge> : null}
              </div>
              <p className="mt-1 text-sm text-slate-500">Валюта счёта: {account.currency}</p>
            </div>
          </div>

          <div className="surface-muted mt-5 p-4">
            <p className="text-sm text-slate-500">
              {isCreditCard ? 'Доступный остаток' : account.is_credit ? 'Текущий долг' : 'Текущий баланс'}
            </p>
            <MoneyAmount
              value={account.is_credit && !isCreditCard ? Math.abs(numericBalance) : numericBalance}
              currency={account.currency}
              tone={account.is_credit && !isCreditCard ? 'expense' : numericBalance < 0 ? 'expense' : 'default'}
              className="mt-1 block text-2xl lg:text-3xl"
            />
            {(isCreditCard || isInstallmentCard) ? <CreditCardLimitBar account={account} /> : null}
          </div>

          {account.is_credit && !isCreditCard ? (
            <>
              <div className="mt-4 grid gap-3 text-sm text-slate-600 sm:grid-cols-3">
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                  <div className="text-xs text-slate-500">Изначальная сумма</div>
                  <div className="mt-1 font-medium text-slate-900">
                    {Number(account.credit_limit_original ?? 0).toLocaleString('ru-RU')}
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                  <div className="text-xs text-slate-500">Ставка</div>
                  <div className="mt-1 font-medium text-slate-900">
                    {Number(account.credit_interest_rate ?? 0).toLocaleString('ru-RU')}%
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                  <div className="text-xs text-slate-500">Осталось</div>
                  <div className="mt-1 font-medium text-slate-900">
                    {Number(account.credit_term_remaining ?? 0).toLocaleString('ru-RU')} мес.
                  </div>
                </div>
              </div>

              {(() => {
                const original = Number(account.credit_limit_original ?? 0);
                const current = Math.abs(Number(account.credit_current_amount ?? account.balance ?? 0));
                if (original <= 0) return null;
                const paid = Math.max(0, original - current);
                const paidPct = Math.min(100, (paid / original) * 100);
                const barColor = paidPct >= 75 ? 'bg-emerald-500' : paidPct >= 40 ? 'bg-amber-400' : 'bg-rose-400';
                return (
                  <div className="mt-4">
                    <div className="mb-1 flex justify-between text-xs text-slate-500">
                      <span>Погашено</span>
                      <span>
                        {Math.round(paidPct)}% · {Math.round(paid).toLocaleString('ru-RU')} из{' '}
                        {Math.round(original).toLocaleString('ru-RU')} ₽
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                      <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${paidPct}%` }} />
                    </div>
                  </div>
                );
              })()}

              {(() => {
                const principal = Math.abs(Number(account.credit_current_amount ?? account.balance ?? 0));
                const rate = Number(account.credit_interest_rate ?? 0);
                const termMonths = Number(account.credit_term_remaining ?? 0);
                const monthlyPayment = Number(account.monthly_payment ?? 0);

                const lastPaymentFromTx = (() => {
                  const txList = transactions ?? [];
                  const creditPayments = txList
                    .filter((tx) => {
                      if (tx.operation_type !== 'credit_payment') return false;
                      const creditId = tx.credit_account_id ?? tx.target_account_id;
                      return creditId === account.id;
                    })
                    .sort(
                      (a, b) =>
                        new Date(b.transaction_date).getTime() -
                        new Date(a.transaction_date).getTime(),
                    );

                  return creditPayments[0] ? Number(creditPayments[0].amount) : 0;
                })();

                const paymentSource: 'transactions' | 'manual' | 'none' =
                  lastPaymentFromTx > 0 ? 'transactions' : monthlyPayment > 0 ? 'manual' : 'none';
                const payment = lastPaymentFromTx > 0 ? lastPaymentFromTx : monthlyPayment;

                const realOverpay = (() => {
                  const txList = transactions ?? [];
                  return txList
                    .filter((tx) => {
                      if (tx.operation_type !== 'credit_payment') return false;
                      const creditId = tx.credit_account_id ?? tx.target_account_id;
                      return creditId === account.id;
                    })
                    .reduce((sum, tx) => sum + Number(tx.credit_interest_amount ?? 0), 0);
                })();

                const hasOverpayData = realOverpay > 0;
                const overpayPct = principal > 0 ? (realOverpay / principal) * 100 : 0;

                const totalPrincipalPaid = (() => {
                  const txList = transactions ?? [];
                  return txList
                    .filter((tx) => {
                      if (tx.operation_type !== 'credit_payment') return false;
                      const creditId = tx.credit_account_id ?? tx.target_account_id;
                      return creditId === account.id;
                    })
                    .reduce((sum, tx) => sum + Number(tx.credit_principal_amount ?? 0), 0);
                })();

                const closeDate = (() => {
                  if (termMonths <= 0) return null;
                  const d = new Date();
                  d.setMonth(d.getMonth() + termMonths);
                  return d.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });
                })();

                return (
                  <div className="mt-4 border-t border-slate-100 pt-4">
                    <button
                      type="button"
                      onClick={() => setShowCalc((v) => !v)}
                      className="flex w-full items-center justify-between text-xs font-medium text-slate-500 transition hover:text-slate-800"
                    >
                      <span>Калькулятор переплаты</span>
                      <span>{showCalc ? '↑ Скрыть' : '↓ Показать'}</span>
                    </button>

                    {showCalc ? (
                      <div className="mt-3 space-y-3">
                        {paymentSource === 'none' ? (
                          <p className="text-xs text-slate-400">
                            Внеси первый платёж по кредиту через раздел Транзакции —
                            тип операции «Кредитная операция: платёж по кредиту».
                            После этого калькулятор покажет реальные цифры.
                          </p>
                        ) : (
                          <>
                            <div className="grid grid-cols-3 gap-2">
                              <div className="rounded-xl bg-slate-50 px-3 py-2">
                                <p className="text-xs text-slate-400">Платёж/мес</p>
                                <p className="mt-1 text-sm font-semibold text-slate-900">
                                  {Math.round(payment).toLocaleString('ru-RU')} ₽
                                </p>
                                <p className="text-[10px] text-slate-400">
                                  {paymentSource === 'transactions'
                                    ? 'последний платёж из транзакций'
                                    : paymentSource === 'manual'
                                      ? 'введено вручную'
                                      : ''}
                                </p>
                              </div>
                              <div className="rounded-xl bg-rose-50 px-3 py-2">
                                <p className="text-xs text-slate-400">Переплата (факт)</p>
                                {hasOverpayData ? (
                                  <>
                                    <p className="mt-1 text-sm font-semibold text-rose-600">
                                      {Math.round(realOverpay).toLocaleString('ru-RU')} ₽
                                    </p>
                                    <p className="text-[10px] text-slate-400">
                                      {overpayPct.toFixed(0)}% от суммы долга
                                    </p>
                                  </>
                                ) : (
                                  <p className="mt-1 text-sm text-slate-400">нет данных</p>
                                )}
                              </div>
                              <div className="rounded-xl bg-slate-50 px-3 py-2">
                                <p className="text-xs text-slate-400">Закроется</p>
                                <p className="mt-1 text-sm font-semibold text-slate-900">{closeDate ?? '—'}</p>
                              </div>
                            </div>

                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                );
              })()}
            </>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <Button type="button" variant="secondary" size="icon" onClick={() => { setAdjustValue(String(numericBalance)); setShowAdjust(true); }} aria-label="Скорректировать баланс" title="Скорректировать баланс">
            <SlidersHorizontal className="size-4" />
          </Button>
          <Button type="button" variant="secondary" size="icon" onClick={() => onEdit(account)} aria-label="Изменить счёт" title="Изменить">
            <Pencil className="size-4" />
          </Button>
          {isDeletePending ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => onCancelDelete(account.id)}
              disabled={isDeleting}
              aria-label={isDeleting ? 'Счёт удаляется' : 'Отменить удаление счёта'}
              title={isDeleting ? 'Удаляем...' : 'Отменить удаление'}
            >
              <RotateCcw className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              variant="danger"
              size="icon"
              onClick={() => onDelete(account)}
              disabled={isDeleting}
              aria-label={isDeleting ? 'Удаляем счёт' : 'Удалить счёт'}
              title={isDeleting ? 'Удаляем...' : 'Удалить'}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </Card>

    <Dialog
      open={showAdjust}
      onClose={() => setShowAdjust(false)}
      title="Корректировка баланса"
      description={`Текущий баланс: ${numericBalance.toLocaleString('ru-RU')} ${account.currency}. Введи новый баланс — разница запишется как транзакция-корректировка.`}
    >
      <div className="space-y-4">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">Новый баланс ({account.currency})</label>
          <input
            type="number"
            step="0.01"
            value={adjustValue}
            onChange={(e) => setAdjustValue(e.target.value)}
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            placeholder="0.00"
            autoFocus
          />
          {adjustValue !== '' && !isNaN(parseFloat(adjustValue)) && parseFloat(adjustValue) !== numericBalance && (
            <p className="mt-1.5 text-xs text-slate-500">
              Дельта: <span className={parseFloat(adjustValue) > numericBalance ? 'text-emerald-600 font-medium' : 'text-rose-600 font-medium'}>
                {parseFloat(adjustValue) > numericBalance ? '+' : ''}{(parseFloat(adjustValue) - numericBalance).toLocaleString('ru-RU', { minimumFractionDigits: 2 })} {account.currency}
              </span>
            </p>
          )}
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-slate-700">Комментарий (необязательно)</label>
          <input
            type="text"
            value={adjustComment}
            onChange={(e) => setAdjustComment(e.target.value)}
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            placeholder="Начальный баланс при настройке"
            maxLength={255}
          />
        </div>
        <div className="flex gap-3 pt-1">
          <Button
            type="button"
            variant="secondary"
            className="flex-1"
            onClick={() => setShowAdjust(false)}
          >
            Отмена
          </Button>
          <Button
            type="button"
            className="flex-1"
            disabled={adjustMutation.isPending || adjustValue === '' || isNaN(parseFloat(adjustValue)) || parseFloat(adjustValue) === numericBalance}
            onClick={() => adjustMutation.mutate()}
          >
            {adjustMutation.isPending ? 'Сохраняем...' : 'Применить'}
          </Button>
        </div>
      </div>
    </Dialog>
    </>
  );
}

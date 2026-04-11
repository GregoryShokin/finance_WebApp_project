'use client';

import { useMemo } from 'react';
import { CreditCard, TrendingUp, Wallet } from 'lucide-react';

import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { Account } from '@/types/account';

type Props = {
  accounts: Account[];
  isLoading?: boolean;
};

function AccountIcon({ accountType }: { accountType: Account['account_type'] }) {
  if (accountType === 'broker') {
    return <TrendingUp className="size-3.5 text-slate-400" />;
  }
  if (accountType === 'cash') {
    return <Wallet className="size-3.5 text-slate-400" />;
  }
  return <CreditCard className="size-3.5 text-slate-400" />;
}

function isCreditCard(account: Account): boolean {
  return account.account_type === 'credit_card';
}

function pluralAccounts(n: number): string {
  if (n === 1) return 'счёт';
  if (n >= 2 && n <= 4) return 'счёта';
  return 'счетов';
}

export function AvailableFinancesWidget({ accounts, isLoading = false }: Props) {
  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'available-finances-widget', expandHeight: 400 });

  // Только дебетовые (regular, cash) — реальные деньги, без вкладов и кредитов
  const debitAccounts = useMemo(
    () => accounts.filter(
      (a) => a.account_type === 'regular' || a.account_type === 'cash',
    ),
    [accounts],
  );

  // Кредитные карты
  const creditCardAccounts = useMemo(
    () => accounts.filter(isCreditCard),
    [accounts],
  );

  // Все релевантные счета для этого виджета
  const allRelevantAccounts = useMemo(
    () => [...debitAccounts, ...creditCardAccounts],
    [debitAccounts, creditCardAccounts],
  );

  // Основная цифра — только реальные деньги (дебет)
  const realMoneyTotal = useMemo(
    () => debitAccounts.reduce((sum, a) => sum + Math.max(0, Number(a.balance)), 0),
    [debitAccounts],
  );

  // Доступный кредитный резерв
  const creditAvailableTotal = useMemo(
    () => creditCardAccounts.reduce((sum, a) => sum + Math.max(0, Number(a.balance)), 0),
    [creditCardAccounts],
  );

  // Итого с учётом кредитных лимитов
  const totalWithCredit = realMoneyTotal + creditAvailableTotal;

  // Счета с балансом >= 1000 — показываем по отдельности
  const visibleAccounts = useMemo(
    () => allRelevantAccounts.filter((a) => Math.max(0, Number(a.balance)) >= 1000),
    [allRelevantAccounts],
  );

  // Счета с балансом < 1000 — сворачиваем в одну строку
  const hiddenAccounts = useMemo(
    () => allRelevantAccounts.filter((a) => Math.max(0, Number(a.balance)) < 1000),
    [allRelevantAccounts],
  );

  const hiddenTotal = useMemo(
    () => hiddenAccounts.reduce((sum, a) => sum + Math.max(0, Number(a.balance)), 0),
    [hiddenAccounts],
  );

  const totalAccountCount = allRelevantAccounts.length;

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Доступные финансы</p>
          <div className="mt-3 space-y-2">
            <div className="h-9 w-28 animate-pulse rounded bg-slate-100" />
            <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
            <div className="h-4 w-16 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Доступные финансы</p>

        {toggleButton}

        <div className="mt-3">
          {/* Основная цифра — только реальные деньги */}
          <MoneyAmount
            value={realMoneyTotal}
            tone={realMoneyTotal >= 0 ? 'income' : 'expense'}
            className="text-2xl lg:text-3xl"
          />
          <p className="mt-1 text-sm text-slate-500">реальные деньги</p>

          {/* Дополнительная строка — с учётом кредитных лимитов */}
          {creditAvailableTotal > 0 && (
            <p className="mt-1.5 text-xs text-slate-400">
              с кредитными лимитами:{' '}
              <span className="font-medium text-slate-600">{formatMoney(totalWithCredit)}</span>
            </p>
          )}

          <p className="mt-2 text-xs font-medium uppercase tracking-wide text-slate-400">
            {totalAccountCount} {pluralAccounts(totalAccountCount)}
          </p>
        </div>

        {isExpanded ? (
          <div className="mt-3 space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Счета
            </p>
            {visibleAccounts.length === 0 && hiddenAccounts.length === 0 ? (
              <p className="text-xs text-slate-400">Нет счетов для отображения</p>
            ) : (
              <>
                {visibleAccounts.map((account) => {
                  const creditLimit = account.credit_limit ?? account.credit_limit_original;
                  const cardLike = isCreditCard(account);
                  return (
                    <div
                      key={account.id}
                      className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <div className="flex size-7 items-center justify-center rounded-full border border-slate-100 bg-white">
                          <AccountIcon accountType={account.account_type} />
                        </div>
                        <p className="text-sm font-medium text-slate-900">{account.name}</p>
                      </div>
                      {cardLike ? (
                        <div className="text-right">
                          <p className="text-sm font-medium text-slate-900">
                            {formatMoney(Math.max(0, Number(account.balance)))}
                          </p>
                          {creditLimit ? (
                            <p className="text-[11px] text-slate-400">
                              лимит {formatMoney(Number(creditLimit))}
                            </p>
                          ) : null}
                        </div>
                      ) : (
                        <MoneyAmount
                          value={Math.max(0, Number(account.balance))}
                          tone="income"
                          className="text-sm font-medium"
                        />
                      )}
                    </div>
                  );
                })}

                {hiddenAccounts.length > 0 && (
                  <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                    <p className="text-sm text-slate-500">
                      Остальные счета ({hiddenAccounts.length})
                    </p>
                    <MoneyAmount
                      value={hiddenTotal}
                      tone="income"
                      className="text-sm font-medium"
                    />
                  </div>
                )}
              </>
            )}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative h-full overflow-visible"
      style={wrapperStyle}
    >
      {backdrop}
      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5" style={cardStyle}>
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, CreditCard, TrendingUp, Wallet } from 'lucide-react';

import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { formatMoney } from '@/lib/utils/format';
import { resolveExpandUp } from '@/lib/utils/widget-expand';
import type { Account } from '@/types/account';

const SCALE = 1.8;

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

function isLoan(account: Account): boolean {
  return account.account_type === 'credit';
}

export function AvailableFinancesWidget({ accounts, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const [expandUp, setExpandUp] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, accounts, isLoading]);

  useEffect(() => {
    if (!isExpanded) return;

    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    }

    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  const debitAccounts = useMemo(
    () => accounts.filter(
      (account) =>
        !isCreditCard(account) &&
        !isLoan(account) &&
        account.account_type !== 'deposit' &&
        account.account_type !== 'broker' &&
        account.account_type !== 'installment_card',
    ),
    [accounts],
  );

  const creditCardAccounts = useMemo(
    () => accounts.filter((account) => isCreditCard(account)),
    [accounts],
  );

  const installmentCardAccounts = useMemo(
    () => accounts.filter((account) => account.account_type === 'installment_card'),
    [accounts],
  );

  const visibleDebitAccounts = useMemo(
    () => debitAccounts.filter((account) => Math.max(0, Number(account.balance)) >= 1000),
    [debitAccounts],
  );

  const visibleAccounts = useMemo(
    () => [...visibleDebitAccounts, ...creditCardAccounts, ...installmentCardAccounts],
    [creditCardAccounts, installmentCardAccounts, visibleDebitAccounts],
  );

  const debitTotal = useMemo(
    () => debitAccounts.reduce((sum, account) => sum + Math.max(0, Number(account.balance)), 0),
    [debitAccounts],
  );

  const creditCardLimitTotal = useMemo(
    () => creditCardAccounts.reduce((sum, account) => {
      const limit = Number(account.credit_limit ?? account.credit_limit_original ?? 0);
      return sum + Math.max(0, limit);
    }, 0),
    [creditCardAccounts],
  );

  const installmentCardLimitTotal = useMemo(
    () => installmentCardAccounts.reduce((sum, account) => {
      const limit = Number(account.credit_limit ?? account.credit_limit_original ?? 0);
      return sum + Math.max(0, limit);
    }, 0),
    [installmentCardAccounts],
  );

  const totalAvailable = debitTotal;

  function handleToggle(next?: boolean) {
    if ((!isExpanded || next === true) && cardRef.current) {
      setExpandUp(resolveExpandUp(cardRef.current, 400));
    }
    setIsExpanded((value) => next ?? !value);
  }

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
        <p className="text-sm font-semibold text-slate-900">Доступные средства</p>

        <button
          type="button"
          onClick={() => handleToggle()}
          className="absolute right-3 top-3 flex size-[24px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
          aria-label="Подробнее"
          aria-expanded={isExpanded}
        >
          <ChevronDown className={`size-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
        </button>

        <div className="mt-1">
          <MoneyAmount
            value={totalAvailable}
            tone={totalAvailable >= 0 ? 'income' : 'expense'}
            className="text-2xl font-extrabold lg:text-3xl"
          />
        </div>
        <div className="mt-3 space-y-1.5">
          {creditCardLimitTotal > 0 ? (
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500">Кредитный лимит</span>
              <span className="font-semibold text-slate-700">{formatMoney(creditCardLimitTotal)}</span>
            </div>
          ) : null}
          {installmentCardLimitTotal > 0 ? (
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500">Лимит рассрочки</span>
              <span className="font-semibold text-slate-700">{formatMoney(installmentCardLimitTotal)}</span>
            </div>
          ) : null}
        </div>

        {isExpanded ? (
          <div className="mt-3 space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Доступные счета
            </p>
            {visibleAccounts.length === 0 ? (
              <p className="text-xs text-slate-400">Нет счетов для отображения</p>
            ) : (
              visibleAccounts.map((account) => {
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
                      <div>
                        <p className="text-sm font-medium text-slate-900">{account.name}</p>
                      </div>
                    </div>
                    {cardLike ? (
                      <div className="text-right">
                        <p className="text-sm font-medium text-slate-900">
                          {formatMoney(Math.abs(Number(account.balance)))}
                        </p>
                        {creditLimit ? (
                          <p className="text-[11px] text-slate-400">
                            лимит {formatMoney(Number(creditLimit))}
                          </p>
                        ) : null}
                      </div>
                    ) : (
                      <MoneyAmount
                        value={Math.abs(Number(account.balance))}
                        tone="income"
                        className="text-sm font-medium"
                      />
                    )}
                  </div>
                );
              })
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
      style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}
    >
      {isExpanded ? (
        <button
          type="button"
          aria-label="Закрыть"
          onClick={() => handleToggle(false)}
          className="fixed inset-0 z-40 bg-black/10"
        />
      ) : null}

      <div ref={cardRef}>
        <Card
          className="relative overflow-visible p-5"
          style={{
            position: isExpanded ? 'absolute' : 'relative',
            top: isExpanded && !expandUp ? 0 : 'auto',
            bottom: isExpanded && expandUp ? 0 : 'auto',
            left: 0,
            right: 0,
            transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
            transformOrigin: expandUp ? 'center bottom' : 'center center',
            transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
            zIndex: isExpanded ? 50 : 1,
            overflow: 'visible',
          }}
        >
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}

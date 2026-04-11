'use client';

import { useMemo } from 'react';
import { CarFront, Home, Package } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { Account } from '@/types/account';
import type { FinancialHealth } from '@/types/financial-health';
import type { RealAsset } from '@/types/real-asset';

type Props = {
  accounts: Account[];
  realAssets: RealAsset[];
  health: FinancialHealth;
  isLoading?: boolean;
};

function toNumber(value: number | string | null | undefined) {
  return Number(value ?? 0);
}

function getAssetLabel(type: RealAsset['asset_type']) {
  if (type === 'real_estate') return 'Недвижимость';
  if (type === 'car') return 'Авто';
  return 'Прочее';
}

function AssetIcon({ type }: { type: RealAsset['asset_type'] }) {
  if (type === 'real_estate') return <Home className="size-4 text-slate-400" />;
  if (type === 'car') return <CarFront className="size-4 text-slate-400" />;
  return <Package className="size-4 text-slate-400" />;
}

export function CapitalWidget({ accounts, realAssets, health, isLoading = false }: Props) {
  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'capital-widget', expandHeight: 450 });

  const metrics = useMemo(() => {
    const liquidAccounts = accounts.filter(
      (account) =>
        account.account_type !== 'credit' &&
        account.account_type !== 'credit_card' &&
        account.account_type !== 'installment_card' &&
        account.account_type !== 'broker' &&
        account.account_type !== 'deposit',
    );
    const depositAccounts = accounts.filter((account) => account.account_type === 'deposit');
    const brokerAccounts = accounts.filter((account) => account.account_type === 'broker');

    const liquidTotal = liquidAccounts.reduce((sum, account) => sum + Math.max(0, toNumber(account.balance)), 0);
    const depositTotal = depositAccounts.reduce((sum, account) => sum + Math.max(0, toNumber(account.balance)), 0);
    const realAssetsTotal = realAssets.reduce((sum, asset) => sum + Math.max(0, toNumber(asset.estimated_value)), 0);
    const brokerTotal = brokerAccounts.reduce((sum, account) => sum + Math.max(0, toNumber(account.balance)), 0);
    const totalAssets = liquidTotal + depositTotal + realAssetsTotal + brokerTotal;
    const netCapital = health.leverage_own_capital - health.leverage_total_debt;

    return {
      liquidTotal,
      depositTotal,
      realAssetsTotal,
      brokerTotal,
      totalAssets,
      netCapital,
    };
  }, [accounts, realAssets, health]);

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-medium text-slate-500">Капитал</p>
          <div className="mt-4 space-y-2">
            <div className="h-9 w-40 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-28 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-sm font-medium text-slate-500">Капитал</p>
        {toggleButton}

        {!isExpanded ? (
          <div className="mt-4">
            <p className={cn('text-2xl font-semibold lg:text-3xl', metrics.netCapital >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
              {formatMoney(metrics.netCapital)}
            </p>
            <p className="mt-2 text-sm text-slate-500">чистый капитал</p>
            <div className="mt-4 space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Активы</span>
                <span className="font-medium text-slate-700">{formatMoney(metrics.totalAssets)}</span>
              </div>
              {metrics.depositTotal > 0 ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Вклады</span>
                  <span className="font-medium text-emerald-600">{formatMoney(metrics.depositTotal)}</span>
                </div>
              ) : null}
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Долги</span>
                <span className="font-medium text-rose-600">{formatMoney(health.leverage_total_debt)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Инвестиции</span>
                <span className="font-medium text-slate-400">
                  {metrics.brokerTotal === 0 ? 'нет данных' : formatMoney(metrics.brokerTotal)}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Активы</p>
              <div className="mt-3 space-y-3 rounded-2xl bg-slate-50 px-4 py-4">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-600">Ликвидные средства</span>
                  <span className="font-medium text-slate-900">{formatMoney(metrics.liquidTotal)}</span>
                </div>
                {metrics.depositTotal > 0 ? (
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-slate-600">Вклады</span>
                    <span className="font-medium text-emerald-600">{formatMoney(metrics.depositTotal)}</span>
                  </div>
                ) : null}
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-600">Реальные активы</span>
                  <span className="font-medium text-slate-900">{formatMoney(metrics.realAssetsTotal)}</span>
                </div>
                {realAssets.length > 0 ? (
                  <div className="space-y-2 border-t border-slate-200 pt-3">
                    {realAssets.map((asset) => (
                      <div key={asset.id} className="flex items-center justify-between gap-3 text-sm">
                        <div className="flex min-w-0 items-center gap-2">
                          <AssetIcon type={asset.asset_type} />
                          <div className="min-w-0">
                            <p className="truncate text-slate-900">{asset.name}</p>
                            <p className="text-xs text-slate-400">{getAssetLabel(asset.asset_type)}</p>
                          </div>
                        </div>
                        <span className="shrink-0 font-medium text-slate-900">{formatMoney(toNumber(asset.estimated_value))}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-600">Инвестиции</span>
                  {metrics.brokerTotal > 0 ? (
                    <span className="font-medium text-slate-900">{formatMoney(metrics.brokerTotal)}</span>
                  ) : (
                    <span className="text-slate-400">Появится после добавления инвестиционного счёта</span>
                  )}
                </div>
              </div>
            </div>

            <hr className="border-slate-100" />

            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Пассивы</p>
              <div className="mt-3 rounded-2xl bg-rose-50 px-4 py-4">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-rose-700">Кредиты и займы</span>
                  <span className="font-medium text-rose-600">{formatMoney(health.leverage_total_debt)}</span>
                </div>
              </div>
            </div>

            <hr className="border-slate-100" />

            <div className="rounded-2xl bg-slate-50 px-4 py-4">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Чистый капитал</p>
              <p className={cn('mt-2 text-2xl font-semibold', metrics.netCapital >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                {formatMoney(metrics.netCapital)}
              </p>
            </div>
          </div>
        )}
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

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { CarFront, Home, Info, Landmark, Package } from 'lucide-react';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { resolveExpandUp } from '@/lib/utils/widget-expand';
import type { Account } from '@/types/account';
import type { FinancialHealth } from '@/types/financial-health';
import type { RealAsset } from '@/types/real-asset';

const SCALE = 1.8;

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
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const [expandUp, setExpandUp] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, accounts, realAssets, health, isLoading]);

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

  useEffect(() => {
    function handleExternalToggle(event: Event) {
      const customEvent = event as CustomEvent<{ source?: string; open?: boolean }>;
      if (customEvent.detail?.source !== 'capital-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

  const metrics = useMemo(() => {
    const liquidAccounts = accounts.filter(
      (account) =>
        account.account_type !== 'credit' &&
        account.account_type !== 'credit_card' &&
        account.account_type !== 'broker',
    );
    const brokerAccounts = accounts.filter((account) => account.account_type === 'broker');

    const liquidTotal = liquidAccounts.reduce((sum, account) => sum + Math.max(0, toNumber(account.balance)), 0);
    const realAssetsTotal = realAssets.reduce((sum, asset) => sum + Math.max(0, toNumber(asset.estimated_value)), 0);
    const brokerTotal = brokerAccounts.reduce((sum, account) => sum + Math.max(0, toNumber(account.balance)), 0);
    const totalAssets = liquidTotal + realAssetsTotal + brokerTotal;
    const netCapital = health.leverage_own_capital - health.leverage_total_debt;

    return {
      liquidTotal,
      realAssetsTotal,
      brokerTotal,
      totalAssets,
      netCapital,
    };
  }, [accounts, realAssets, health]);

  function handleToggle() {
    if (!isExpanded && cardRef.current) {
      setExpandUp(resolveExpandUp(cardRef.current, 450));
    }
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'capital-widget', open: next },
        }),
      );
      return next;
    });
  }

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
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <p className="text-sm font-medium text-slate-500">Капитал</p>
          </div>
          <button
            type="button"
            onClick={handleToggle}
            className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
            aria-label="Подробнее"
            aria-expanded={isExpanded}
          >
            <Info className="size-3.5" />
          </button>
        </div>

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
          <>
            <div className="mt-5 space-y-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Активы</p>
                <div className="mt-3 space-y-3 rounded-2xl bg-slate-50 px-4 py-4">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-slate-600">Ликвидные средства</span>
                    <span className="font-medium text-slate-900">{formatMoney(metrics.liquidTotal)}</span>
                  </div>
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
          </>
        )}
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
          onClick={handleToggle}
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

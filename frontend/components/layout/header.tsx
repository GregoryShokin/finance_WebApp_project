"use client";

import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Menu } from 'lucide-react';

import type { User } from '@/types/auth';

const ROUTE_TITLE: Record<string, string> = {
  '/dashboard': 'Дашборд',
  '/health': 'Финансовое здоровье',
  '/transactions': 'Транзакции',
  '/planning': 'План',
  '/goals': 'Цели',
  '/import': 'Импорт выписок',
  '/parked-queue': 'Недоразобранное',
  '/categories': 'Категории',
  '/rules': 'Правила',
  '/accounts': 'Активы',
  '/bank-connections': 'Банковские подключения',
  '/settings': 'Настройки',
  '/review': 'Ревью',
};

function titleFromPath(pathname: string): string {
  const exact = ROUTE_TITLE[pathname];
  if (exact) return exact;
  // Fallback: take first segment, prettify
  const seg = pathname.split('/').filter(Boolean)[0] ?? '';
  return seg ? seg.charAt(0).toUpperCase() + seg.slice(1) : 'FinanceApp';
}

function sectionFromPath(pathname: string): string {
  const seg = pathname.split('/').filter(Boolean)[0] ?? '';
  if (!seg) return 'Личный кабинет';
  return ROUTE_TITLE[`/${seg}`] ?? seg;
}

export function Header({
  user: _user,
  title,
  subtitle,
  actions,
  onMobileMenuToggle,
}: {
  user: User | null;
  /** Page title override; falls back to route mapping. */
  title?: string;
  /** Optional subtitle line under the title (e.g. statement metadata). */
  subtitle?: ReactNode;
  /** Right-side action slot (chips, buttons specific to a page). */
  actions?: ReactNode;
  /** Toggle for the mobile sidebar drawer (rendered only on <lg). */
  onMobileMenuToggle?: () => void;
}) {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const todayLabel = useMemo(
    () =>
      new Intl.DateTimeFormat('ru-RU', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
      }).format(new Date()),
    [],
  );

  const resolvedTitle = title ?? titleFromPath(pathname ?? '');
  const section = sectionFromPath(pathname ?? '');

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur">
      <div className="flex w-full items-center justify-between gap-4 px-6 py-3.5 lg:px-7">
        <div className="flex min-w-0 items-center gap-3">
          {/* Hamburger only on <lg — when sidebar is hidden. Skipped if no
              handler is provided (Header is reused on screens without Sidebar). */}
          {onMobileMenuToggle ? (
            <button
              type="button"
              onClick={onMobileMenuToggle}
              aria-label="Открыть меню"
              className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-bg-surface text-ink-2 hover:bg-ink/5 lg:hidden"
            >
              <Menu className="size-4" />
            </button>
          ) : null}
          <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-3">
            Личный кабинет · {section}
          </div>
          <h1 className="mt-0.5 truncate text-base font-semibold text-ink">{resolvedTitle}</h1>
          {subtitle ? (
            <div className="mt-1 text-xs text-ink-3">{subtitle}</div>
          ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {actions}
          <span className="hidden rounded-pill border border-line bg-bg-surface px-2.5 py-1 text-[11px] font-medium capitalize text-ink-2 md:inline">
            {mounted ? todayLabel : ''}
          </span>
        </div>
      </div>
    </header>
  );
}

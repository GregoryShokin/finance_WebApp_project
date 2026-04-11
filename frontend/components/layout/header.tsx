"use client";

import { CalendarDays, LogOut, Settings, ShieldCheck } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { removeAccessToken } from '@/lib/auth/token';
import type { User } from '@/types/auth';

export function Header({ user }: { user: User | null }) {
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const todayLabel = useMemo(
    () =>
      new Intl.DateTimeFormat('ru-RU', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
      }).format(new Date()),
    [],
  );

  function handleLogout() {
    removeAccessToken();
    router.replace('/login');
  }

  function handleSettings() {
    router.push('/settings');
  }

  return (
    <header className="sticky top-0 z-20 border-b border-white/60 bg-white/75 backdrop-blur">
      <div className="mx-auto flex h-20 w-full max-w-7xl items-center justify-between gap-4 px-4 lg:px-8">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
            <ShieldCheck className="size-4" />
            Личный кабинет
          </div>
          <h1 className="mt-1 truncate text-lg font-semibold text-slate-950 lg:text-xl">
            {mounted ? user?.full_name || user?.email || 'FinanceApp' : 'FinanceApp'}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 md:block">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <CalendarDays className="size-4" />
              <span className="capitalize">{todayLabel}</span>
            </div>
            <p className="mt-0.5 max-w-56 truncate text-sm font-medium text-slate-700">
              {mounted ? user?.email ?? 'Нет данных' : '...'}
            </p>
          </div>

          <Button variant="secondary" onClick={handleSettings}>
            <Settings className="size-4" />
            Настройки
          </Button>

          <Button variant="secondary" onClick={handleLogout}>
            <LogOut className="size-4" />
            Выйти
          </Button>
        </div>
      </div>
    </header>
  );
}
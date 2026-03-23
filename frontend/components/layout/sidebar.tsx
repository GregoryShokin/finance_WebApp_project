"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils/cn';
import { navItems } from './nav-items';

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-screen w-80 shrink-0 border-r border-white/60 bg-white/70 p-6 backdrop-blur lg:block">
      <div className="flex h-full flex-col">
        <Link href="/dashboard" className="surface-panel mb-6 flex items-center gap-4 p-4">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-slate-950 text-lg font-semibold text-white shadow-soft">₽</div>
          <div>
            <p className="text-base font-semibold text-slate-950">FinanceApp</p>
            <p className="text-sm text-slate-500">Учёт личных финансов</p>
          </div>
        </Link>

        <div className="mb-3 px-3 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Разделы</div>
        <nav className="space-y-1.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition',
                  isActive
                    ? 'bg-slate-950 text-white shadow-soft'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950',
                )}
              >
                <Icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="surface-muted mt-auto p-4">
          <p className="text-sm font-medium text-slate-800">Следующий этап</p>
          <p className="mt-1 text-sm leading-6 text-slate-500">После стандартизации UI сюда удобно добавлять импорт выписок, правила и AI-классификацию без визуального хаоса.</p>
        </div>
      </div>
    </aside>
  );
}

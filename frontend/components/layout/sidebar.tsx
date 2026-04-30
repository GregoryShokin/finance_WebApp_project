"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, LogOut, Settings } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { cn } from '@/lib/utils/cn';
import { getParkedQueue } from '@/lib/api/imports';
import { removeAccessToken } from '@/lib/auth/token';
import { useAuth } from '@/hooks/use-auth';
import { isNavGroup, navItems, type NavGroup, type NavLeaf } from './nav-items';

// ── Badge hook ────────────────────────────────────────────────────────────────

function useParkedQueueCount(): number {
  const { data } = useQuery({
    queryKey: ['imports', 'parked-queue'],
    queryFn: () => getParkedQueue(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  return data?.total ?? 0;
}

// ── Leaf link ─────────────────────────────────────────────────────────────────

function NavLeafLink({ item, indent = false }: { item: NavLeaf; indent?: boolean }) {
  const pathname = usePathname();
  const isActive = pathname === item.href;
  const Icon = item.icon;
  const parkedCount = useParkedQueueCount();
  const badgeValue = item.badge === 'parked-queue' ? parkedCount : null;

  return (
    <Link
      href={item.href}
      className={cn(
        'flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 font-sans text-[13px] font-medium transition',
        indent && 'ml-4',
        isActive
          ? 'bg-ink text-white'
          : 'text-ink-2 hover:bg-ink/5 hover:text-ink',
      )}
    >
      <Icon className={cn('size-4 shrink-0', isActive ? 'opacity-90' : 'opacity-60')} />
      <span className="flex-1 truncate">{item.label}</span>
      {badgeValue && badgeValue > 0 ? (
        <span
          className={cn(
            'inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums',
            isActive ? 'bg-white text-ink' : 'bg-bg-surface2 text-ink-2',
          )}
        >
          {badgeValue}
        </span>
      ) : null}
    </Link>
  );
}

// ── Group item ────────────────────────────────────────────────────────────────

function NavGroupItem({ item }: { item: NavGroup }) {
  const pathname = usePathname();
  const Icon = item.icon;
  const isChildActive = item.children.some((c) => pathname === c.href);
  const [isOpen, setIsOpen] = useState(isChildActive);

  useEffect(() => {
    if (isChildActive) setIsOpen(true);
  }, [isChildActive]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 font-sans text-[13px] font-medium transition',
          isChildActive ? 'text-ink' : 'text-ink-2 hover:bg-ink/5 hover:text-ink',
        )}
      >
        <Icon className="size-4 shrink-0 opacity-60" />
        <span className="flex-1 text-left truncate">{item.label}</span>
        <ChevronDown
          className={cn(
            'size-3.5 shrink-0 text-ink-3 transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </button>

      <div
        className={cn(
          'overflow-hidden transition-all duration-200',
          isOpen ? 'max-h-40 opacity-100' : 'max-h-0 opacity-0',
        )}
      >
        <div className="mt-0.5 space-y-0.5">
          {item.children.map((child) => (
            <NavLeafLink key={child.href} item={child} indent />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

export function Sidebar() {
  const router = useRouter();
  const { user } = useAuth();

  function handleLogout() {
    removeAccessToken();
    router.replace('/login');
  }

  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r border-line bg-bg-surface2 px-2.5 py-3.5 lg:flex">
      <Link
        href="/dashboard"
        className="mb-2.5 flex items-center gap-2.5 border-b border-line px-2 pb-3.5 pt-1.5"
      >
        <div className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-ink text-[13px] font-semibold text-white">
          F
        </div>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-ink">FinanceApp</div>
          <div className="mt-0.5 truncate text-[11px] text-ink-3">Учёт личных финансов</div>
        </div>
      </Link>

      <div className="px-2 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-3">
        Разделы
      </div>
      <nav className="space-y-0.5">
        {navItems.map((item) =>
          isNavGroup(item) ? (
            <NavGroupItem key={item.label} item={item} />
          ) : (
            <NavLeafLink key={item.href} item={item} />
          ),
        )}
      </nav>

      <div className="mt-auto space-y-1 border-t border-line pt-3">
        <Link
          href="/settings"
          className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] text-ink-2 transition hover:bg-ink/5 hover:text-ink"
        >
          <Settings className="size-4 shrink-0 opacity-60" />
          <span>Настройки</span>
        </Link>
        <button
          type="button"
          onClick={handleLogout}
          className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-ink-2 transition hover:bg-ink/5 hover:text-ink"
        >
          <LogOut className="size-4 shrink-0 opacity-60" />
          <span>Выйти</span>
        </button>
        {user?.email ? (
          <div className="px-2.5 pt-2 text-[11px] text-ink-3">
            <div className="truncate">{user.full_name || user.email}</div>
            {user.full_name ? (
              <div className="mt-0.5 truncate text-ink-3/70">{user.email}</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

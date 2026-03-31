"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils/cn';
import { isNavGroup, navItems, type NavGroup, type NavLeaf } from './nav-items';

// ── Leaf link ─────────────────────────────────────────────────────────────────

function NavLeafLink({ item, indent = false }: { item: NavLeaf; indent?: boolean }) {
  const pathname = usePathname();
  const isActive = pathname === item.href;
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      className={cn(
        'flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition',
        indent && 'ml-4',
        isActive
          ? 'bg-slate-950 text-white shadow-soft'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950',
      )}
    >
      <Icon className="size-4" />
      {item.label}
    </Link>
  );
}

// ── Group item ────────────────────────────────────────────────────────────────

function NavGroupItem({ item }: { item: NavGroup }) {
  const pathname = usePathname();
  const Icon = item.icon;

  const isChildActive = item.children.some((c) => pathname === c.href);

  const [isOpen, setIsOpen] = useState(isChildActive);

  // Auto-open when navigating to a child route; auto-close when navigating away
  useEffect(() => {
    if (isChildActive) {
      setIsOpen(true);
    }
  }, [isChildActive]);

  return (
    <div>
      {/* Group header button */}
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition',
          isChildActive
            ? 'text-slate-950'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950',
        )}
      >
        <Icon className="size-4 shrink-0" />
        <span className="flex-1 text-left">{item.label}</span>
        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-slate-400 transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </button>

      {/* Children — animated with max-height */}
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
          {navItems.map((item) =>
            isNavGroup(item) ? (
              <NavGroupItem key={item.label} item={item} />
            ) : (
              <NavLeafLink key={item.href} item={item} />
            ),
          )}
        </nav>

        <div className="surface-muted mt-auto p-4">
          <p className="text-sm font-medium text-slate-800">Следующий этап</p>
          <p className="mt-1 text-sm leading-6 text-slate-500">После стандартизации UI сюда удобно добавлять импорт выписок, правила и AI-классификацию без визуального хаоса.</p>
        </div>
      </div>
    </aside>
  );
}

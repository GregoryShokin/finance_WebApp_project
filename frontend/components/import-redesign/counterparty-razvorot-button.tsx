'use client';

/**
 * CounterpartyRazvorotButton — pill (or icon-square) opening a razvorot
 * popover with search + create flow.
 *
 * Two variants:
 *   - compact (default): 32x32 icon button with a small dot when assigned.
 *     Used inside TxRow next to the traffic-light buttons.
 *   - full pill: shows the counterparty name. Used inside SplitModal where
 *     the label needs to be visible without hover.
 */

import { type ReactNode, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronRight, Loader2, Plus, Search, User, X } from 'lucide-react';
import { toast } from 'sonner';

import { createCounterparty } from '@/lib/api/counterparties';
import type { Counterparty } from '@/types/counterparty';
import type { CreatableOption } from '@/components/ui/creatable-select';
import { cn } from '@/lib/utils/cn';

type Props = {
  value: number | null;
  options: CreatableOption[];
  disabled?: boolean;
  onChange: (id: number) => void;
  /** Set false to render the full-width pill variant (used in SplitModal). */
  compact?: boolean;
  width?: number | string;
  placeholder?: string;
};

export function CounterpartyRazvorotButton({
  value,
  options,
  disabled = false,
  onChange,
  compact = true,
  width,
  placeholder = '— контрагент —',
}: Props) {
  const [open, setOpen] = useState<{ origin: { x: number; y: number } } | null>(null);
  const btnRef = useRef<HTMLButtonElement | null>(null);

  const selected = options.find((o) => String(o.value) === String(value)) || null;
  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (disabled) return;
    const r = e.currentTarget.getBoundingClientRect();
    setOpen({ origin: { x: r.left + r.width / 2, y: r.top + r.height / 2 } });
  };

  // ── Compact icon button ──────────────────────────────────────────────────
  if (compact) {
    return (
      <>
        <button
          ref={btnRef}
          type="button"
          onClick={handleClick}
          disabled={disabled}
          title={
            disabled
              ? 'Контрагент недоступен для этого типа операции'
              : selected
                ? `Контрагент: ${selected.label}`
                : 'Выбрать контрагента'
          }
          className={cn(
            'relative grid size-8 place-items-center rounded-md transition active:translate-y-px',
            disabled && 'cursor-not-allowed opacity-40',
            selected
              ? 'border border-accent-violet bg-accent-violet-soft text-accent-violet'
              : 'text-ink-3 hover:bg-ink/5',
          )}
        >
          <User className="size-3.5" />
          {selected ? (
            <span
              className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-bg-surface bg-accent-violet"
              aria-hidden
            />
          ) : null}
        </button>

        <AnimatePresence>
          {open ? (
            <CounterpartyPicker
              value={value}
              options={options}
              origin={open.origin}
              onChange={(id) => {
                onChange(id);
                setOpen(null);
              }}
              onClose={() => setOpen(null)}
            />
          ) : null}
        </AnimatePresence>
      </>
    );
  }

  // ── Full pill variant ───────────────────────────────────────────────────
  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={handleClick}
        disabled={disabled}
        title={disabled ? 'Контрагент недоступен' : 'Выбрать контрагента'}
        style={{ width: typeof width === 'number' ? `${width}px` : width }}
        className={cn(
          'inline-flex h-8 items-center justify-between gap-1.5 rounded-pill border border-line bg-bg-surface px-3 text-xs transition hover:border-line-strong',
          disabled && 'cursor-not-allowed opacity-40',
          selected ? 'text-ink' : 'text-ink-3',
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <User className="size-3 shrink-0 text-ink-3" />
          <span className="truncate">{selected ? selected.label : placeholder}</span>
        </span>
        <ChevronRight className="size-3 shrink-0 text-ink-3" />
      </button>

      <AnimatePresence>
        {open ? (
          <CounterpartyPicker
            value={value}
            options={options}
            origin={open.origin}
            onChange={(id) => {
              onChange(id);
              setOpen(null);
            }}
            onClose={() => setOpen(null)}
          />
        ) : null}
      </AnimatePresence>
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Razvorot popover with search + inline create

function CounterpartyPicker({
  value,
  options,
  origin,
  onChange,
  onClose,
}: {
  value: number | null;
  options: CreatableOption[];
  origin: { x: number; y: number };
  onChange: (id: number) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const q = query.trim().toLowerCase();
  const filtered = q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  const exact = options.some((o) => o.label.toLowerCase() === q);
  const showCreate = query.trim().length > 0 && !exact;

  const createMut = useMutation({
    mutationFn: (name: string) => createCounterparty({ name }),
    onSuccess: async (cp: Counterparty) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      toast.success(`Контрагент «${cp.name}» создан`);
      onChange(cp.id);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать'),
  });

  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[9100] bg-ink/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="pointer-events-none fixed inset-0 z-[9101] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.05 }}
          animate={{ opacity: 1, scale: 1, transition: { duration: 0.28, ease: [0.16, 0.84, 0.3, 1] } }}
          exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.14 } }}
          style={{
            transformOrigin: `${origin.x - window.innerWidth / 2}px ${origin.y - window.innerHeight / 2}px`,
          }}
          className="pointer-events-auto flex w-[min(440px,90vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
          <header className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-violet text-white">
              <User className="size-3.5" />
            </span>
            <div className="flex-1">
              <div className="text-sm font-semibold text-ink">Контрагент</div>
              <div className="mt-0.5 text-[11px] text-ink-3">
                Найди существующего или создай нового — будет сохранён в общем списке.
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
            >
              <X className="size-3.5" />
            </button>
          </header>

          <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
            <Search className="size-3.5 shrink-0 text-ink-3" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск или новое название…"
              className="block w-full bg-transparent text-xs text-ink outline-none placeholder:text-ink-3"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (filtered.length > 0) onChange(Number(filtered[0].value));
                  else if (showCreate) createMut.mutate(query.trim());
                }
              }}
            />
          </div>

          <div className="max-h-72 overflow-auto py-1">
            {filtered.length === 0 && !showCreate ? (
              <div className="px-4 py-3 text-xs text-ink-3">Ничего не найдено.</div>
            ) : null}
            {filtered.map((opt) => {
              const sel = String(opt.value) === String(value);
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onChange(Number(opt.value))}
                  className={cn(
                    'flex w-full items-center justify-between px-4 py-2 text-left text-xs transition',
                    sel ? 'bg-bg-surface2 font-medium' : 'hover:bg-bg-surface2',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span className="grid size-6 place-items-center rounded-md bg-accent-violet-soft text-[10.5px] font-semibold text-accent-violet">
                      {opt.label.charAt(0).toUpperCase() || '·'}
                    </span>
                    <span className="truncate">{opt.label}</span>
                  </span>
                  {sel ? <Check className="size-3.5" /> : null}
                </button>
              );
            })}
          </div>

          {showCreate ? (
            <button
              type="button"
              onClick={() => createMut.mutate(query.trim())}
              disabled={createMut.isPending}
              className="flex w-full items-center gap-2 border-t border-line bg-bg-surface2 px-4 py-2.5 text-left text-xs font-medium text-ink transition hover:bg-line/40 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {createMut.isPending ? (
                <Loader2 className="size-3 animate-spin text-accent-violet" />
              ) : (
                <Plus className="size-3 text-accent-violet" />
              )}
              Создать «{query.trim()}»
            </button>
          ) : null}
        </motion.div>
      </div>
    </>,
    document.body,
  ) as ReactNode;
}

'use client';

/**
 * CreatableSelect — warm-design dropdown with built-in "+ Создать..." action.
 *
 * Two creation modes:
 *  - inline:  onCreate(query) is called with the typed name; component shows
 *             a loading state inside the dropdown until it resolves.
 *  - dialog:  onOpenCreateDialog() opens an external dialog (e.g. AccountDialog)
 *             and the parent is responsible for selecting the new entity via
 *             setValue once the dialog returns.
 *
 * Used by ImportEntitySelects in components/import/entity-selects.tsx.
 */

import {
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronDown, Loader2, Plus, Search } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

const DROPDOWN_EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1];
const DROPDOWN_EASE_IN: [number, number, number, number] = [0.4, 0, 1, 1];

export type CreatableOption = {
  value: string;
  label: string;
  hint?: string;       // small grey trailing label (e.g. category type)
  toneDot?: string;    // optional accent dot color (e.g. 'var(--accent-violet)')
};

type CreateMode =
  | { kind: 'inline'; onCreate: (name: string) => Promise<CreatableOption | null>; createLabel?: string }
  | { kind: 'dialog'; onOpenCreateDialog: (queryPrefill: string) => void; createLabel?: string }
  | { kind: 'none' };

export function CreatableSelect({
  value,
  options,
  placeholder = '— выбрать —',
  onChange,
  createMode = { kind: 'none' },
  width,
  size = 'sm',
  accentDot,
  disabled = false,
  emptyHint = 'Ничего не найдено',
}: {
  value: string | null | undefined;
  options: CreatableOption[];
  placeholder?: string;
  onChange: (value: string) => void;
  createMode?: CreateMode;
  width?: number | string;
  size?: 'sm' | 'md';
  accentDot?: string;
  disabled?: boolean;
  emptyHint?: ReactNode;
}) {
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [coords, setCoords] = useState<{ top: number; left: number; width: number } | null>(null);
  const [creating, setCreating] = useState(false);
  const [portalReady, setPortalReady] = useState(false);

  useEffect(() => setPortalReady(true), []);

  const selected = useMemo(() => options.find((o) => o.value === value) ?? null, [options, value]);

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!normalizedQuery) return options;
    return options.filter((o) => o.label.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery, options]);

  const hasExactMatch = useMemo(
    () => options.some((o) => o.label.toLowerCase() === normalizedQuery),
    [options, normalizedQuery],
  );
  const canCreate = createMode.kind === 'inline' || createMode.kind === 'dialog';
  const showCreateRow = canCreate && !hasExactMatch && (createMode.kind === 'dialog' || query.trim().length > 0);

  const updateCoords = () => {
    if (!btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    setCoords({ top: r.bottom + 4, left: r.left, width: r.width });
  };

  useLayoutEffect(() => {
    if (open) updateCoords();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onScroll = () => updateCoords();
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target)) return;
      if (popRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery('');
      window.requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const handlePick = (opt: CreatableOption) => {
    onChange(opt.value);
    setOpen(false);
  };

  const handleCreate = async () => {
    if (createMode.kind === 'dialog') {
      setOpen(false);
      window.requestAnimationFrame(() => createMode.onOpenCreateDialog(query.trim()));
      return;
    }
    if (createMode.kind === 'inline') {
      const name = query.trim();
      if (!name) return;
      setCreating(true);
      try {
        const created = await createMode.onCreate(name);
        if (created) {
          onChange(created.value);
          setOpen(false);
        }
      } finally {
        setCreating(false);
      }
    }
  };

  const heightClass = size === 'sm' ? 'h-8' : 'h-9';
  const paddingClass = size === 'sm' ? 'px-2.5 text-xs' : 'px-3 text-sm';

  const dot = accentDot || selected?.toneDot;

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        className={cn(
          'inline-flex w-full items-center justify-between gap-1.5 rounded-lg border border-line bg-bg-surface font-sans text-ink transition hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-50',
          heightClass,
          paddingClass,
        )}
        style={{ width: typeof width === 'number' ? `${width}px` : width }}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {dot ? (
            <span className="size-2 shrink-0 rounded-full" style={{ background: dot }} />
          ) : null}
          <span className={cn('truncate', !selected && 'text-ink-3')}>
            {selected?.label ?? placeholder}
          </span>
        </span>
        <ChevronDown className="size-3 shrink-0 text-ink-3" />
      </button>

      {portalReady && coords
        ? createPortal(
            <AnimatePresence>
              {open ? (
                <motion.div
                  ref={popRef}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: 0.12, ease: DROPDOWN_EASE_OUT } }}
                  exit={{ opacity: 0, y: -4, transition: { duration: 0.1, ease: DROPDOWN_EASE_IN } }}
                  className="fixed z-[9999] overflow-hidden rounded-xl border border-line bg-bg-surface shadow-modal"
                  style={{
                    top: coords.top,
                    left: coords.left,
                    minWidth: Math.max(coords.width, 220),
                  }}
                >
                  <div className="flex items-center gap-2 border-b border-line px-2.5 py-2">
                    <Search className="size-3.5 shrink-0 text-ink-3" />
                    <input
                      ref={inputRef}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Поиск или новое название…"
                      className="w-full bg-transparent font-sans text-xs text-ink outline-none placeholder:text-ink-3"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (filtered.length > 0) {
                            handlePick(filtered[0]);
                          } else if (showCreateRow) {
                            handleCreate();
                          }
                        }
                      }}
                    />
                  </div>

                  <div className="max-h-64 overflow-auto py-1">
                    {filtered.length === 0 && !showCreateRow ? (
                      <div className="px-3 py-2 text-xs text-ink-3">{emptyHint}</div>
                    ) : null}

                    {filtered.map((opt) => {
                      const isSel = opt.value === value;
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => handlePick(opt)}
                          className={cn(
                            'flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs text-ink transition hover:bg-bg-surface2',
                            isSel && 'bg-bg-surface2 font-medium',
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-1.5">
                            {opt.toneDot ? (
                              <span
                                className="size-2 shrink-0 rounded-full"
                                style={{ background: opt.toneDot }}
                              />
                            ) : null}
                            <span className="truncate">{opt.label}</span>
                          </span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            {opt.hint ? (
                              <span className="text-[10px] text-ink-3">{opt.hint}</span>
                            ) : null}
                            {isSel ? <Check className="size-3" /> : null}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {showCreateRow && canCreate ? (
                    <button
                      type="button"
                      onClick={handleCreate}
                      disabled={creating}
                      className="flex w-full items-center gap-2 border-t border-line bg-bg-surface2 px-3 py-2 text-left text-xs font-medium text-ink transition hover:bg-line/40 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {creating ? (
                        <Loader2 className="size-3 animate-spin text-ink-3" />
                      ) : (
                        <Plus className="size-3 text-ink-3" />
                      )}
                      <span className="truncate">
                        {createMode.kind === 'inline' && createMode.createLabel
                          ? createMode.createLabel
                          : createMode.kind === 'dialog' && createMode.createLabel
                            ? createMode.createLabel
                            : query.trim()
                              ? `Создать «${query.trim()}»`
                              : 'Создать новое…'}
                      </span>
                    </button>
                  ) : null}
                </motion.div>
              ) : null}
            </AnimatePresence>,
            document.body,
          )
        : null}
    </>
  );
}

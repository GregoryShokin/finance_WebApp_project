'use client';

/**
 * Attach-to-counterparty UI (Phase 3).
 *
 * Shared between:
 *   - "Требуют внимания" row action (AttentionCard) — one icon button per row
 *   - Cluster row list (ClusterCard expanded view) — per-row action to move
 *     a stray row from a brand cluster into its own counterparty
 *
 * The FLIP modal animates from the click coordinate so the motion still
 * feels anchored to the row even when invoked from deep inside a cluster
 * card. Picker lists every user counterparty, highlighting the ones that
 * already have a binding active in this import session.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { createCounterparty, getCounterparties } from '@/lib/api/counterparties';
import type { Counterparty } from '@/types/counterparty';
import type { BulkClustersResponse } from '@/types/import';

export type AttachToCounterpartyPick = { id: number; name: string };

/**
 * Icon button + modal opener. Saves click coordinates for the FLIP animation.
 *
 * The visual variant keeps the button consistent with sibling icons (split,
 * exclude) in both the attention card (32×32) and the cluster row list (28×28).
 */
export function AttachToCounterpartyButton({
  open,
  setOpen,
  bulkClusters,
  sourceDirection,
  sourceAmount,
  sourceDescription,
  onAttach,
  isPending,
  size = 'md',
  title = 'Добавить к контрагенту',
}: {
  open: boolean;
  setOpen: (next: boolean) => void;
  bulkClusters: BulkClustersResponse | undefined;
  sourceDirection: 'income' | 'expense';
  sourceAmount: number;
  sourceDescription: string;
  onAttach: (cp: AttachToCounterpartyPick) => void;
  isPending: boolean;
  size?: 'sm' | 'md';
  title?: string;
}) {
  const sizeClass = size === 'sm' ? 'h-7 w-7' : 'h-8 w-8';
  const iconClass = size === 'sm' ? 'size-3.5' : 'size-4';
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          (window as any).__lastAttachClick = { x: e.clientX, y: e.clientY };
          setOpen(true);
        }}
        title={title}
        disabled={isPending}
        className={`flex items-center justify-center ${sizeClass} rounded-md border transition ${
          open
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
            : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-700'
        } disabled:opacity-50`}
      >
        {/* person-with-plus icon */}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={iconClass}>
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <line x1="19" y1="8" x2="19" y2="14" />
          <line x1="16" y1="11" x2="22" y2="11" />
        </svg>
      </button>
      <AttachCounterpartyModal
        isOpen={open}
        onClose={() => setOpen(false)}
        sourceRow={{ amount: sourceAmount, direction: sourceDirection, description: sourceDescription }}
      >
        <AttachCounterpartyPicker
          bulkClusters={bulkClusters}
          onPick={onAttach}
          isPending={isPending}
        />
      </AttachCounterpartyModal>
    </>
  );
}

// FLIP-modal for "Attach to counterparty". Animates from click origin to
// centre and back; identical to SplitModal's motion contract.
function AttachCounterpartyModal({
  isOpen,
  onClose,
  sourceRow,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  sourceRow: { amount: number; direction: 'income' | 'expense'; description: string };
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'closed' | 'measure' | 'enter' | 'open' | 'exit'>('closed');
  const originRef = useRef<{ x: number; y: number } | null>(null);
  const DURATION = 320;
  const EASING = 'cubic-bezier(0.4, 0, 0.15, 1)';

  useEffect(() => {
    if (isOpen && phase === 'closed') {
      const lastClick = (window as any).__lastAttachClick as { x: number; y: number } | undefined;
      originRef.current = lastClick ?? { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      setPhase('measure');
    }
  }, [isOpen, phase]);

  useLayoutEffect(() => {
    if (phase !== 'measure') return;
    const panel = panelRef.current;
    const origin = originRef.current;
    if (!panel || !origin) return;
    panel.style.transition = 'none';
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '0';
    const rect = panel.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const dx = origin.x - centerX;
    const dy = origin.y - centerY;
    panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
    panel.getBoundingClientRect();
    panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.6)}ms ease`;
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '1';
    setPhase('enter');
  }, [phase]);

  useEffect(() => {
    if (!isOpen && phase !== 'closed' && phase !== 'exit') {
      const panel = panelRef.current;
      const origin = originRef.current;
      if (!panel || !origin) {
        setPhase('closed');
        return;
      }
      const rect = panel.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = origin.x - centerX;
      const dy = origin.y - centerY;
      panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.5)}ms ease`;
      panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
      panel.style.opacity = '0';
      setPhase('exit');
    }
  }, [isOpen, phase]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent) => {
      if (e.propertyName !== 'transform') return;
      if (phase === 'enter') setPhase('open');
      if (phase === 'exit') setPhase('closed');
    },
    [phase],
  );

  useEffect(() => {
    if (phase !== 'exit') return;
    const t = setTimeout(() => setPhase('closed'), DURATION + 100);
    return () => clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase === 'closed') return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    const sw = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (sw > 0) document.body.style.paddingRight = `${sw}px`;
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    };
  }, [phase, onClose]);

  if (phase === 'closed' || typeof document === 'undefined') return null;
  const backdropVisible = phase === 'enter' || phase === 'open';

  return createPortal(
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 z-[100]"
        style={{
          backgroundColor: 'rgba(0,0,0,0.25)',
          opacity: backdropVisible ? 1 : 0,
          transition: `opacity ${DURATION}ms ease`,
        }}
      />
      <div
        ref={panelRef}
        onTransitionEnd={handleTransitionEnd}
        className="fixed left-1/2 top-1/2 z-[101] max-h-[85vh] w-[720px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-3xl bg-white p-6 shadow-[0_25px_80px_rgba(0,0,0,0.18)]"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 z-10 flex size-8 items-center justify-center rounded-full bg-slate-100 text-base text-slate-500 transition hover:bg-slate-200"
        >
          ✕
        </button>
        <div className="mb-3 pr-10">
          <h3 className="text-base font-semibold text-slate-900">Добавить к контрагенту</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            {sourceRow.direction === 'income' ? '↓ Доход' : '↑ Расход'} · {sourceRow.amount.toFixed(2)} ₽ · {sourceRow.description}
          </p>
        </div>
        <div className={phase === 'open' ? 'overflow-y-auto max-h-[calc(85vh-9rem)]' : ''}>
          {children}
        </div>
      </div>
    </>,
    document.body,
  );
}

// Picker of user counterparties. Active-in-session (those with an existing
// CounterpartyFingerprint binding visible in bulkClusters.counterparty_groups)
// float to the top with an "в импорте" badge. "+ Создать нового" is available
// via the same input whenever the query doesn't match an existing name.
function AttachCounterpartyPicker({
  bulkClusters,
  onPick,
  isPending,
}: {
  bulkClusters: BulkClustersResponse | undefined;
  onPick: (cp: AttachToCounterpartyPick) => void;
  isPending: boolean;
}) {
  const [query, setQuery] = useState('');
  const [createPending, setCreatePending] = useState(false);
  const queryClient = useQueryClient();

  const counterpartiesQuery = useQuery({
    queryKey: ['counterparties'],
    queryFn: getCounterparties,
  });
  const counterparties: Counterparty[] = counterpartiesQuery.data ?? [];

  const activeGroups = bulkClusters?.counterparty_groups ?? [];
  const activeById = useMemo(() => {
    const map = new Map<number, typeof activeGroups[number]>();
    for (const g of activeGroups) map.set(g.counterparty_id, g);
    return map;
  }, [activeGroups]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? counterparties.filter((cp) => cp.name.toLowerCase().includes(q))
      : counterparties;
    return [...list].sort((a, b) => {
      const ga = activeById.get(a.id);
      const gb = activeById.get(b.id);
      if (!!ga !== !!gb) return ga ? -1 : 1;
      if (ga && gb) return gb.count - ga.count;
      return a.name.localeCompare(b.name, 'ru');
    });
  }, [counterparties, query, activeById]);

  const trimmed = query.trim();
  const exactMatch = counterparties.some(
    (cp) => cp.name.toLowerCase() === trimmed.toLowerCase(),
  );
  const canCreate = trimmed.length > 0 && !exactMatch;

  const handleCreate = async () => {
    if (!canCreate || createPending) return;
    setCreatePending(true);
    try {
      const created = await createCounterparty({ name: trimmed });
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      onPick({ id: created.id, name: created.name });
    } catch (err) {
      toast.error((err as Error).message || 'Не удалось создать контрагента');
    } finally {
      setCreatePending(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <input
        autoFocus
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Поиск контрагента или имя нового…"
        className="h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-slate-400 focus:outline-none"
      />
      <p className="text-xs text-slate-400">
        Клик — операция уйдёт к этому контрагенту и его паттерн запомнится для будущих импортов.
      </p>
      {canCreate ? (
        <button
          type="button"
          disabled={isPending || createPending}
          onClick={handleCreate}
          className="flex w-full items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm font-medium text-indigo-700 transition hover:bg-indigo-100 disabled:opacity-50"
        >
          <Plus className="size-4" />
          {createPending ? 'Создаю…' : `Создать нового контрагента «${trimmed}»`}
        </button>
      ) : null}
      {filtered.length === 0 && !canCreate ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          {counterparties.length === 0
            ? 'У тебя пока нет контрагентов. Начни набирать имя, чтобы создать первого.'
            : 'Ничего не найдено. Попробуй другой запрос.'}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((cp) => {
            const active = activeById.get(cp.id);
            return (
              <button
                key={cp.id}
                type="button"
                disabled={isPending}
                onClick={() => onPick({ id: cp.id, name: cp.name })}
                className="flex w-full flex-col gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-indigo-300 hover:bg-indigo-50/30 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900">
                    {cp.name}
                  </span>
                  {active ? (
                    <span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                      в импорте
                    </span>
                  ) : null}
                </div>
                {active ? (
                  <div className="flex items-center gap-3 text-xs text-slate-400">
                    <span>{active.count} операц{active.count === 1 ? 'ия' : active.count < 5 ? 'ии' : 'ий'}</span>
                    <span>·</span>
                    <span className="tabular-nums">
                      {Math.round(Math.abs(Number(active.total_amount) || 0)).toLocaleString('ru-RU')} ₽
                    </span>
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

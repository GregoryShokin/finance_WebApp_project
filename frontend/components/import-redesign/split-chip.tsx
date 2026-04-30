'use client';

/**
 * SplitChip — read-only badge shown in bucket rows for transactions that
 * have been divided into N parts. Hovering reveals a popover with each
 * part's category, counterparty, description and amount.
 */

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Split } from 'lucide-react';
import { fmtRubAbs } from './format';
import type { ImportSplitItem } from '@/types/import';

const partsWord = (n: number) =>
  n === 1 ? 'часть' : n < 5 ? 'части' : 'частей';

export function SplitChip({
  parts,
  categoriesById,
  counterpartiesById,
}: {
  parts: ImportSplitItem[];
  categoriesById: Map<number, string>;
  counterpartiesById?: Map<number, string>;
}) {
  const [open, setOpen] = useState(false);
  const refEl = useRef<HTMLSpanElement | null>(null);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);

  const updateCoords = () => {
    if (!refEl.current) return;
    const r = refEl.current.getBoundingClientRect();
    setCoords({ top: r.bottom + 6, left: r.left });
  };

  useEffect(() => {
    if (!open) return;
    updateCoords();
    const onScroll = () => updateCoords();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [open]);

  // Only categories matter for split_items today (backend schema).
  const uniqCats = new Set(parts.filter((p) => p.category_id != null).map((p) => p.category_id));
  const subtitle = [
    `${parts.length} ${partsWord(parts.length)}`,
    uniqCats.size > 1 ? `${uniqCats.size} категории` : null,
  ].filter(Boolean).join(' · ');

  return (
    <span
      ref={refEl}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      className="chip chip-violet cursor-help text-[10.5px]"
    >
      <Split className="size-2.5" />
      Разделена · {parts.length}
      {open && coords ? createPortal(
        <div
          style={{
            position: 'fixed',
            top: coords.top,
            left: coords.left,
            zIndex: 9999,
            minWidth: 280,
            maxWidth: 360,
          }}
          className="overflow-hidden rounded-xl border border-line bg-bg-surface shadow-modal animate-selectIn"
        >
          <div className="border-b border-line px-3.5 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-ink-3">
            Операция разделена · {subtitle}
          </div>
          <div>
            {parts.map((p, i) => {
              const catName = p.category_id != null ? categoriesById.get(p.category_id) : null;
              return (
                <div
                  key={i}
                  className="grid grid-cols-[20px_1fr_auto] items-center gap-2.5 px-3.5 py-2 text-xs last:border-b-0"
                  style={{ borderBottom: i < parts.length - 1 ? '1px solid var(--line, #e3e4e8)' : 'none' }}
                >
                  <span className="font-mono text-[10.5px] text-ink-3">#{i + 1}</span>
                  <div className="min-w-0 text-ink">
                    <div className="flex flex-wrap gap-1">
                      {catName ? (
                        <span className="inline-flex items-center rounded-pill bg-accent-green-soft px-2 py-0.5 text-[10.5px] text-accent-green">
                          {catName}
                        </span>
                      ) : (
                        <span className="inline-flex items-center rounded-pill bg-bg-surface2 px-2 py-0.5 text-[10.5px] text-ink-3">
                          без категории
                        </span>
                      )}
                    </div>
                    {p.description ? (
                      <div className="mt-1 truncate text-[10.5px] text-ink-3">{p.description}</div>
                    ) : null}
                  </div>
                  <span className="font-mono text-xs font-semibold tabular-nums">
                    {fmtRubAbs(p.amount)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>,
        document.body,
      ) : null}
    </span>
  );
}

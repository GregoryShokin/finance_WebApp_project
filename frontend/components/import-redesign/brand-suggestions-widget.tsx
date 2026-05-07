'use client';

/**
 * BrandSuggestionsWidget — «Мы видим N строк, похожих на X — создать бренд?»
 *
 * Renders one card per group returned by `GET /brands/suggested-groups`.
 * Threshold (≥3 rows) is enforced server-side; this widget just renders
 * the result. Each card opens BrandCreateModal seeded with the group's
 * first sample row, so the form prefills with the right skeleton-derived
 * canonical name + pattern.
 *
 * Hidden completely when there are no candidates — no empty-state box —
 * so it doesn't add visual noise on sessions where every brand is known.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';

import { listSuggestedBrandGroups, type SuggestedBrandGroup } from '@/lib/api/brands';
import { BrandCreateModal } from './brand-create-modal';
import type { CreatableOption } from '@/components/ui/creatable-select';

export function BrandSuggestionsWidget({
  sessionId,
  categoryOptions,
}: {
  sessionId: number;
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
}) {
  const [active, setActive] = useState<{
    rowId: number;
    rawDescription: string;
  } | null>(null);

  const query = useQuery({
    queryKey: ['brand-suggested-groups', sessionId],
    queryFn: () => listSuggestedBrandGroups(sessionId),
    enabled: sessionId > 0,
    staleTime: 10_000,
  });

  const groups: SuggestedBrandGroup[] = query.data?.suggestions ?? [];
  if (query.isLoading || groups.length === 0) return null;

  return (
    <section className="border-b border-line bg-emerald-50/40 px-5 py-3">
      <header className="mb-2 flex items-center gap-2">
        <Sparkles className="size-4 text-emerald-600" />
        <h4 className="text-[13px] font-semibold text-ink">
          Похожие на бренды
          <span className="ml-1 font-normal text-ink-3">· {groups.length}</span>
        </h4>
      </header>

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {groups.map((g) => (
          <li
            key={g.candidate}
            className="rounded-xl border border-emerald-200 bg-white px-3 py-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-ink">
                  «{titleCase(g.candidate)}»
                </div>
                <div className="text-[11px] text-ink-3">
                  {g.row_count} {pluralRows(g.row_count)} в этой сессии
                </div>
                {g.sample_descriptions.length > 0 ? (
                  <ul className="mt-1 space-y-0.5">
                    {g.sample_descriptions.slice(0, 2).map((d, i) => (
                      <li key={i} className="truncate text-[11px] text-ink-3">
                        · {d}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => {
                  if (g.sample_row_ids.length === 0) return;
                  setActive({
                    rowId: g.sample_row_ids[0],
                    rawDescription: g.sample_descriptions[0] ?? '',
                  });
                }}
                disabled={g.sample_row_ids.length === 0}
                className="shrink-0 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                Создать бренд
              </button>
            </div>
          </li>
        ))}
      </ul>

      {active ? (
        <BrandCreateModal
          open={true}
          rowId={active.rowId}
          sessionId={sessionId}
          rawDescription={active.rawDescription}
          categoryOptions={categoryOptions}
          onClose={() => setActive(null)}
        />
      ) : null}
    </section>
  );
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function pluralRows(n: number): string {
  const last = n % 10;
  const tens = n % 100;
  if (tens >= 11 && tens <= 14) return 'строк';
  if (last === 1) return 'строка';
  if (last >= 2 && last <= 4) return 'строки';
  return 'строк';
}

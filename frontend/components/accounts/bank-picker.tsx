'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, Search, X } from 'lucide-react';
import { getBanks } from '@/lib/api/banks';
import { Button } from '@/components/ui/button';
import { BankIcon } from '@/components/ui/bank-icon';
import type { Bank } from '@/types/account';

type Props = {
  value: number | null;
  onChange: (bank: Bank | null) => void;
};

export function BankPicker({ value, onChange }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState('');

  const allQuery = useQuery({ queryKey: ['banks'], queryFn: () => getBanks() });
  const searchQuery = useQuery({
    queryKey: ['banks', 'search', query],
    queryFn: () => getBanks(query),
    enabled: query.trim().length > 0,
  });

  const banks = query.trim() ? (searchQuery.data ?? []) : (allQuery.data ?? []);
  const popular = useMemo(() => (allQuery.data ?? []).filter((b) => b.is_popular), [allQuery.data]);

  const selected = useMemo(
    () => (value ? (allQuery.data ?? []).find((b) => b.id === value) ?? null : null),
    [value, allQuery.data],
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="flex h-10 w-full items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-left text-sm shadow-sm hover:border-slate-300 focus:outline-none focus:border-slate-400"
      >
        {selected ? (
          <BankIcon code={selected.code} bank={selected.name} size={20} />
        ) : (
          <Building2 className="size-4 shrink-0 text-slate-400" />
        )}
        {selected ? (
          <span className="flex-1 font-medium text-slate-900">{selected.name}</span>
        ) : (
          <span className="flex-1 text-slate-400">— выбрать банк —</span>
        )}
        {selected && (
          <X
            className="size-4 shrink-0 text-slate-400 hover:text-slate-600"
            onClick={(e) => { e.stopPropagation(); onChange(null); }}
          />
        )}
      </button>

      {modalOpen && (
        <BankModal
          query={query}
          onQueryChange={setQuery}
          popular={popular}
          banks={banks}
          selectedId={value}
          onSelect={(bank) => { onChange(bank); setModalOpen(false); setQuery(''); }}
          onClose={() => { setModalOpen(false); setQuery(''); }}
        />
      )}
    </>
  );
}

function BankModal({
  query,
  onQueryChange,
  popular,
  banks,
  selectedId,
  onSelect,
  onClose,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  popular: Bank[];
  banks: Bank[];
  selectedId: number | null;
  onSelect: (bank: Bank) => void;
  onClose: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const showPopular = !query.trim();
  const list = showPopular ? popular : banks;

  return createPortal(
    // z-[10001] beats the Dialog's z-[10000] backdrop so this nested modal
    // stays on top when BankPicker is used inside a Dialog (account form
    // opens as a dialog on /accounts, otherwise the bank list sat below
    // the backdrop and clicks never reached it).
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex w-full max-w-md flex-col rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Выбрать банк</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="size-5" />
          </button>
        </div>

        {/* Search */}
        <div className="px-4 pt-3 pb-2">
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2">
            <Search className="size-4 shrink-0 text-slate-400" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Поиск по названию..."
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
            />
            {query && (
              <button type="button" onClick={() => onQueryChange('')}>
                <X className="size-4 text-slate-400" />
              </button>
            )}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-2 pb-3" style={{ maxHeight: '360px' }}>
          {showPopular && (
            <p className="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Популярные
            </p>
          )}
          {list.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-400 text-center">Ничего не найдено</p>
          ) : (
            list.map((bank) => (
              <button
                key={bank.id}
                type="button"
                onClick={() => onSelect(bank)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-slate-50 ${
                  bank.id === selectedId ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-800'
                }`}
              >
                <BankIcon code={bank.code} bank={bank.name} size={32} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{bank.name}</p>
                  {bank.bik && <p className="text-xs text-slate-400">БИК {bank.bik}</p>}
                </div>
                {bank.id === selectedId && (
                  <span className="text-xs text-indigo-500">✓</span>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

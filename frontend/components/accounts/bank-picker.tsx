'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, Search, X } from 'lucide-react';
import { getBanks } from '@/lib/api/banks';
import { BankIcon } from '@/components/ui/bank-icon';
import type { Bank, ExtractorStatus } from '@/types/account';

type Props = {
  value: number | null;
  onChange: (bank: Bank | null) => void;
  // When true, only banks with a tested extractor are shown. The picker
  // becomes a "trusted" picker for the import flow. Default false — the
  // account form lets users register an account for any bank, then visually
  // marks unsupported ones with a "Скоро" badge.
  supportedOnly?: boolean;
};

export function BankPicker({ value, onChange, supportedOnly = false }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState('');

  const allQuery = useQuery({
    queryKey: ['banks', { supportedOnly }],
    queryFn: () => getBanks(undefined, { supportedOnly }),
  });
  const searchQuery = useQuery({
    queryKey: ['banks', 'search', query, { supportedOnly }],
    queryFn: () => getBanks(query, { supportedOnly }),
    enabled: query.trim().length > 0,
  });

  const banks = query.trim() ? (searchQuery.data ?? []) : (allQuery.data ?? []);

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
        {selected && <ExtractorBadge status={selected.extractor_status} compact />}
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
  banks,
  selectedId,
  onSelect,
  onClose,
}: {
  query: string;
  onQueryChange: (q: string) => void;
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

  const supported = useMemo(
    () => banks.filter((b) => b.extractor_status === 'supported'),
    [banks],
  );
  const unsupported = useMemo(
    () => banks.filter((b) => b.extractor_status !== 'supported'),
    [banks],
  );

  return createPortal(
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex w-full max-w-md flex-col rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Выбрать банк</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="size-5" />
          </button>
        </div>

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

        <div className="flex-1 overflow-y-auto px-2 pb-3" style={{ maxHeight: '420px' }}>
          {banks.length === 0 ? (
            <p className="px-3 py-4 text-sm text-slate-400 text-center">Ничего не найдено</p>
          ) : (
            <>
              {supported.length > 0 && (
                <BankSection
                  title="Импорт поддерживается"
                  banks={supported}
                  selectedId={selectedId}
                  onSelect={onSelect}
                />
              )}
              {unsupported.length > 0 && (
                <BankSection
                  title="Импорт пока не поддерживается"
                  banks={unsupported}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  muted
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function BankSection({
  title,
  banks,
  selectedId,
  onSelect,
  muted = false,
}: {
  title: string;
  banks: Bank[];
  selectedId: number | null;
  onSelect: (bank: Bank) => void;
  muted?: boolean;
}) {
  return (
    <>
      <p className="px-3 pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </p>
      {banks.map((bank) => (
        <button
          key={bank.id}
          type="button"
          onClick={() => onSelect(bank)}
          className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-slate-50 ${
            bank.id === selectedId
              ? 'bg-indigo-50 font-medium text-indigo-700'
              : muted
                ? 'text-slate-500'
                : 'text-slate-800'
          }`}
        >
          <BankIcon code={bank.code} bank={bank.name} size={32} />
          <div className="min-w-0 flex-1">
            <p className={`truncate font-medium ${muted ? 'text-slate-600' : ''}`}>{bank.name}</p>
            {bank.bik && <p className="text-xs text-slate-400">БИК {bank.bik}</p>}
          </div>
          <ExtractorBadge status={bank.extractor_status} />
          {bank.id === selectedId && <span className="text-xs text-indigo-500">✓</span>}
        </button>
      ))}
    </>
  );
}

function ExtractorBadge({ status, compact = false }: { status: ExtractorStatus; compact?: boolean }) {
  if (status === 'supported') return null;
  const label = status === 'broken' ? 'Временно не работает' : 'Скоро';
  const color = status === 'broken'
    ? 'bg-amber-50 text-amber-700 ring-amber-200'
    : 'bg-slate-100 text-slate-500 ring-slate-200';
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ${color} ${compact ? '' : 'ml-auto'}`}
    >
      {label}
    </span>
  );
}

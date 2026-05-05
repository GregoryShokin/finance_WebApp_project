'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { X } from 'lucide-react';
import { createPortal } from 'react-dom';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { createBankSupportRequest } from '@/lib/api/bank-support';
import type { Bank } from '@/types/account';

type Props = {
  // When passed, prefills bank_id/bank_name and disables the bank input.
  bank?: Bank | null;
  onClose: () => void;
};

export function BankSupportRequestModal({ bank, onClose }: Props) {
  const [bankName, setBankName] = useState(bank?.name ?? '');
  const [note, setNote] = useState('');

  const submitMut = useMutation({
    mutationFn: () =>
      createBankSupportRequest({
        bank_id: bank?.id ?? null,
        bank_name: bankName.trim(),
        note: note.trim() || null,
      }),
    onSuccess: (req) => {
      toast.success(
        req.status === 'added'
          ? 'Этот банк уже добавлен — обнови список'
          : 'Запрос отправлен. Сообщим, когда добавим поддержку.',
      );
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось отправить запрос'),
  });

  const canSubmit = bankName.trim().length > 0 && !submitMut.isPending;

  return createPortal(
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex w-full max-w-md flex-col gap-4 rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Запросить поддержку банка</h2>
            <p className="mt-1 text-sm text-slate-500">
              Расскажи, какой банк добавить — мы напишем парсер выписки и сообщим, когда импорт заработает.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="size-5" />
          </button>
        </div>

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) submitMut.mutate();
          }}
        >
          <div>
            <Label htmlFor="bsr-bank">Банк</Label>
            <Input
              id="bsr-bank"
              value={bankName}
              onChange={(e) => setBankName(e.target.value)}
              placeholder="Например, Точка"
              disabled={!!bank}
            />
          </div>
          <div>
            <Label htmlFor="bsr-note">Комментарий (необязательно)</Label>
            <textarea
              id="bsr-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Какие форматы выписок есть, тип счёта и т.п."
              rows={3}
              maxLength={2000}
              className="block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
            />
          </div>

          <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitMut.isPending ? 'Отправляем...' : 'Отправить запрос'}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}

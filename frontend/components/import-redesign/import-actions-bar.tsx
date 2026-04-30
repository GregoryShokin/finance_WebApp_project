'use client';

/**
 * Top-of-page action row.
 * Layout (warm-design 2026-04-30):
 *   [ Загрузить выписку ]  [ Очередь выписок (N) ●●● ]      [ Импортировать готовые (R) · Σ ]
 */

import { type ChangeEvent, useRef } from 'react';
import { ChevronRight, Check, FileText, RotateCcw, Upload } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

export function ImportActionsBar({
  onUpload,
  onOpenQueue,
  onCommit,
  onReset,
  queueCount,
  queueOk,
  queueSnz,
  queueExc,
  readyCount,
  readySum,
  uploading = false,
  committing = false,
  resetting = false,
  queuePillRef,
  resetEnabled = true,
}: {
  onUpload: (file: File) => void;
  onOpenQueue: () => void;
  onCommit: () => void;
  onReset?: () => void;
  queueCount: number;
  queueOk: number;
  queueSnz: number;
  queueExc: number;
  readyCount: number;
  /** Optional human-formatted total (e.g. "21 348 ₽"). Hidden if absent. */
  readySum?: string | null;
  uploading?: boolean;
  committing?: boolean;
  resetting?: boolean;
  resetEnabled?: boolean;
  queuePillRef?: React.MutableRefObject<HTMLButtonElement | null>;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUpload(file);
    event.target.value = '';
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          className="inline-flex items-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-[13px] font-medium text-white shadow-pill transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Upload className="size-3.5" />
          {uploading ? 'Загружаем…' : 'Загрузить выписку'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx,.pdf"
          className="hidden"
          onChange={handleFile}
        />

        <button
          ref={queuePillRef}
          type="button"
          onClick={onOpenQueue}
          className="group inline-flex items-center gap-2.5 rounded-pill border border-line bg-bg-surface px-3.5 py-2.5 text-[13px] font-medium text-ink shadow-pill transition hover:-translate-y-px hover:shadow-pillHover"
        >
          <FileText className="size-3.5 text-ink-3" />
          Очередь выписок
          <span className="rounded-pill bg-bg-surface2 px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums">
            {queueCount}
          </span>
          <span className="ml-1 flex gap-1">
            <span
              className={cn('size-1.5 rounded-full bg-accent-green', queueOk === 0 && 'opacity-30')}
              title={`${queueOk} готовы`}
            />
            <span
              className={cn('size-1.5 rounded-full bg-accent-amber', queueSnz === 0 && 'opacity-30')}
              title={`${queueSnz} в работе`}
            />
            <span
              className={cn('size-1.5 rounded-full bg-accent-red', queueExc === 0 && 'opacity-30')}
              title={`${queueExc} ошибок`}
            />
          </span>
        </button>
      </div>

      <div className="flex items-center gap-2">
        {onReset ? (
          <button
            type="button"
            onClick={onReset}
            disabled={resetting || !resetEnabled}
            title="Сбросить статусы строк (parked/excluded → в очередь). Категории и привязки остаются."
            className="inline-flex h-[42px] items-center gap-1.5 rounded-xl border border-line bg-bg-surface px-3 text-[12px] font-medium text-ink transition hover:bg-bg-surface2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RotateCcw className={cn('size-3.5 text-ink-3', resetting && 'animate-spin')} />
            Сбросить сессию
          </button>
        ) : null}
        <button
          type="button"
          disabled={readyCount === 0 || committing}
          onClick={onCommit}
          className={cn(
            'inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-[13px] font-medium shadow-pill transition',
            readyCount > 0 && !committing
              ? 'bg-accent-green text-white hover:bg-accent-green/90'
              : 'cursor-not-allowed bg-bg-surface2 text-ink-3 border border-line',
          )}
        >
          <Check className="size-3.5" />
          Импортировать готовые ({readyCount})
          {readySum ? <span className="text-[11px] opacity-85">· {readySum}</span> : null}
          {readyCount > 0 ? <ChevronRight className="size-3.5 opacity-70" /> : null}
        </button>
      </div>
    </div>
  );
}

'use client';

/**
 * Duplicate-statement detection modal (Этап 0.5).
 *
 * Backend signals two distinct shapes via `ImportUploadResponse.action_required`:
 *   - `'choose'` — an UNCOMMITTED session with the same file_hash exists.
 *     User picks: open the existing session, upload as a parallel new one, or cancel.
 *   - `'warn'`   — only COMMITTED sessions exist for this file_hash. Soft
 *     warning: user can still upload as new (e.g. a re-issued statement),
 *     or cancel.
 *
 * Discriminated union on `action` lets TypeScript exhaustively check rendering
 * branches and prevents passing `existingProgress` to the WARN variant (where
 * progress is meaningless — committed sessions have nothing left to lose).
 *
 * "Перезаписать" / "Загрузить как новую" are intentionally NON-destructive —
 * they call upload again with `force_new=true`, leaving the original session
 * in the queue. The user reconciles in the queue UI which session to keep.
 */

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import type { ExistingProgress, ImportSessionStatus } from '@/types/import';

export type DuplicateModalProps =
  | {
      open: boolean;
      action: 'choose';
      existingSessionId: number;
      existingProgress: ExistingProgress | null;
      existingStatus: ImportSessionStatus | null;
      existingCreatedAt: string | null;
      filename: string;
      onOpenExisting: () => void;
      onForceNew: () => void;
      onCancel: () => void;
    }
  | {
      open: boolean;
      action: 'warn';
      existingSessionId: number;
      existingStatus: ImportSessionStatus | null;
      existingCreatedAt: string | null;
      filename: string;
      onForceNew: () => void;
      onCancel: () => void;
    };

export function DuplicateModal(props: DuplicateModalProps) {
  if (props.action === 'choose') {
    return <ChooseDialog {...props} />;
  }
  return <WarnDialog {...props} />;
}

// ─── CHOOSE — uncommitted duplicate ──────────────────────────────────────────

function ChooseDialog(props: Extract<DuplicateModalProps, { action: 'choose' }>) {
  const { open, existingProgress, existingCreatedAt, filename, onOpenExisting, onForceNew, onCancel } = props;
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title="Эта выписка уже загружена"
      description={`Файл «${filename}»${formatRelativeAgo(existingCreatedAt)}`}
    >
      <ProgressBlock progress={existingProgress} />
      <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="button" variant="secondary" onClick={onForceNew}>
          Загрузить как новую
        </Button>
        <Button type="button" onClick={onOpenExisting}>
          Открыть существующую
        </Button>
      </div>
    </Dialog>
  );
}

function ProgressBlock({ progress }: { progress: ExistingProgress | null }) {
  // Backend skips `existing_progress` on freshly-uploaded sessions where rows
  // haven't been parsed yet — show a reassuring placeholder instead of "0 of 0".
  if (!progress || progress.total_rows === 0) {
    return (
      <p className="text-sm text-slate-600">
        Сессия только начата, изменений ещё нет — безопасно загрузить как новую.
      </p>
    );
  }
  const hasWork = progress.committed_rows > 0 || progress.user_actions > 0;
  if (!hasWork) {
    return (
      <p className="text-sm text-slate-600">
        В существующей сессии {progress.total_rows} строк, изменений нет.
      </p>
    );
  }
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-medium">В существующей сессии есть несохранённая работа.</p>
      <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
        <li>
          Готово {progress.committed_rows} из {progress.total_rows} строк
        </li>
        <li>Изменено / отложено / исключено: {progress.user_actions}</li>
      </ul>
      <p className="mt-2 text-xs text-amber-800/80">
        «Загрузить как новую» создаст параллельную сессию — старая сохранится в очереди.
      </p>
    </div>
  );
}

// ─── WARN — committed duplicate ──────────────────────────────────────────────

function WarnDialog(props: Extract<DuplicateModalProps, { action: 'warn' }>) {
  const { open, existingCreatedAt, filename, onForceNew, onCancel } = props;
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title="Эта выписка уже импортирована"
      description={`Файл «${filename}»${formatRelativeAgo(existingCreatedAt)}`}
    >
      <p className="text-sm text-slate-600">
        Транзакции уже в базе. Если банк прислал обновлённую версию выписки и
        её нужно перезагрузить — создаём параллельную сессию.
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="button" onClick={onForceNew}>
          Загрузить как новую
        </Button>
      </div>
    </Dialog>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────────

const RU_PLURAL_DAYS = (n: number) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'день';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'дня';
  return 'дней';
};

/**
 * Human-readable relative-time suffix for duplicate-modal headers. We do this
 * client-side because the bot already gets a backend-formatted absolute date
 * (see `_format_bot_duplicate_message`) — but for the web modal a relative
 * "2 дня назад" reads better than an absolute timestamp.
 *
 * Falls back to absolute date if parsing fails. Never throws — broken dates
 * just hide the suffix rather than break the modal.
 */
function formatRelativeAgo(iso: string | null): string {
  if (!iso) return '';
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return '';
  const diffMs = Date.now() - ts;
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days <= 0) return ' — сегодня';
  if (days === 1) return ' — вчера';
  if (days < 30) return ` — ${days} ${RU_PLURAL_DAYS(days)} назад`;
  // Fallback to absolute date for older sessions.
  try {
    const date = new Date(ts);
    return ` — ${date.toLocaleDateString('ru-RU')}`;
  } catch {
    return '';
  }
}

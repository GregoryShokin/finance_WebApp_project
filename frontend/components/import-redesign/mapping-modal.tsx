'use client';

/**
 * "Сопоставить колонки" — modal opened from queue rows whose auto-preview
 * failed (status: error).
 *
 * Phase C step 5: the legacy <ImportWizard> renderer was removed
 * alongside the Counterparty surface — its moderator section was
 * deeply coupled to the dropped table. Manual column mapping is rare
 * (the bank whitelist makes auto-preview the common path) and lands
 * here as a placeholder until the dedicated mapping UI ships in a
 * follow-up. The user sees an actionable hint to retry / re-upload.
 */

import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';

export function MappingModal({
  sessionId,
  onClose,
}: {
  sessionId: number;
  onClose: () => void;
}) {
  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[9050] bg-ink/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1, transition: { duration: 0.22, ease: [0.16, 0.84, 0.3, 1] } }}
        exit={{ opacity: 0, scale: 0.96 }}
        className="fixed left-1/2 top-1/2 z-[9051] flex max-h-[92vh] w-[min(720px,94vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-line bg-bg shadow-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line bg-bg-surface px-5 py-4">
          <div>
            <div className="text-[15px] font-semibold text-ink">Сопоставить колонки</div>
            <div className="mt-0.5 text-xs text-ink-3">
              Сессия #{sessionId}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
          >
            <X className="size-3.5" />
          </button>
        </div>
        <div className="space-y-3 p-6 text-sm text-ink-2">
          <p>
            Ручное сопоставление колонок временно недоступно. Это окно открывается
            только когда автоматический разбор файла не сработал.
          </p>
          <p>
            Попробуй заново загрузить файл — большинство банков из списка
            поддержки разбираются автоматически. Если ошибка повторяется —
            напиши в поддержку, приложив скриншот этого окна и название банка.
          </p>
        </div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
}

'use client';

/**
 * "Сопоставить колонки" — modal opened from queue rows whose auto-preview
 * failed (status: error). Falls back to the legacy <ImportWizard> mapping
 * step UI for now: the mapping form is heavy enough that mounting the
 * full wizard inside a modal is the safest path until we redesign mapping
 * dedicated.
 *
 * Renders ImportWizard with initialSessionId; once mapping succeeds, the
 * preview triggers and the wizard's own UI takes over inside the modal.
 */

import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';

import { ImportWizard } from '@/components/import/import-wizard';

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
        className="fixed left-1/2 top-1/2 z-[9051] flex max-h-[92vh] w-[min(1080px,94vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-line bg-bg shadow-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line bg-bg-surface px-5 py-4">
          <div>
            <div className="text-[15px] font-semibold text-ink">Сопоставить колонки</div>
            <div className="mt-0.5 text-xs text-ink-3">
              Подскажи системе, какая колонка содержит дату, сумму и описание.
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
        <div className="overflow-auto p-4">
          <ImportWizard initialSessionId={sessionId} onSessionCreated={() => {}} />
        </div>
      </motion.div>
    </AnimatePresence>,
    document.body,
  );
}

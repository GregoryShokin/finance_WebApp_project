'use client';

import { Dialog } from '@/components/ui/dialog';
import { DebtPartnerForm } from '@/components/debt-partners/debt-partner-form';
import type { CreateDebtPartnerPayload } from '@/types/debt-partner';

export function DebtPartnerDialog({
  open,
  draft,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  draft?: Partial<CreateDebtPartnerPayload> | null;
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateDebtPartnerPayload) => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Новый дебитор / кредитор"
      description="Создай человека или бизнес, с которым у тебя долговые отношения, прямо из формы операции."
      size="md"
    >
      <DebtPartnerForm initialValues={draft} isSubmitting={isSubmitting} onSubmit={onSubmit} onCancel={onClose} />
    </Dialog>
  );
}

'use client';

import { Dialog } from '@/components/ui/dialog';
import { CounterpartyForm } from '@/components/counterparties/counterparty-form';
import type { CreateCounterpartyPayload } from '@/types/counterparty';

export function CounterpartyDialog({
  open,
  draft,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  draft?: Partial<CreateCounterpartyPayload> | null;
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateCounterpartyPayload) => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} title="Новый контрагент" description="Создай должника или кредитора прямо из формы операции." size="md">
      <CounterpartyForm initialValues={draft} isSubmitting={isSubmitting} onSubmit={onSubmit} onCancel={onClose} />
    </Dialog>
  );
}

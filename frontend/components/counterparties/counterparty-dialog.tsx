'use client';

import { Dialog } from '@/components/ui/dialog';
import { CounterpartyForm } from '@/components/counterparties/counterparty-form';
import type { CreateCounterpartyPayload } from '@/types/counterparty';

export function CounterpartyDialog({
  open,
  mode = 'create',
  draft,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mode?: 'create' | 'edit';
  draft?: Partial<CreateCounterpartyPayload> | null;
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateCounterpartyPayload) => void;
}) {
  const isEdit = mode === 'edit';
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={isEdit ? 'Редактировать контрагента' : 'Новый контрагент'}
      description={
        isEdit
          ? 'Обнови имя контрагента.'
          : 'Создай должника или кредитора прямо из формы операции.'
      }
      size="md"
    >
      <CounterpartyForm
        mode={mode}
        initialValues={draft}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
        onCancel={onClose}
      />
    </Dialog>
  );
}

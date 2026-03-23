'use client';

import { ReactNode } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  size = 'md',
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  size?: 'md' | 'lg' | 'xl';
}) {
  if (!open) {
    return null;
  }

  const maxWidthClassName = size === 'xl' ? 'max-w-7xl' : size === 'lg' ? 'max-w-4xl' : 'max-w-lg';

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/40 p-4 pt-8 sm:items-center sm:pt-4" onClick={onClose}>
      <Card
        className={`my-auto w-full ${maxWidthClassName} rounded-2xl border bg-white p-4 shadow-soft sm:p-6`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-xl font-semibold text-slate-900">{title}</h3>
            {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
          </div>
          <Button type="button" variant="ghost" className="h-9 w-9 px-0" onClick={onClose}>
            <X className="size-4" />
          </Button>
        </div>
        {children}
      </Card>
    </div>
  );
}

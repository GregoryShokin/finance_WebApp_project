'use client';

import { ReactNode, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
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
  // Render через portal в document.body, чтобы position:fixed был привязан
  // к viewport, а не к ближайшему transformed/filtered предку. Без этого
  // диалог может оказаться вне экрана (виден только backdrop), если ancestor
  // в дереве имеет transform/filter/will-change/contain — это создаёт
  // containing block для fixed-элементов.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  // Lock body scroll while open + закрытие по Esc.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    const sw = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (sw > 0) document.body.style.paddingRight = `${sw}px`;
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    };
  }, [open, onClose]);

  if (!open || !mounted || typeof document === 'undefined') {
    return null;
  }

  const maxWidthClassName = size === 'xl' ? 'max-w-7xl' : size === 'lg' ? 'max-w-4xl' : 'max-w-lg';

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center overflow-y-auto bg-slate-950/40 p-4 pt-8 sm:items-center sm:pt-4"
      onClick={onClose}
    >
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
    </div>,
    document.body,
  );
}

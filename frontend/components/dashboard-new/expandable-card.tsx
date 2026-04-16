'use client';

import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Props = {
  isOpen: boolean;
  onToggle: () => void;
  /** Width of the expanded overlay card, e.g. '560px', '860px' */
  expandedWidth?: string;
  collapsed: ReactNode;
  expanded: ReactNode;
};

export function ExpandableCard({ isOpen, onToggle, expandedWidth = '560px', collapsed, expanded }: Props) {
  const backdropRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    if (isOpen) onToggle();
  }, [isOpen, onToggle]);

  useEffect(() => {
    if (!isOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }

    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, close]);

  return (
    <>
      {/* Collapsed card */}
      <div
        onClick={onToggle}
        className="group relative cursor-pointer rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-shadow hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)]"
      >
        {collapsed}
        <span className="absolute bottom-2 right-3 text-[10px] font-medium text-slate-300 opacity-0 transition-opacity group-hover:opacity-100">
          Нажмите для деталей ↗
        </span>
      </div>

      {/* Expanded overlay via portal */}
      {typeof document !== 'undefined' && isOpen
        ? createPortal(
            <>
              {/* Backdrop */}
              <div
                ref={backdropRef}
                onClick={close}
                className="fixed inset-0 z-[100] bg-black/25 transition-opacity duration-250"
                style={{ opacity: isOpen ? 1 : 0 }}
              />
              {/* Expanded card */}
              <div
                className="fixed left-1/2 top-1/2 z-[101] max-h-[85vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[20px] bg-white p-7 shadow-[0_25px_80px_rgba(0,0,0,0.18)] transition-all duration-250"
                style={{
                  width: expandedWidth,
                  maxWidth: 'calc(100vw - 2rem)',
                  opacity: isOpen ? 1 : 0,
                  transform: isOpen
                    ? 'translate(-50%, -50%) scale(1)'
                    : 'translate(-50%, -50%) scale(0.95)',
                }}
              >
                <button
                  type="button"
                  onClick={close}
                  className="absolute right-4 top-4 flex size-8 items-center justify-center rounded-full bg-slate-100 text-base text-slate-500 transition hover:bg-slate-200"
                >
                  ✕
                </button>
                {expanded}
              </div>
            </>,
            document.body,
          )
        : null}
    </>
  );
}

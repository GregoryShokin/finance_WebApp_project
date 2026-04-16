'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Props = {
  isOpen: boolean;
  onToggle: () => void;
  /** Width of the expanded overlay card, e.g. '560px', '860px' */
  expandedWidth?: string;
  collapsed: ReactNode;
  expanded: ReactNode;
};

type Phase = 'closed' | 'measure' | 'enter' | 'open' | 'exit';

const DURATION = 380;
const EASING = 'cubic-bezier(0.4, 0, 0.15, 1)';

export function ExpandableCard({ isOpen, onToggle, expandedWidth = '560px', collapsed, expanded }: Props) {
  const cardRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>('closed');
  const originRef = useRef<DOMRect | null>(null);

  const close = useCallback(() => {
    if (isOpen) onToggle();
  }, [isOpen, onToggle]);

  /* ── Open trigger ────────────────────────────────────────────── */
  useEffect(() => {
    if (isOpen && phase === 'closed') {
      originRef.current = cardRef.current?.getBoundingClientRect() ?? null;
      setPhase('measure');
    }
  }, [isOpen, phase]);

  /* ── Measure & start enter animation (FLIP) ─────────────────── */
  useLayoutEffect(() => {
    if (phase !== 'measure') return;
    const panel = panelRef.current;
    const origin = originRef.current;
    if (!panel || !origin) return;

    // 1. Position at center, invisible, measure final rect
    panel.style.transition = 'none';
    panel.style.transform = 'translate(-50%, -50%)';
    panel.style.opacity = '0';
    panel.style.borderRadius = '20px';
    panel.style.willChange = 'transform, opacity';
    const rect = panel.getBoundingClientRect();

    // 2. Calculate FLIP transform (center → origin)
    const dx = (origin.left + origin.width / 2) - (rect.left + rect.width / 2);
    const dy = (origin.top + origin.height / 2) - (rect.top + rect.height / 2);
    const sx = origin.width / rect.width;
    const sy = origin.height / rect.height;

    // 3. Jump to origin position (no transition)
    panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${sx}, ${sy})`;
    panel.style.borderRadius = '16px';
    panel.getBoundingClientRect(); // force reflow → commit start state

    // 4. Animate to center
    panel.style.transition = [
      `transform ${DURATION}ms ${EASING}`,
      `opacity ${Math.round(DURATION * 0.6)}ms ease`,
      `border-radius ${DURATION}ms ease`,
    ].join(', ');
    panel.style.transform = 'translate(-50%, -50%)';
    panel.style.opacity = '1';
    panel.style.borderRadius = '20px';

    setPhase('enter');
  }, [phase]);

  /* ── Close trigger ───────────────────────────────────────────── */
  useEffect(() => {
    if (!isOpen && phase !== 'closed' && phase !== 'exit') {
      // If still measuring, just close immediately
      if (phase === 'measure') {
        setPhase('closed');
        return;
      }

      const panel = panelRef.current;
      const origin = cardRef.current?.getBoundingClientRect();
      if (!panel || !origin) {
        setPhase('closed');
        return;
      }

      const rect = panel.getBoundingClientRect();
      const dx = (origin.left + origin.width / 2) - (rect.left + rect.width / 2);
      const dy = (origin.top + origin.height / 2) - (rect.top + rect.height / 2);
      const sx = origin.width / rect.width;
      const sy = origin.height / rect.height;

      panel.style.transition = [
        `transform ${DURATION}ms ${EASING}`,
        `opacity ${Math.round(DURATION * 0.5)}ms ease ${Math.round(DURATION * 0.35)}ms`,
        `border-radius ${DURATION}ms ease`,
      ].join(', ');
      panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${sx}, ${sy})`;
      panel.style.opacity = '0';
      panel.style.borderRadius = '16px';

      setPhase('exit');
    }
  }, [isOpen, phase]);

  /* ── Transition end ──────────────────────────────────────────── */
  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent) => {
      if (e.propertyName !== 'transform') return;
      if (phase === 'enter') {
        setPhase('open');
        if (panelRef.current) panelRef.current.style.willChange = '';
      }
      if (phase === 'exit') setPhase('closed');
    },
    [phase],
  );

  /* ── Safety timeout (if transitionend doesn't fire) ──────────── */
  useEffect(() => {
    if (phase !== 'exit') return;
    const timeout = setTimeout(() => setPhase('closed'), DURATION + 100);
    return () => clearTimeout(timeout);
  }, [phase]);

  /* ── Escape & scroll lock (with scrollbar compensation) ──────── */
  useEffect(() => {
    if (phase === 'closed') return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }

    // Compensate for scrollbar width to prevent layout shift
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    };
  }, [phase, close]);

  const showPortal = phase !== 'closed';
  const backdropVisible = phase === 'enter' || phase === 'open';

  return (
    <>
      {/* Collapsed card */}
      <div
        ref={cardRef}
        onClick={onToggle}
        className="group relative cursor-pointer rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-shadow hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)]"
        style={{
          opacity: (phase === 'measure' || phase === 'enter' || phase === 'open') ? 0 : 1,
          transition: `opacity ${Math.round(DURATION * 0.25)}ms ease`,
        }}
      >
        {collapsed}
        <span className="absolute bottom-2 right-3 text-[10px] font-medium text-slate-300 opacity-0 transition-opacity group-hover:opacity-100">
          Нажмите для деталей ↗
        </span>
      </div>

      {/* Expanded overlay via portal */}
      {showPortal && typeof document !== 'undefined'
        ? createPortal(
            <>
              {/* Backdrop */}
              <div
                onClick={close}
                className="fixed inset-0 z-[100]"
                style={{
                  backgroundColor: 'rgba(0,0,0,0.25)',
                  opacity: backdropVisible ? 1 : 0,
                  transition: `opacity ${DURATION}ms ease`,
                }}
              />
              {/* Expanded card */}
              <div
                ref={panelRef}
                onTransitionEnd={handleTransitionEnd}
                className="fixed left-1/2 top-1/2 z-[101] max-h-[85vh] overflow-hidden bg-white p-7 shadow-[0_25px_80px_rgba(0,0,0,0.18)]"
                style={{
                  width: expandedWidth,
                  maxWidth: 'calc(100vw - 2rem)',
                }}
              >
                <button
                  type="button"
                  onClick={close}
                  className="absolute right-4 top-4 z-10 flex size-8 items-center justify-center rounded-full bg-slate-100 text-base text-slate-500 transition hover:bg-slate-200"
                >
                  ✕
                </button>
                <div className={phase === 'open' ? 'overflow-y-auto max-h-[calc(85vh-3.5rem)]' : ''}>
                  {expanded}
                </div>
              </div>
            </>,
            document.body,
          )
        : null}
    </>
  );
}

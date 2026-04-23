'use client';

import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';

type CollapsibleProps = {
  open: boolean;
  children: ReactNode;
  className?: string;
};

const DURATION = 0.24;
const EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1];
const EASE_IN: [number, number, number, number] = [0.4, 0, 1, 1];

export function Collapsible({ open, children, className }: CollapsibleProps) {
  return (
    <AnimatePresence initial={false}>
      {open ? (
        <motion.div
          key="collapsible"
          initial={{ height: 0, opacity: 0 }}
          animate={{
            height: 'auto',
            opacity: 1,
            transition: {
              height: { duration: DURATION, ease: EASE_OUT },
              opacity: { duration: DURATION * 0.9, ease: EASE_OUT, delay: 0.02 },
            },
          }}
          exit={{
            height: 0,
            opacity: 0,
            transition: {
              height: { duration: DURATION * 0.85, ease: EASE_IN },
              opacity: { duration: DURATION * 0.5, ease: EASE_IN },
            },
          }}
          style={{ overflow: 'hidden' }}
          className={className}
        >
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

type CollapsibleChevronProps = {
  open: boolean;
  className?: string;
};

export function CollapsibleChevron({ open, className }: CollapsibleChevronProps) {
  return (
    <motion.svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ?? 'size-4 text-slate-400'}
      animate={{ rotate: open ? 90 : 0 }}
      transition={{ duration: 0.22, ease: EASE_OUT }}
    >
      <path d="M7 5l6 5-6 5" />
    </motion.svg>
  );
}

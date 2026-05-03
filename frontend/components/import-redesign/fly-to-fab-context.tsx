'use client';

/**
 * Fly-to-FAB animation context.
 *
 * Usage:
 *   1. Wrap the page in <FlyToFabProvider>.
 *   2. FabBubble calls registerFab(bucket, el) to publish its DOM position.
 *   3. TxRow calls flyTo(rowEl, bucket) on TrafficBtn click.
 *   4. A phantom card is rendered in a portal, animates from the row to the FAB,
 *      then the FAB pulses via subscribePulse callbacks.
 */

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';

export type FlyBucket = 'done' | 'snz' | 'excl';

const BUCKET_COLOR: Record<FlyBucket, string> = {
  done: '#1e8a4f',
  snz: '#d49b1a',
  excl: '#e54033',
};

type PhantomEntry = {
  id: number;
  bucket: FlyBucket;
  sourceRect: DOMRect;
  targetRect: DOMRect;
};

type FlyToFabCtx = {
  registerFab: (bucket: FlyBucket, el: HTMLElement | null) => void;
  flyTo: (sourceEl: HTMLElement, bucket: FlyBucket) => void;
  subscribePulse: (bucket: FlyBucket, fn: () => void) => () => void;
};

const FlyToFabContext = createContext<FlyToFabCtx | null>(null);

let _uid = 0;

export function FlyToFabProvider({ children }: { children: React.ReactNode }) {
  const fabRefs = useRef<Partial<Record<FlyBucket, HTMLElement>>>({});
  const listeners = useRef<Partial<Record<FlyBucket, Set<() => void>>>>({});
  const [phantoms, setPhantoms] = useState<PhantomEntry[]>([]);

  const registerFab = useCallback((bucket: FlyBucket, el: HTMLElement | null) => {
    if (el) fabRefs.current[bucket] = el;
    else delete fabRefs.current[bucket];
  }, []);

  const flyTo = useCallback((sourceEl: HTMLElement, bucket: FlyBucket) => {
    const tgt = fabRefs.current[bucket];
    if (!tgt) return;
    const sourceRect = sourceEl.getBoundingClientRect();
    const targetRect = tgt.getBoundingClientRect();
    setPhantoms((prev) => [...prev, { id: ++_uid, bucket, sourceRect, targetRect }]);
  }, []);

  const subscribePulse = useCallback((bucket: FlyBucket, fn: () => void) => {
    if (!listeners.current[bucket]) listeners.current[bucket] = new Set();
    listeners.current[bucket]!.add(fn);
    return () => { listeners.current[bucket]?.delete(fn); };
  }, []);

  const dismiss = useCallback((id: number, bucket: FlyBucket) => {
    setPhantoms((prev) => prev.filter((p) => p.id !== id));
    listeners.current[bucket]?.forEach((fn) => fn());
  }, []);

  return (
    <FlyToFabContext.Provider value={{ registerFab, flyTo, subscribePulse }}>
      {children}
      {typeof window !== 'undefined' && phantoms.map((ph) =>
        createPortal(
          <PhantomCard key={ph.id} entry={ph} onDone={dismiss} />,
          document.body,
        ),
      )}
    </FlyToFabContext.Provider>
  );
}

/** Returns null if called outside a FlyToFabProvider (graceful degradation). */
export function useFlyToFab() {
  return useContext(FlyToFabContext);
}

// ─────────────────────────────────────────────────────────────────────────────

function PhantomCard({
  entry,
  onDone,
}: {
  entry: PhantomEntry;
  onDone: (id: number, bucket: FlyBucket) => void;
}) {
  const { id, bucket, sourceRect, targetRect } = entry;
  const color = BUCKET_COLOR[bucket];

  // Translate the element's center to the FAB's center.
  const srcCx = sourceRect.left + sourceRect.width / 2;
  const srcCy = sourceRect.top + sourceRect.height / 2;
  const tgtCx = targetRect.left + targetRect.width / 2;
  const tgtCy = targetRect.top + targetRect.height / 2;

  return (
    <motion.div
      style={{
        position: 'fixed',
        left: sourceRect.left,
        top: sourceRect.top,
        width: sourceRect.width,
        height: sourceRect.height,
        borderRadius: 16,
        background: `${color}12`,
        border: `1.5px solid ${color}90`,
        boxShadow: `0 4px 20px ${color}28`,
        zIndex: 9999,
        pointerEvents: 'none',
        transformOrigin: 'center center',
      }}
      initial={{ x: 0, y: 0, scale: 1, opacity: 1 }}
      animate={{
        x: tgtCx - srcCx,
        y: tgtCy - srcCy,
        scale: 0.08,
        opacity: [1, 1, 0.6, 0],
      }}
      transition={{
        duration: 0.52,
        ease: [0.4, 0, 1, 1],
        opacity: { times: [0, 0.38, 0.72, 1], ease: 'easeIn' },
      }}
      onAnimationComplete={() => onDone(id, bucket)}
    />
  );
}

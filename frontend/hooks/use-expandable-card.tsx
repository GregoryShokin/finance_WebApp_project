'use client';

import {
  CSSProperties,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { ChevronDown } from 'lucide-react';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { resolveExpandHorizontal, resolveExpandUp } from '@/lib/utils/widget-expand';

const SCALE = 1.8;

type HorizontalOrigin = 'left' | 'center' | 'right';

type UseExpandableCardOptions = {
  /** Stable identifier used to coordinate with other expandable widgets */
  id: string;
  /** Estimated expanded height — used to decide whether the card should grow up or down */
  expandHeight?: number;
};

type ExpandableCardHandle = {
  wrapperRef: React.RefObject<HTMLDivElement>;
  cardRef: React.RefObject<HTMLDivElement>;
  isExpanded: boolean;
  handleToggle: (next?: boolean) => void;
  wrapperStyle: CSSProperties;
  cardStyle: CSSProperties;
  backdrop: ReactNode;
  toggleButton: ReactNode;
};

/**
 * Centralises the "expand on click" interaction used by dashboard widgets such
 * as `AvailableFinancesWidget`. Every widget that needs this behaviour should
 * use this hook so the visual style and coordination rules stay in sync.
 *
 * Behaviour:
 *  - `scale(1.8)` transform, direction resolved via `resolveExpandUp`
 *  - Full-screen backdrop closes the card on click outside
 *  - Dispatches/listens to `FI_SCORE_WIDGET_EVENT` so opening one card closes others
 *  - Preserves the collapsed height on the wrapper to avoid layout reflow
 *
 * Usage:
 *   const { wrapperRef, cardRef, wrapperStyle, cardStyle, backdrop, toggleButton, isExpanded } =
 *     useExpandableCard({ id: 'my-widget', expandHeight: 400 });
 *
 *   return (
 *     <div ref={wrapperRef} className="relative h-full overflow-visible" style={wrapperStyle}>
 *       {backdrop}
 *       <div ref={cardRef}>
 *         <Card className="relative overflow-visible p-5" style={cardStyle}>
 *           {toggleButton}
 *           ...your content here
 *         </Card>
 *       </div>
 *     </div>
 *   );
 */
export function useExpandableCard({ id, expandHeight = 400 }: UseExpandableCardOptions): ExpandableCardHandle {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState(0);
  const [expandUp, setExpandUp] = useState(false);
  const [horizontalOrigin, setHorizontalOrigin] = useState<HorizontalOrigin>('center');

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Track collapsed height via ResizeObserver so the wrapper keeps its slot
  // in the grid when the card scales out of flow.
  useEffect(() => {
    const node = cardRef.current;
    if (!node) return;

    const measure = () => {
      if (!isExpanded && cardRef.current) {
        setCollapsedHeight(cardRef.current.offsetHeight);
      }
    };
    measure();

    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [isExpanded]);

  // Click anywhere outside the wrapper closes the expanded card.
  useEffect(() => {
    if (!isExpanded) return;

    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    }

    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  // Listen to other widgets' toggle events — opening a different card closes this one.
  useEffect(() => {
    function handleExternalToggle(event: Event) {
      const customEvent = event as CustomEvent<{ source?: string; open?: boolean }>;
      if (customEvent.detail?.source !== id && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, [id]);

  const handleToggle = useCallback(
    (next?: boolean) => {
      if ((!isExpanded || next === true) && cardRef.current) {
        setExpandUp(resolveExpandUp(cardRef.current, expandHeight));
        setHorizontalOrigin(resolveExpandHorizontal(cardRef.current, SCALE));
      }
      setIsExpanded((value) => {
        const target = typeof next === 'boolean' ? next : !value;
        document.dispatchEvent(
          new CustomEvent(FI_SCORE_WIDGET_EVENT, {
            detail: { source: id, open: target },
          }),
        );
        return target;
      });
    },
    [isExpanded, expandHeight, id],
  );

  const wrapperStyle = useMemo<CSSProperties>(
    () => ({ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }),
    [collapsedHeight],
  );

  const cardStyle = useMemo<CSSProperties>(
    () => {
      const verticalOrigin = expandUp ? 'bottom' : 'top';
      return {
        position: isExpanded ? 'absolute' : 'relative',
        top: isExpanded && !expandUp ? 0 : 'auto',
        bottom: isExpanded && expandUp ? 0 : 'auto',
        left: 0,
        right: 0,
        transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
        transformOrigin: isExpanded ? `${horizontalOrigin} ${verticalOrigin}` : 'center center',
        transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
        zIndex: isExpanded ? 50 : 1,
        overflow: 'visible',
      };
    },
    [isExpanded, expandUp, horizontalOrigin],
  );

  const backdrop = isExpanded ? (
    <button
      type="button"
      aria-label="Закрыть"
      onClick={() => handleToggle(false)}
      className="fixed inset-0 z-40 bg-black/10"
    />
  ) : null;

  const toggleButton = (
    <button
      type="button"
      onClick={() => handleToggle()}
      className="absolute right-3 top-3 flex size-[24px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
      aria-label="Подробнее"
      aria-expanded={isExpanded}
    >
      <ChevronDown className={`size-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
    </button>
  );

  return {
    wrapperRef,
    cardRef,
    isExpanded,
    handleToggle,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  };
}

'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, Trash2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleChevron } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils/cn';

const DROPDOWN_EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1];
const DROPDOWN_EASE_IN: [number, number, number, number] = [0.4, 0, 1, 1];

export type SearchSelectItem = {
  value: string;
  label: string;
  searchText?: string;
  badge?: string;
  badgeClassName?: string;
};

function normalize(value?: string | null) {
  return (value ?? '').trim().toLowerCase();
}

function getFilteredItems(items: SearchSelectItem[], query: string, limit: number) {
  const normalized = normalize(query);
  if (!normalized) return items.slice(0, limit);
  return items.filter((item) => normalize(item.searchText ?? item.label).includes(normalized)).slice(0, limit);
}

export function SearchSelect({
  id,
  label,
  placeholder,
  widthClassName,
  query,
  setQuery,
  items,
  selectedValue,
  onSelect,
  error,
  createAction,
  onDeleteItem,
  deleteItemLabel = 'Удалить',
  showAllOnFocus = false,
  limit = 8,
  disabled = false,
  inline = false,
  inputSize = 'md',
  hideLabel = false,
  inputClassName,
}: {
  id: string;
  label: string;
  placeholder: string;
  widthClassName: string;
  query: string;
  setQuery: (value: string) => void;
  items: SearchSelectItem[];
  selectedValue?: string | null;
  onSelect: (item: SearchSelectItem) => void;
  error?: string;
  createAction?: { visible: boolean; label: string; onClick: () => void };
  onDeleteItem?: (item: SearchSelectItem) => void;
  deleteItemLabel?: string;
  showAllOnFocus?: boolean;
  limit?: number;
  disabled?: boolean;
  inline?: boolean;
  inputSize?: 'sm' | 'md';
  hideLabel?: boolean;
  inputClassName?: string;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [isBrowsingOnFocus, setIsBrowsingOnFocus] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState<{ top: number; left: number; width: number } | null>(null);
  const [portalReady, setPortalReady] = useState(false);

  const selectedItem = useMemo(
    () => items.find((item) => item.value === selectedValue) ?? null,
    [items, selectedValue],
  );

  const effectiveQuery = useMemo(() => {
    if (showAllOnFocus && isBrowsingOnFocus) return '';
    if (showAllOnFocus && selectedItem && normalize(query) === normalize(selectedItem.label)) return '';
    return query;
  }, [isBrowsingOnFocus, query, selectedItem, showAllOnFocus]);

  const filteredItems = useMemo(
    () => getFilteredItems(items, effectiveQuery, limit),
    [items, effectiveQuery, limit],
  );

  const updateDropdownPosition = () => {
    if (!inputRef.current) return;
    const rect = inputRef.current.getBoundingClientRect();
    setDropdownStyle({
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
    });
  };

  useEffect(() => {
    setPortalReady(true);
  }, []);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [effectiveQuery, open]);

  useLayoutEffect(() => {
    if (!open) return;
    updateDropdownPosition();
  }, [open, filteredItems.length, widthClassName]);

  useEffect(() => {
    if (!open) return;

    const handleScrollOrResize = () => updateDropdownPosition();

    window.addEventListener('resize', handleScrollOrResize);
    window.addEventListener('scroll', handleScrollOrResize, true);

    return () => {
      window.removeEventListener('resize', handleScrollOrResize);
      window.removeEventListener('scroll', handleScrollOrResize, true);
    };
  }, [open]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (dropdownRef.current?.contains(target)) return;
      setOpen(false);
      setIsBrowsingOnFocus(false);
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        setIsBrowsingOnFocus(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, []);

  const listContent = (
    <>
      {filteredItems.length > 0 ? (
        <div className="max-h-60 overflow-auto py-1">
          {filteredItems.map((item, index) => {
            const isSelected = selectedValue === item.value;
            const isHighlighted = highlightedIndex === index;

            return (
              <div
                key={item.value}
                className={cn(
                  'flex w-full items-center gap-3 px-3 py-2 text-sm transition',
                  isHighlighted ? 'bg-slate-100' : 'hover:bg-slate-50',
                )}
              >
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    onSelect(item);
                    setOpen(false);
                    setIsBrowsingOnFocus(false);
                  }}
                >
                  <span className="min-w-0 flex-1 truncate text-slate-800">{item.label}</span>
                  {item.badge ? (
                    <span className={cn('shrink-0 text-xs text-slate-500', item.badgeClassName)}>{item.badge}</span>
                  ) : null}
                  {isSelected ? <Check className="size-4 shrink-0 text-slate-900" /> : null}
                </button>
                {onDeleteItem ? (
                  <button
                    type="button"
                    className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      onDeleteItem(item);
                    }}
                    aria-label={`${deleteItemLabel}: ${item.label}`}
                    title={`${deleteItemLabel}: ${item.label}`}
                  >
                    <Trash2 className="size-4" />
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {createAction?.visible ? (
        <div className="border-t border-slate-200 p-2">
          <Button
            type="button"
            className="h-9 w-full bg-black text-white hover:bg-black/90"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              setOpen(false);
              setIsBrowsingOnFocus(false);
              window.requestAnimationFrame(() => createAction.onClick());
            }}
          >
            {createAction.label}
          </Button>
        </div>
      ) : null}
    </>
  );

  const hasContent = filteredItems.length > 0 || !!createAction?.visible;

  const overlayDropdown = !inline && dropdownStyle && portalReady
    ? createPortal(
        <AnimatePresence initial={false}>
          {open && hasContent ? (
            <motion.div
              key="ss-overlay"
              ref={dropdownRef}
              className="fixed z-[9999] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
              style={{
                top: `${dropdownStyle.top}px`,
                left: `${dropdownStyle.left}px`,
                width: `${dropdownStyle.width}px`,
                transformOrigin: 'top center',
              }}
              initial={{ opacity: 0, y: -6, scaleY: 0.9 }}
              animate={{
                opacity: 1,
                y: 0,
                scaleY: 1,
                transition: { duration: 0.22, ease: DROPDOWN_EASE_OUT },
              }}
              exit={{
                opacity: 0,
                y: -4,
                scaleY: 0.95,
                transition: { duration: 0.14, ease: DROPDOWN_EASE_IN },
              }}
            >
              {listContent}
            </motion.div>
          ) : null}
        </AnimatePresence>,
        document.body,
      )
    : null;

  // Input sizing — `sm` keeps compact row-level selectors visually in line with
  // adjacent status pills and filter buttons; `md` is the full-size default.
  const inputHeightClass = inputSize === 'sm' ? 'h-9' : 'h-11';
  const paddingRightClass = inline ? (inputSize === 'sm' ? 'pr-8' : 'pr-9') : '';

  return (
    <div ref={rootRef} className={cn('relative overflow-visible', widthClassName)}>
      {hideLabel ? (
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
      ) : (
        <Label htmlFor={id}>{label}</Label>
      )}
      <div className="relative">
        <Input
          ref={inputRef}
          id={id}
          className={cn(inputHeightClass, paddingRightClass, inputClassName)}
          value={query}
          disabled={disabled}
          autoComplete="off"
          placeholder={placeholder}
          onFocus={() => {
            setIsBrowsingOnFocus(true);
            setOpen(true);
            if (!inline) updateDropdownPosition();
          }}
          onClick={() => {
            setIsBrowsingOnFocus(true);
            setOpen(true);
            if (!inline) updateDropdownPosition();
          }}
          onChange={(event) => {
            setIsBrowsingOnFocus(false);
            setQuery(event.target.value);
            setOpen(true);
            if (!inline) updateDropdownPosition();
          }}
          onKeyDown={(event) => {
            if (disabled) return;

            if (!open && (event.key === 'ArrowDown' || event.key === 'Enter')) {
              event.preventDefault();
              setIsBrowsingOnFocus(true);
              setOpen(true);
              if (!inline) updateDropdownPosition();
              return;
            }

            if (!open) return;

            if (filteredItems.length > 0 && event.key === 'ArrowDown') {
              event.preventDefault();
              setHighlightedIndex((prev) => (prev + 1) % filteredItems.length);
              return;
            }

            if (filteredItems.length > 0 && event.key === 'ArrowUp') {
              event.preventDefault();
              setHighlightedIndex((prev) => (prev - 1 + filteredItems.length) % filteredItems.length);
              return;
            }

            if (event.key === 'Enter') {
              event.preventDefault();
              if (filteredItems.length > 0) {
                onSelect(filteredItems[highlightedIndex] ?? filteredItems[0]);
                setOpen(false);
                setIsBrowsingOnFocus(false);
                return;
              }
              if (createAction?.visible) {
                setOpen(false);
                setIsBrowsingOnFocus(false);
                window.requestAnimationFrame(() => createAction.onClick());
              }
            }
          }}
        />
        {inline ? (
          <span
            aria-hidden="true"
            className={cn(
              'pointer-events-none absolute top-1/2 -translate-y-1/2 text-slate-400',
              inputSize === 'sm' ? 'right-2.5' : 'right-3',
            )}
          >
            <CollapsibleChevron open={open} className="size-4 text-slate-400" />
          </span>
        ) : null}
      </div>

      {inline ? (
        <Collapsible open={open && hasContent}>
          <div
            ref={dropdownRef}
            className="mt-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg"
          >
            {listContent}
          </div>
        </Collapsible>
      ) : null}

      {overlayDropdown}

      {error ? <p className="mt-1 text-xs text-danger">{error}</p> : null}
    </div>
  );
}

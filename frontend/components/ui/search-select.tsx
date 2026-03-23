'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils/cn';

export type SearchSelectItem = {
  value: string;
  label: string;
  searchText?: string;
  badge?: string;
  badgeClassName?: string;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
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
  showAllOnFocus = false,
  limit = 8,
  disabled = false,
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
  showAllOnFocus?: boolean;
  limit?: number;
  disabled?: boolean;
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

  const dropdown = open && (filteredItems.length > 0 || createAction?.visible) && dropdownStyle && portalReady
    ? createPortal(
        <div
          ref={dropdownRef}
          className="fixed z-[9999] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
          style={{
            top: `${dropdownStyle.top}px`,
            left: `${dropdownStyle.left}px`,
            width: `${dropdownStyle.width}px`,
          }}
        >
          {filteredItems.length > 0 ? (
            <div className="max-h-60 overflow-auto py-1">
              {filteredItems.map((item, index) => {
                const isSelected = selectedValue === item.value;
                const isHighlighted = highlightedIndex === index;

                return (
                  <button
                    key={item.value}
                    type="button"
                    className={cn(
                      'flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition',
                      isHighlighted ? 'bg-slate-100' : 'hover:bg-slate-50',
                    )}
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
        </div>,
        document.body,
      )
    : null;

  return (
    <div ref={rootRef} className={cn('relative overflow-visible', widthClassName)}>
      <Label htmlFor={id}>{label}</Label>
      <Input
        ref={inputRef}
        id={id}
        className="h-9"
        value={query}
        disabled={disabled}
        autoComplete="off"
        placeholder={placeholder}
        onFocus={() => {
          setIsBrowsingOnFocus(true);
          setOpen(true);
          updateDropdownPosition();
        }}
        onClick={() => {
          setIsBrowsingOnFocus(true);
          setOpen(true);
          updateDropdownPosition();
        }}
        onChange={(event) => {
          setIsBrowsingOnFocus(false);
          setQuery(event.target.value);
          setOpen(true);
          updateDropdownPosition();
        }}
        onKeyDown={(event) => {
          if (disabled) return;

          if (!open && (event.key === 'ArrowDown' || event.key === 'Enter')) {
            event.preventDefault();
            setIsBrowsingOnFocus(true);
            setOpen(true);
            updateDropdownPosition();
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

      {dropdown}

      {error ? <p className="mt-1 text-xs text-danger">{error}</p> : null}
    </div>
  );
}

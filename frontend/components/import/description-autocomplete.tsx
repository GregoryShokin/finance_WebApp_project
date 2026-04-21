'use client';

import { useLayoutEffect, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils/cn';
import type { CategoryRule } from '@/types/category-rule';

function scoreRule(rule: CategoryRule, rowNormalizedDesc: string): number {
  if (!rowNormalizedDesc) return 0;
  const rowWords = rowNormalizedDesc.split(/\s+/).filter(Boolean);
  return rowWords.filter((word) => rule.normalized_description.includes(word)).length;
}

function getSuggestions(rules: CategoryRule[], value: string, rowNormalizedDesc: string): CategoryRule[] {
  const query = value.trim().toLowerCase();
  const filtered = query
    ? rules.filter((rule) => rule.user_label.toLowerCase().includes(query))
    : rules;

  return filtered
    .map((rule) => ({ rule, score: scoreRule(rule, rowNormalizedDesc) }))
    .sort((a, b) => b.score - a.score || b.rule.confirms - a.rule.confirms)
    .slice(0, 8)
    .map(({ rule }) => rule);
}

export function DescriptionAutocomplete({
  value,
  onChange,
  rowNormalizedDescription,
  rules,
}: {
  value: string;
  onChange: (value: string) => void;
  rowNormalizedDescription: string;
  rules: CategoryRule[];
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [dropdownStyle, setDropdownStyle] = useState<{ top: number; left: number; width: number } | null>(null);
  const [portalReady, setPortalReady] = useState(false);

  const suggestions = getSuggestions(rules, open ? value : '', rowNormalizedDescription);

  const updatePosition = () => {
    if (!inputRef.current) return;
    const rect = inputRef.current.getBoundingClientRect();
    setDropdownStyle({ top: rect.bottom + 4, left: rect.left, width: rect.width });
  };

  useEffect(() => {
    setPortalReady(true);
  }, []);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [suggestions.length, open]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open, suggestions.length]);

  useEffect(() => {
    if (!open) return;
    const handle = () => updatePosition();
    window.addEventListener('resize', handle);
    window.addEventListener('scroll', handle, true);
    return () => {
      window.removeEventListener('resize', handle);
      window.removeEventListener('scroll', handle, true);
    };
  }, [open]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (inputRef.current?.contains(target)) return;
      if (dropdownRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, []);

  const dropdown =
    open && suggestions.length > 0 && dropdownStyle && portalReady
      ? createPortal(
          <div
            ref={dropdownRef}
            className="fixed z-[9999] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
            style={{ top: `${dropdownStyle.top}px`, left: `${dropdownStyle.left}px`, width: `${dropdownStyle.width}px` }}
          >
            <div className="max-h-60 overflow-auto py-1">
              {suggestions.map((rule, index) => (
                <button
                  key={rule.id}
                  type="button"
                  className={cn(
                    'flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition',
                    highlightedIndex === index ? 'bg-slate-100' : 'hover:bg-slate-50',
                  )}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onChange(rule.user_label);
                    setOpen(false);
                  }}
                >
                  <span className="truncate font-medium text-slate-900">{rule.user_label}</span>
                  {rule.original_description ? (
                    <span className="truncate text-xs text-slate-400">{rule.original_description}</span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="relative">
      <Input
        ref={inputRef}
        value={value}
        autoComplete="off"
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          updatePosition();
        }}
        onFocus={() => {
          setOpen(true);
          updatePosition();
        }}
        onKeyDown={(e) => {
          if (!open || suggestions.length === 0) return;
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHighlightedIndex((prev) => (prev + 1) % suggestions.length);
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHighlightedIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
          } else if (e.key === 'Enter') {
            e.preventDefault();
            const selected = suggestions[highlightedIndex];
            if (selected) {
              onChange(selected.user_label);
              setOpen(false);
            }
          }
        }}
      />
      {dropdown}
    </div>
  );
}

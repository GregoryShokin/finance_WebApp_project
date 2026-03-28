"use client";

import { useCallback, useEffect, useRef, useState } from 'react';

type PendingMap = Record<number, boolean>;

export function useDelayedDelete(delayMs = 3000) {
  const [pendingIds, setPendingIds] = useState<PendingMap>({});
  const timersRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  const clearPending = useCallback((id: number) => {
    const timer = timersRef.current[id];
    if (timer) {
      clearTimeout(timer);
      delete timersRef.current[id];
    }

    setPendingIds((prev) => {
      if (!prev[id]) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const scheduleDelete = useCallback((id: number, onDelete: () => void) => {
    const existingTimer = timersRef.current[id];
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    setPendingIds((prev) => ({ ...prev, [id]: true }));
    timersRef.current[id] = setTimeout(() => {
      delete timersRef.current[id];
      setPendingIds((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      onDelete();
    }, delayMs);
  }, [delayMs]);

  const isPending = useCallback((id: number | null | undefined) => {
    if (!id) return false;
    return Boolean(pendingIds[id]);
  }, [pendingIds]);

  useEffect(() => {
    return () => {
      Object.values(timersRef.current).forEach((timer) => clearTimeout(timer));
      timersRef.current = {};
    };
  }, []);

  return {
    pendingIds,
    isPending,
    scheduleDelete,
    cancelDelete: clearPending,
    clearPending,
  };
}

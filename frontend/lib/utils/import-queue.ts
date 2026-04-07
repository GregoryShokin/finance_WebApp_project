export type QueuedImportSession = {
  id: number;
  accountId?: string;
};

const IMPORT_QUEUE_STORAGE_KEY = 'financeapp.import-queue.ids.v1';
export const IMPORT_QUEUE_EVENT = 'financeapp:import-queue-changed';

function emitQueueChange() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(IMPORT_QUEUE_EVENT));
}

function normalizeEntries(entries: QueuedImportSession[]) {
  const unique = new Map<number, QueuedImportSession>();
  for (const entry of entries) {
    const id = Number(entry.id);
    if (!Number.isFinite(id) || id <= 0) continue;
    unique.set(id, {
      id,
      accountId: entry.accountId ? String(entry.accountId) : undefined,
    });
  }
  return [...unique.values()];
}

export function getQueuedImportSessions(): QueuedImportSession[] {
  if (typeof window === 'undefined') return [];

  try {
    const raw = window.localStorage.getItem(IMPORT_QUEUE_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    if (parsed.every((value) => typeof value === 'number')) {
      return normalizeEntries(parsed.map((id) => ({ id })));
    }

    return normalizeEntries(
      parsed
        .filter((value) => value && typeof value === 'object')
        .map((value) => ({
          id: Number((value as { id?: unknown }).id),
          accountId: (value as { accountId?: unknown }).accountId
            ? String((value as { accountId?: unknown }).accountId)
            : undefined,
        })),
    );
  } catch {
    return [];
  }
}

export function getQueuedImportSessionIds(): number[] {
  return getQueuedImportSessions().map((entry) => entry.id);
}

export function setQueuedImportSessions(entries: QueuedImportSession[]) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(IMPORT_QUEUE_STORAGE_KEY, JSON.stringify(normalizeEntries(entries)));
  emitQueueChange();
}

export function enqueueImportSession(entry: QueuedImportSession) {
  const current = getQueuedImportSessions();
  setQueuedImportSessions([...current, entry]);
}

export function dequeueImportSession(sessionId: number) {
  const current = getQueuedImportSessions();
  setQueuedImportSessions(current.filter((entry) => entry.id !== sessionId));
}

export function getQueuedImportSession(sessionId: number) {
  return getQueuedImportSessions().find((entry) => entry.id === sessionId);
}

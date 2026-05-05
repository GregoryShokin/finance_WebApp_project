/**
 * Client-side upload limits — must stay in sync with backend
 * `app/core/config.py:MAX_UPLOAD_SIZE_*_MB`. Mismatch leads to a confusing
 * UX: the client passes its check, the server returns 413 anyway.
 *
 * Values come from `NEXT_PUBLIC_MAX_UPLOAD_*_MB` so production can tune
 * the limit without a frontend rebuild — set both backend and frontend
 * env to the same number and redeploy in lockstep.
 */

export const UPLOAD_LIMITS_MB = {
  csv: Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_CSV_MB) || 10,
  xlsx: Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_XLSX_MB) || 10,
  pdf: Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_PDF_MB) || 25,
} as const;

export type UploadKind = keyof typeof UPLOAD_LIMITS_MB;

export const UPLOAD_ACCEPT_ATTR =
  '.csv,.xlsx,.pdf,' +
  'text/csv,' +
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,' +
  'application/pdf';

export function inferKindFromName(filename: string): UploadKind | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.csv')) return 'csv';
  if (lower.endsWith('.xlsx')) return 'xlsx';
  if (lower.endsWith('.pdf')) return 'pdf';
  return null;
}

export type UploadValidationResult =
  | { ok: true; kind: UploadKind }
  | { ok: false; reason: 'unknown_kind'; message: string }
  | { ok: false; reason: 'empty'; message: string }
  | { ok: false; reason: 'too_large'; message: string; kind: UploadKind; limitMb: number; actualMb: number };

export function validateUploadSize(file: File): UploadValidationResult {
  const kind = inferKindFromName(file.name);
  if (!kind) {
    return {
      ok: false,
      reason: 'unknown_kind',
      message: 'Поддерживаются только файлы CSV, XLSX, PDF.',
    };
  }
  // Catch zero-byte uploads early — saves a network round-trip to learn what
  // the backend already knows (`empty_file` → 415).
  if (file.size === 0) {
    return {
      ok: false,
      reason: 'empty',
      message: 'Файл пустой.',
    };
  }
  const limitMb = UPLOAD_LIMITS_MB[kind];
  const limitBytes = limitMb * 1024 * 1024;
  if (file.size > limitBytes) {
    const actualMb = Number((file.size / 1024 / 1024).toFixed(1));
    return {
      ok: false,
      reason: 'too_large',
      kind,
      limitMb,
      actualMb,
      message: `Файл ${actualMb} МБ превышает лимит ${limitMb} МБ для ${kind.toUpperCase()}.`,
    };
  }
  return { ok: true, kind };
}

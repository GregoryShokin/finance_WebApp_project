/**
 * Two formatters for backend 429 responses (`code: rate_limit_exceeded`),
 * one tone per UX context.
 *
 * The backend payload contract is fixed in `app/core/rate_limit.py`:
 *   { detail, code: 'rate_limit_exceeded', endpoint, retry_after_seconds }
 *
 *   - **auth** (`/auth/login`, `/auth/register`, `/auth/refresh`):
 *     Security context. Round retry to minutes — "47 seconds" reads as
 *     "try again right now" which is the wrong signal under brute-force
 *     protection. No retry counter, no retry-now CTA.
 *   - **upload** (`/imports/upload`, `/telegram/bot/upload`):
 *     Productivity context. The user is mid-flow and wants to continue;
 *     show seconds when small, minutes when ≥60s. Concrete numbers help
 *     them decide whether to wait or batch later.
 *
 * Source preference: `payload.retry_after_seconds` (structured, set by our
 * own handler). If somehow absent, fall back to the `Retry-After` HTTP header
 * if the caller chose to pass it. Final fallback is 60s — never "0" so the
 * UI never tells the user to "retry now" and immediately bounce again.
 */

export interface RateLimitPayload {
  detail?: string;
  code: 'rate_limit_exceeded';
  endpoint?: string;
  retry_after_seconds?: number;
}

const FALLBACK_SECONDS = 60;

function resolveRetrySeconds(payload: unknown, retryAfterHeader?: string | null): number {
  const fromPayload =
    typeof (payload as RateLimitPayload | undefined)?.retry_after_seconds === 'number'
      ? (payload as RateLimitPayload).retry_after_seconds!
      : null;
  if (fromPayload && fromPayload > 0) return fromPayload;

  if (retryAfterHeader) {
    const parsed = Number.parseInt(retryAfterHeader, 10);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return FALLBACK_SECONDS;
}

/**
 * Auth-context: minutes, rounded UP via Math.ceil. Floor of "0.5 min" reads
 * as "no wait" — ceil keeps the message honest.
 */
export function formatRateLimitErrorAuth(
  payload: unknown,
  retryAfterHeader?: string | null,
): string {
  const seconds = resolveRetrySeconds(payload, retryAfterHeader);
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  if (minutes === 1) {
    return 'Слишком много попыток. Подождите минуту.';
  }
  return `Слишком много попыток. Подождите ${minutes} мин.`;
}

/**
 * Upload-context: seconds when small (<60), minutes when ≥60. Plural-aware
 * fallback ("Подождите 1 мин" reads naturally; "Подождите 1 секунд" doesn't,
 * so we keep the noun fixed and only render the number).
 */
export function formatRateLimitErrorUpload(
  payload: unknown,
  retryAfterHeader?: string | null,
): string {
  const seconds = resolveRetrySeconds(payload, retryAfterHeader);
  if (seconds < 60) {
    return `Слишком много загрузок. Подождите ${seconds} сек.`;
  }
  const minutes = Math.ceil(seconds / 60);
  return `Слишком много загрузок. Подождите ${minutes} мин.`;
}

/** Shared predicate so callers don't all duplicate the `status === 429 && code === ...` check. */
export function isRateLimitError(status: number, payload: unknown): boolean {
  return (
    status === 429 &&
    typeof payload === 'object' &&
    payload !== null &&
    (payload as { code?: unknown }).code === 'rate_limit_exceeded'
  );
}

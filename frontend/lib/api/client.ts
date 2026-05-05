import { RETURN_TO_KEY } from '@/lib/auth/constants';
import { clearTokens, getAccessToken, getRefreshToken, setTokenPair } from '@/lib/auth/token';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

type RequestOptions = RequestInit & {
  auth?: boolean;
};

export class ApiError extends Error {
  status: number;
  detail: string;
  /** Full JSON payload from the response when the body parses as object.
   * Routes that emit structured errors (e.g. upload validator: `{detail, code,
   * max_size_mb, actual_size_mb, ...}`) put fields beyond `detail` here so
   * UI code can render them without re-parsing the response. */
  payload?: Record<string, unknown>;

  constructor(status: number, detail: string, payload?: Record<string, unknown>) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

// Singleton in-flight refresh — when N requests get 401 in parallel (common
// during the moderator's bulk PATCH stream), only one /auth/refresh fires
// and every caller awaits the same promise. Resolves to the new access token,
// or null if refresh failed (caller treats null as "give up, redirect").
let refreshPromise: Promise<string | null> | null = null;

function isRefreshOrLogoutPath(path: string) {
  return path.startsWith('/auth/refresh') || path.startsWith('/auth/logout');
}

function rememberReturnTo() {
  if (typeof window === 'undefined') return;
  // Don't capture /login or /register as a return target — would loop.
  const path = window.location.pathname + window.location.search;
  if (path.startsWith('/login') || path.startsWith('/register')) return;
  try {
    window.sessionStorage.setItem(RETURN_TO_KEY, path);
  } catch {
    // sessionStorage unavailable (private mode quota etc.) — silently skip.
  }
}

function redirectToLogin() {
  if (typeof window === 'undefined') return;
  rememberReturnTo();
  clearTokens();
  window.location.href = '/login';
}

async function performRefresh(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;

  try {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { access_token: string; refresh_token: string };
    setTokenPair(data);
    return data.access_token;
  } catch {
    return null;
  }
}

function ensureRefresh(): Promise<string | null> {
  if (refreshPromise === null) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function executeRequest(path: string, options: RequestOptions): Promise<Response> {
  const headers = new Headers(options.headers);
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;

  if (!headers.has('Content-Type') && options.body !== undefined && !isFormData) {
    headers.set('Content-Type', 'application/json');
  }

  if (options.auth !== false) {
    const token = getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }

  return fetch(`${API_URL}${path}`, { ...options, headers });
}

export async function apiClient<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await executeRequest(path, options);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Сетевой запрос не выполнен';
    throw new ApiError(0, `Не удалось выполнить запрос к API: ${message}`);
  }

  // 401 on an auth'd request → try one rotation, then retry the original.
  // Skip the retry path for /auth/refresh and /auth/logout themselves to
  // avoid recursion if the refresh endpoint itself returns 401.
  if (
    response.status === 401 &&
    options.auth !== false &&
    !isRefreshOrLogoutPath(path)
  ) {
    if (!getRefreshToken()) {
      redirectToLogin();
      throw new ApiError(401, 'Сессия истекла, войди заново');
    }

    const newAccess = await ensureRefresh();
    if (newAccess === null) {
      redirectToLogin();
      throw new ApiError(401, 'Сессия истекла, войди заново');
    }

    try {
      response = await executeRequest(path, options);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Сетевой запрос не выполнен';
      throw new ApiError(0, `Не удалось выполнить запрос к API: ${message}`);
    }
  }

  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    let detail = 'Unexpected API error';
    let payload: Record<string, unknown> | undefined;

    if (isJson) {
      const parsed = await response.json().catch(() => null);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
        const d = (parsed as { detail?: unknown }).detail;
        if (typeof d === 'string') detail = d;
      }
    } else {
      const text = await response.text().catch(() => '');
      if (text.trim()) detail = text.trim();
    }

    throw new ApiError(response.status, detail, payload);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (!isJson) {
    const text = await response.text().catch(() => '');
    return (text ? (text as T) : (undefined as T));
  }

  return response.json() as Promise<T>;
}

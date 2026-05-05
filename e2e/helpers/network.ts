import type { Page, Request, Response } from '@playwright/test';

export interface NetworkCall {
  method: string;
  url: string;
  request: Request;
  response: Response | null;
  startedAt: number;
  finishedAt: number | null;
}

/**
 * Subscribe to all requests on a page and collect them as they complete.
 *
 * Usage:
 * ```
 * const log = startNetworkLog(page);
 * await action();
 * expect(log.calls('POST', '/imports/upload')).toHaveLength(0);
 * ```
 *
 * The matcher accepts a substring against `pathname + search` — full URLs
 * with origin are inconvenient because the frontend's relative API base
 * varies across environments.
 */
export function startNetworkLog(page: Page): {
  calls: (method: string | null, urlSubstr: string | null) => NetworkCall[];
  all: () => NetworkCall[];
  clear: () => void;
} {
  const records: NetworkCall[] = [];

  page.on('request', req => {
    records.push({
      method: req.method(),
      url: req.url(),
      request: req,
      response: null,
      startedAt: Date.now(),
      finishedAt: null,
    });
  });

  page.on('response', resp => {
    const url = resp.url();
    const method = resp.request().method();
    // Match the most recent record for this (method, url) without a response
    for (let i = records.length - 1; i >= 0; i--) {
      const r = records[i];
      if (r.method === method && r.url === url && r.response === null) {
        r.response = resp;
        r.finishedAt = Date.now();
        break;
      }
    }
  });

  function pathOf(url: string): string {
    try {
      const u = new URL(url);
      return u.pathname + u.search;
    } catch {
      return url;
    }
  }

  return {
    calls(method, urlSubstr) {
      return records.filter(r => {
        if (method && r.method !== method.toUpperCase()) return false;
        if (urlSubstr && !pathOf(r.url).includes(urlSubstr)) return false;
        return true;
      });
    },
    all() {
      return records.slice();
    },
    clear() {
      records.length = 0;
    },
  };
}

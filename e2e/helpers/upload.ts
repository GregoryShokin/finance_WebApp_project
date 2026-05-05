import * as fs from 'fs';
import * as path from 'path';
import type { APIRequestContext, APIResponse } from '@playwright/test';

interface UploadOptions {
  /** Override the filename sent to the backend (default: basename of filePath) */
  filename?: string;
  /** Override Content-Type (default: inferred from extension) */
  contentType?: string;
  /** Append `?delimiter=...` query param (default backend value is ',') */
  delimiter?: string;
  /** Append `?force_new=true` to bypass dedup (Этап 0.5) */
  forceNew?: boolean;
}

/**
 * POST `/imports/upload` with an authenticated bearer token, a multipart file,
 * and optional query params. Returns the raw APIResponse — caller asserts.
 *
 * Why a custom helper instead of `api.post(... { multipart: { file: ... } })`:
 * Playwright's `multipart` shorthand is convenient but hides Content-Type
 * inference. Several validator scenarios require sending a file with a
 * deliberately-wrong content-type (e.g. .csv extension + PDF magic bytes),
 * so we want explicit control.
 */
export async function uploadFile(
  api: APIRequestContext,
  accessToken: string,
  filePath: string,
  opts: UploadOptions = {},
): Promise<APIResponse> {
  const buffer = fs.readFileSync(filePath);
  const filename = opts.filename ?? path.basename(filePath);
  const contentType = opts.contentType ?? inferMime(filename);

  const params: Record<string, string> = {};
  if (opts.delimiter) params.delimiter = opts.delimiter;
  if (opts.forceNew) params.force_new = 'true';

  return api.post('imports/upload', {
    headers: { Authorization: `Bearer ${accessToken}` },
    params,
    multipart: {
      file: { name: filename, mimeType: contentType, buffer },
    },
  });
}

/**
 * Same as `uploadFile` but the buffer is supplied directly — used when a
 * test constructs adversarial content in-memory (e.g. PDF magic bytes
 * wrapped in a `.csv`-named blob for the extension-mismatch test).
 */
export async function uploadBuffer(
  api: APIRequestContext,
  accessToken: string,
  buffer: Buffer,
  filename: string,
  contentType?: string,
): Promise<APIResponse> {
  return api.post('imports/upload', {
    headers: { Authorization: `Bearer ${accessToken}` },
    multipart: {
      file: { name: filename, mimeType: contentType ?? inferMime(filename), buffer },
    },
  });
}

function inferMime(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  switch (ext) {
    case 'pdf': return 'application/pdf';
    case 'csv': return 'text/csv';
    case 'xlsx': return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    case 'xls': return 'application/vnd.ms-excel';
    case 'exe': return 'application/octet-stream';
    default: return 'application/octet-stream';
  }
}

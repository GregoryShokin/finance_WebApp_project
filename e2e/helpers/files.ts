import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';

const E2E_ROOT = path.resolve(__dirname, '..');
const FIXTURES = path.join(E2E_ROOT, 'fixtures');
const TMP_DIR = path.join(E2E_ROOT, '.tmp');

/** Resolves a path inside `fixtures/statements/` (the symlink → ../../Bank-extracts). */
export function getStatementPath(filename: string): string {
  const p = path.join(FIXTURES, 'statements', filename);
  if (!fs.existsSync(p)) {
    throw new Error(
      `Statement fixture not found: ${p}\n` +
      `  → ensure the symlink exists: ln -s ../../Bank-extracts e2e/fixtures/statements`,
    );
  }
  return p;
}

/** Resolves a committed adversarial fixture (empty.csv, zip-bomb.xlsx, etc.). */
export function getAdversarialPath(filename: string): string {
  const p = path.join(FIXTURES, 'adversarial', filename);
  if (!fs.existsSync(p)) {
    throw new Error(`Adversarial fixture not found: ${p}`);
  }
  return p;
}

/** Resolves a synthetic statement fixture (tiny-valid.xlsx, etc.). */
export function getSyntheticPath(filename: string): string {
  const p = path.join(FIXTURES, 'statements-synthetic', filename);
  if (!fs.existsSync(p)) {
    throw new Error(`Synthetic fixture not found: ${p}`);
  }
  return p;
}

function ensureTmp(): void {
  if (!fs.existsSync(TMP_DIR)) {
    fs.mkdirSync(TMP_DIR, { recursive: true });
  }
}

/**
 * Generate a PDF blob of a target size on disk. Cached by content size — a
 * second call with the same size returns the same path without rewriting.
 *
 * The body is a minimal PDF header followed by random padding so the magic
 * bytes pass `PDF_MAGIC` detection but the file size exceeds caps. Random
 * bytes don't compress, so the on-disk size matches the requested size.
 */
export function generateLargePDF(sizeMB: number): string {
  ensureTmp();
  const target = path.join(TMP_DIR, `large-${sizeMB}mb.pdf`);
  if (fs.existsSync(target) && fs.statSync(target).size >= sizeMB * 1024 * 1024) {
    return target;
  }
  const header = Buffer.from('%PDF-1.4\n');
  const padding = crypto.randomBytes(sizeMB * 1024 * 1024 - header.length);
  fs.writeFileSync(target, Buffer.concat([header, padding]));
  return target;
}

/** Generate an arbitrary-size CSV-looking blob (printable ASCII). Used by the
 * middleware-cap test (0.2.9) where the body needs to exceed 30 MB to trigger
 * the global Content-Length check. */
export function generateLargeCSV(sizeMB: number): string {
  ensureTmp();
  const target = path.join(TMP_DIR, `large-${sizeMB}mb.csv`);
  if (fs.existsSync(target) && fs.statSync(target).size >= sizeMB * 1024 * 1024) {
    return target;
  }
  const line = 'date,description,amount\n';
  const repeat = Math.ceil((sizeMB * 1024 * 1024) / line.length);
  // Stream-write so we don't allocate the whole blob in RAM.
  const stream = fs.createWriteStream(target);
  for (let i = 0; i < repeat; i++) {
    stream.write(line);
  }
  stream.end();
  // Synchronous wait for stream completion.
  return new Promise<string>((resolve, reject) => {
    stream.on('finish', () => resolve(target));
    stream.on('error', reject);
  }) as unknown as string; // top-level await wrapper applied where called
}

/**
 * Async variant returning a Promise — preferred form for tests.
 */
export async function generateLargeCSVAsync(sizeMB: number): Promise<string> {
  ensureTmp();
  const target = path.join(TMP_DIR, `large-${sizeMB}mb.csv`);
  if (fs.existsSync(target) && fs.statSync(target).size >= sizeMB * 1024 * 1024) {
    return target;
  }
  return new Promise<string>((resolve, reject) => {
    const line = 'date,description,amount\n';
    const repeat = Math.ceil((sizeMB * 1024 * 1024) / line.length);
    const stream = fs.createWriteStream(target);
    let written = 0;
    function pump(): void {
      let ok = true;
      while (written < repeat && ok) {
        ok = stream.write(line);
        written++;
      }
      if (written < repeat) {
        stream.once('drain', pump);
      } else {
        stream.end();
      }
    }
    stream.on('finish', () => resolve(target));
    stream.on('error', reject);
    pump();
  });
}

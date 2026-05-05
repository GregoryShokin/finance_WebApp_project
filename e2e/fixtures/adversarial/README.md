# Adversarial fixtures

Files in this directory are committed to the repo and exist solely to
feed the upload-validator tests in `e2e/specs/02-upload-validation.spec.ts`.
They contain no real data.

## Contents

| File | Origin | Purpose |
|------|--------|---------|
| `empty.csv` | `: > empty.csv` | Zero-byte file → tests `code: empty_file` (415) |
| `fake-extension.exe` | seeded random bytes incl. nulls | `.exe` extension with binary content → tests `unsupported_upload_type` (415). Must contain 0x00 bytes so `is_plausibly_csv` rejects (a printable-ASCII fake-exe routes to `extension_content_mismatch` instead). |
| `cyrillic-cp1251.csv` | `e2e/scripts/build_*.py` (inline) | Russian CSV in CP1251 encoding → must pass validation (CSV negative-check tolerates high-bit bytes ≥0x80) |
| `zip-bomb.xlsx` | `e2e/scripts/build_zip_bomb.py` | Valid XLSX skeleton + 200 MB of zero bytes in `xl/worksheets/sheet1.xml` → tests `xlsx_decompression_too_large` (415) |

## Regenerating

The committed files should remain stable across runs to keep tests
deterministic. If you need to regenerate (e.g. after a validator change):

```bash
cd e2e
python3 scripts/build_zip_bomb.py            # → zip-bomb.xlsx
python3 -c "open('fixtures/adversarial/empty.csv','w').close()"
echo 'MZ this-is-text-not-an-exe' > fixtures/adversarial/fake-extension.exe
python3 -c "open('fixtures/adversarial/cyrillic-cp1251.csv','wb').write(open('fixtures/adversarial/cyrillic-cp1251.csv','rb').read() or 'дата,описание,сумма\\n2026-01-01,Покупка,100\\n'.encode('cp1251'))"
```

## Why no real malware

Synthetic fixtures only. The validator's job is to reject anything that
isn't a recognized statement format — it doesn't rely on signature
databases of known-malicious payloads. We stay within the
spirit of the project's threat model: user uploads their own statements,
not third-party-supplied files.

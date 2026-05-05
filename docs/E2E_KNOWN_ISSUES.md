# E2E suite — known issues / behavioural deviations

This file tracks deviations between the spec (`E2E_SMOKE_TZ.md` + QA brief)
and what the suite actually exercises. Per ТЗ §1: "Если найдёшь баг по
ходу — не фикси, оформляй как KNOWN_ISSUES запись и продолжай."

Each entry: severity, scenario(s) affected, description, current state of
the test, recommended fix.

---

## KI-01 — Frontend lacks pre-upload validation

**Severity:** medium (defence in depth)
**Affects:** Stage 0.2 scenarios 0.2.2 (size), 0.2.3 (extension), 0.2.4
(empty), 0.2.5 (binary content) — anywhere ТЗ §3.3 expected
"validation without a network request".

**What ТЗ assumes:** the frontend rejects files exceeding the upload cap
(`NEXT_PUBLIC_MAX_UPLOAD_*`), files with disallowed extensions, empty
files, and obvious-binary files BEFORE firing the multipart POST. The
spec wanted assertions of the form "no `/imports/upload` request fired".

**Actual frontend code** (`frontend/components/import/import-wizard.tsx:1097`):

```tsx
function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
  setSelectedFile(event.target.files?.[0] ?? null);
}

function handleUpload(...) {
  if (!selectedFile) {
    toast.error('Выбери CSV, XLSX или PDF');
    return;
  }
  // ... no size/type/content checks ...
  uploadMutation.mutate({ file: selectedFile, ... });
}
```

`<Input accept=".csv,.xlsx,.xls,.pdf" />` is a **picker hint only** — it does
not block the user from picking other types via drag-drop, and browsers do
not enforce it on form submit. Result: every file the user selects is
uploaded and validation happens server-side.

**Why this is mostly OK:** the backend (`app/services/upload_validator.py`)
enforces the same checks correctly — every adversarial file in the suite is
rejected with the right HTTP status and `code` field. The system's actual
security/correctness guarantees are intact.

**Why it still matters:**
- UX cost — users wait for a multi-MB upload to fail with a toast instead
  of getting feedback in <100 ms.
- Bandwidth cost — accidentally selecting a 100 MB blob blasts that across
  the wire before rejection. (The `MaxBodySizeMiddleware` mitigates only
  the headers-honest case; a chunked upload would still stream.)
- Network-call assertions in the QA brief (no `/imports/upload` fires) are
  not realistic against the current frontend.

**State of tests in `02-upload-validation.spec.ts`:** scenarios 0.2.2–0.2.5
are written to assert BACKEND rejection (network call DOES fire, response
is 413/415 with the matching `code`). When/if the frontend gains
pre-validation, these tests should be amended to assert `expect(uploadCalls).toHaveLength(0)`
in addition to backend rejection.

**Recommended fix (out of scope for the suite):** add a `validateFile`
helper in `lib/api/imports.ts` that checks `file.size`, `file.name`
extension, and a tiny FileReader probe for empty content. Wire it into
`handleFileChange` and `handleUpload`. Fronted tests should then assert
both: (a) toast appears immediately, (b) no network call fired.

---

## KI-02 — Mobile touch-target audit deferred

**Severity:** low (accessibility, not security)
**Affects:** Cross-cutting CC.2 (mobile smoke).

**State of tests:** `cc-cross-cutting.spec.ts:CC.2.*` runs three mobile
checks per page — console errors, horizontal overflow, sub-44px touch
targets. The first two are HARD asserts (test fails on violation). The
third is a SOFT assert: violations are written to
`test.info().annotations` (visible in the HTML report under the test row)
but do NOT fail the test.

**Why soft:** turning every sub-44px chip / icon into a hard failure would
block every smoke run while the UI is still under accessibility audit.
The report-only mode catches regressions ("we used to have N violations,
now we have N+5") without blocking unrelated work.

**To opt an element out** (legitimate inline icon inside a larger
clickable area): set `data-allow-small-touch="true"` on the offending
DOM node. The CC.2 query skips those.

**Recommended fix:** during the dedicated accessibility audit
(post-MVP), turn the soft assert hard, and either upsize all flagged
elements or tag them with `data-allow-small-touch`.

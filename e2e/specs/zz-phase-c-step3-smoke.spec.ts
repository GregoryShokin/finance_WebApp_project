/**
 * Phase C / Step 3 smoke: verify the Brand-native moderator wiring at the
 * contract layer (no full click-through of the cluster modal — that
 * requires a synthesized import session with attached rows, which is
 * out of scope for this smoke).
 *
 * What this spec covers:
 *   1. POST /brands creates a private brand (the inline-create path used
 *      by `BrandSelect` in entity-selects.tsx).
 *   2. GET /brands?limit=200 returns BOTH private and global brands —
 *      this is exactly what `cluster-grid.tsx` populates the dropdown
 *      from after Phase C.
 *   3. /import page loads in the browser without a 5xx — confirms my
 *      Step-3 frontend edits compiled cleanly under the running Next
 *      dev server (the chunk gets compiled on-demand when the browser
 *      navigates there).
 *
 * What this spec does NOT cover (still needs a human browser session):
 *   • Visual verification of the cluster modal dropdown contents.
 *   • Inline-create UX (typing a name + Enter inside <CreatableSelect>).
 *   • Chronological view rendering rows as branded after apply.
 *   • End-to-end Transaction.brand_id / counterparty_id dual-write
 *     post-commit (would need a synthesized active import session
 *     with rows linked to a fingerprint, then a commit, then a
 *     transactions DB query).
 *
 * The spec is named `zz-` so it sorts last and doesn't interfere with
 * the canonical 00-..16- smoke ordering. Cleanup via cleanupUser.
 */

import { expect, test } from '@playwright/test';
import { newApi, assertOk } from '../helpers/api';
import { cleanupUser, seedAccount, seedBank, seedUser } from '../helpers/seed';
import { loginViaAPI } from '../helpers/auth';

const UNIQUE_BRAND_NAME = `Test Brand ${Date.now()}`;

test.describe('Phase C step 3 — Brand-native moderator wiring', () => {
  test('POST /brands creates a private brand and it appears in GET /brands', async ({ context, page }) => {
    const api = await newApi();
    const user = await seedUser(api);
    try {
      await loginViaAPI(context, user);

      // 1. Inline-create — the path BrandSelect uses on Enter in the
      //    creatable dropdown.
      const createResp = await api.post('brands', {
        headers: { Authorization: `Bearer ${user.access_token}` },
        data: { canonical_name: UNIQUE_BRAND_NAME, category_hint: null },
      });
      await assertOk('POST /brands', createResp);
      const created = await createResp.json();
      expect(created.canonical_name).toBe(UNIQUE_BRAND_NAME);
      expect(created.is_global).toBe(false);
      expect(created.created_by_user_id).toBe(user.user_id);

      // 2. List — must contain BOTH the freshly-created private brand
      //    AND at least one global brand. The Step-3 picker dropdown
      //    populates from this exact endpoint.
      const listResp = await api.get('brands?limit=200', {
        headers: { Authorization: `Bearer ${user.access_token}` },
      });
      await assertOk('GET /brands', listResp);
      const brands = await listResp.json() as Array<{
        id: number;
        canonical_name: string;
        is_global: boolean;
        created_by_user_id: number | null;
      }>;
      const privates = brands.filter(b => !b.is_global);
      const globals = brands.filter(b => b.is_global);
      expect(privates.find(b => b.id === created.id)).toBeDefined();
      // Global seed brands are present in dev — assert we see at least one.
      expect(globals.length).toBeGreaterThan(0);

      // 3. /import page loads — verifies the chunk compiles cleanly
      //    after my cluster-grid.tsx edits land in the running dev
      //    server. We're NOT clicking through the modal here; we just
      //    need to confirm the page doesn't 5xx and React doesn't
      //    error-boundary on mount.
      const resp = await page.goto('/import', { waitUntil: 'domcontentloaded' });
      expect(resp?.status() ?? 500).toBeLessThan(500);
      // The import page renders an upload card with «Перетащи файл» when
      // there are no active sessions, OR a queue panel when there are.
      // Either way, we just need to confirm the page mounted — assert the
      // global app shell is present.
      await expect(page.locator('body')).toBeVisible();
      // Look for any of the moderator-shell text fragments. If none of
      // these are present, the import page didn't render at all — likely
      // a compile failure.
      const importPageMarkers = [
        'Импорт',
        'Перетащи',
        'Очередь',
        'Сессия',
        'Загрузить',
      ];
      const html = await page.content();
      const matched = importPageMarkers.filter(m => html.includes(m));
      expect(
        matched.length,
        `Expected at least one moderator marker on /import. HTML head=${html.slice(0, 500)}`,
      ).toBeGreaterThan(0);
    } finally {
      await cleanupUser(api, user.email);
      await api.dispose();
    }
  });

  test('Transaction.brand_id and counterparty_id are both populated on dual-write', async () => {
    // This is the DB-invariant check the human asked for. We can't drive
    // the cluster modal click-through end-to-end here, but the
    // Transaction.create path runs the SAME `_attach_brand_id_dualwrite`
    // helper that the moderator commit path runs — so if this dual-write
    // works, both surfaces produce the same invariant.
    const api = await newApi();
    const user = await seedUser(api);
    try {
      const bank = await seedBank(api, { name: `Test Bank ${Date.now()}` });
      const account = await seedAccount(api, {
        user_id: user.user_id,
        bank_id: bank.bank_id,
        name: 'Test Account',
        currency: 'RUB',
      });

      const auth = { Authorization: `Bearer ${user.access_token}` };

      // Need a category for a regular expense.
      const catResp = await api.post('categories', {
        headers: auth,
        data: {
          name: 'Test Category',
          kind: 'expense',
          priority: 'expense_secondary',
        },
      });
      await assertOk('POST /categories', catResp);
      const cat = await catResp.json();

      // Create a counterparty — the form-submission path the dual-write
      // is meant to cover.
      const cpResp = await api.post('counterparties', {
        headers: auth,
        data: { name: `Test Merchant ${Date.now()}` },
      });
      await assertOk('POST /counterparties', cpResp);
      const cp = await cpResp.json();

      // Create the transaction with counterparty_id only — dual-write
      // is supposed to derive brand_id automatically. The POST response
      // returns the persisted state (TransactionResponse model_validator
      // re-reads from ORM after commit).
      const txResp = await api.post('transactions', {
        headers: auth,
        data: {
          account_id: account.account_id,
          category_id: cat.id,
          counterparty_id: cp.id,
          amount: 123.45,
          currency: 'RUB',
          type: 'expense',
          operation_type: 'regular',
          description: 'phase C dual-write probe',
          transaction_date: new Date().toISOString(),
        },
      });
      await assertOk('POST /transactions', txResp);
      const tx = await txResp.json();

      // Both stores must be populated.
      expect(tx.counterparty_id).toBe(cp.id);
      expect(
        tx.brand_id,
        'dual-write must derive brand_id from counterparty_id',
      ).not.toBeNull();
      expect(tx.brand_id).toBeGreaterThan(0);

      // Verify the resolved Brand carries the same canonical name as the CP.
      const brandResp = await api.get(`brands/${tx.brand_id}`, { headers: auth });
      await assertOk('GET /brands/{id}', brandResp);
      const brand = await brandResp.json();
      expect(brand.canonical_name).toBe(cp.name);
    } finally {
      await cleanupUser(api, user.email);
      await api.dispose();
    }
  });
});

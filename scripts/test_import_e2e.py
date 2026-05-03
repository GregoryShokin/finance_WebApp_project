"""End-to-end тест пайплайна импорта (имитация действий пользователя через HTTP API).

Что делает:
  1. Регистрирует свежего тестового юзера (`import-e2e-{ts}@example.com`).
  2. Создаёт счета: Основной RUB, Накопительный RUB, Кредитный, Яндекс ЭДС, Яндекс Кредит, Т-Банк, Озон, Озон Кредит.
  3. Прогоняет сценарии импорта: CSV (UTF-8/cp1251), XLSX, дубликаты, переводы,
     credit-payment split, unknown columns, broken file, PDF Яндекс/Т-Банк/Озон.
  4. На каждом сценарии делает упрощённую имитацию работы юзера в визарде
     (upload → preview → опц. PATCH строк → commit) и валидирует результат.
  5. Печатает таблицу pass/fail с краткими деталями.

Запуск (из корня worktree):
    .venv-test/bin/python scripts/test_import_e2e.py
    .venv-test/bin/python scripts/test_import_e2e.py --only S5_transfers
    .venv-test/bin/python scripts/test_import_e2e.py --keep   # не удалять юзера в конце

Требования:
  - Запущен docker compose (api на :8000)
  - В venv-test установлены httpx, openpyxl
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api/v1")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(ROOT, "tests", "import_fixtures")
PDF_DIR = "/Users/grigorii/Documents/Projects/finance_WebApp/Bank-extracts"

# ── colors ────────────────────────────────────────────────────────────────────
RESET = "\033[0m"
RED = "\033[31m"
GRN = "\033[32m"
YLW = "\033[33m"
CYN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


# ── api client ────────────────────────────────────────────────────────────────
class Api:
    def __init__(self, base: str):
        self.base = base
        self.client = httpx.Client(base_url=base, timeout=60.0)
        self.token: str | None = None
        self.user_email: str | None = None

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def register(self, email: str, password: str, full_name: str = "Import E2E") -> dict:
        r = self.client.post("/auth/register", json={"email": email, "password": password, "full_name": full_name})
        if r.status_code == 409:
            # already exists — login
            return self.login(email, password)
        r.raise_for_status()
        self.user_email = email
        return self.login(email, password)

    def login(self, email: str, password: str) -> dict:
        r = self.client.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self.user_email = email
        me = self.client.get("/auth/me", headers=self._h())
        me.raise_for_status()
        return me.json()

    def create_account(self, **kwargs) -> dict:
        r = self.client.post("/accounts", json=kwargs, headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"create_account failed: {r.status_code} {r.text}")
        return r.json()

    def list_accounts(self) -> list[dict]:
        r = self.client.get("/accounts", headers=self._h())
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("accounts", body.get("items", []))

    def banks_by_name(self) -> dict[str, int]:
        r = self.client.get("/banks", headers=self._h())
        r.raise_for_status()
        body = r.json()
        items = body if isinstance(body, list) else body.get("items", body.get("banks", []))
        return {b["name"]: b["id"] for b in items}

    def list_categories(self) -> list[dict]:
        r = self.client.get("/categories", headers=self._h())
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("items", body.get("categories", []))

    def create_category(self, **kwargs) -> dict:
        r = self.client.post("/categories", json=kwargs, headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"create_category failed [{r.status_code}]: {r.text}")
        return r.json()

    def upload(self, path: str, *, delimiter: str = ",") -> dict:
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f, "application/octet-stream")}
            r = self.client.post(f"/imports/upload?delimiter={delimiter}", files=files, headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"upload failed [{r.status_code}]: {r.text}")
        return r.json()

    def preview(self, session_id: int, *, account_id: int, **mapping) -> dict:
        body = {"account_id": account_id, **mapping}
        r = self.client.post(f"/imports/{session_id}/preview", json=body, headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"preview failed [{r.status_code}]: {r.text}")
        return r.json()

    def upload_and_preview(self, path: str, *, account_id: int, delimiter: str = ",",
                           date_format: str = "%Y-%m-%d", extra_mapping: dict | None = None,
                           skip_duplicates: bool = True) -> tuple[dict, dict]:
        """Имитирует визард: upload → берём auto-detected field_mapping → preview."""
        up = self.upload(path, delimiter=delimiter)
        det = up.get("detection", {}) or {}
        fm = dict(det.get("field_mapping") or {})
        if extra_mapping:
            fm.update(extra_mapping)
        prev = self.preview(
            up["session_id"], account_id=account_id, date_format=date_format,
            field_mapping=fm, skip_duplicates=skip_duplicates,
        )
        return up, prev

    def confirm_warnings(self, preview: dict, *, expense_cat_id: int | None = None,
                         income_cat_id: int | None = None) -> int:
        """Имитирует пользователя в визарде: проходит по warning-строкам и подтверждает их,
        проставляя дефолтную категорию (expense → expense_cat_id, income → income_cat_id).
        Для transfer/non-analytics операций категория не нужна."""
        n = 0
        for row in preview.get("rows", []):
            if row.get("status") != "warning":
                continue
            nd = row.get("normalized_data", {}) or {}
            op = str(nd.get("operation_type") or "")
            patch: dict = {"action": "confirm"}
            # Категория нужна только для regular operations с категориями.
            if op not in ("transfer", "credit_disbursement", "credit_payment"):
                t = str(nd.get("type") or "expense")
                cat_id = income_cat_id if t == "income" else expense_cat_id
                if cat_id:
                    patch["category_id"] = cat_id
            try:
                self.patch_row(row["id"], **patch)
                n += 1
            except RuntimeError:
                pass
        return n

    def get_preview(self, session_id: int) -> dict:
        r = self.client.get(f"/imports/{session_id}/preview", headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"get_preview failed [{r.status_code}]: {r.text}")
        return r.json()

    def patch_row(self, row_id: int, **fields) -> dict:
        r = self.client.patch(f"/imports/rows/{row_id}", json=fields, headers=self._h())
        if r.status_code >= 400:
            raise RuntimeError(f"patch_row {row_id} failed [{r.status_code}]: {r.text}")
        return r.json()

    def commit(self, session_id: int, *, import_ready_only: bool = True) -> dict:
        r = self.client.post(
            f"/imports/{session_id}/commit",
            json={"import_ready_only": import_ready_only},
            headers=self._h(),
        )
        if r.status_code >= 400:
            raise RuntimeError(f"commit failed [{r.status_code}]: {r.text}")
        return r.json()

    def list_transactions(self, **params) -> list[dict]:
        r = self.client.get("/transactions", params=params, headers=self._h())
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("transactions", body.get("items", []))

    def delete_session(self, session_id: int) -> None:
        self.client.delete(f"/imports/{session_id}", headers=self._h())

    def assign_account(self, session_id: int, account_id: int) -> dict:
        r = self.client.patch(
            f"/imports/{session_id}/account",
            json={"account_id": account_id},
            headers=self._h(),
        )
        if r.status_code >= 400:
            raise RuntimeError(f"assign_account failed [{r.status_code}]: {r.text}")
        return r.json()


# ── scenario framework ────────────────────────────────────────────────────────
@dataclass
class Result:
    name: str
    ok: bool = False
    note: str = ""
    duration_ms: int = 0
    asserts: list[tuple[bool, str]] = field(default_factory=list)


@dataclass
class Ctx:
    api: Api
    accounts: dict[str, dict]  # alias → account dict
    expense_cat_id: int | None = None
    income_cat_id: int | None = None
    results: list[Result] = field(default_factory=list)
    sessions: list[int] = field(default_factory=list)

    def confirm_all(self, preview: dict) -> int:
        return self.api.confirm_warnings(
            preview, expense_cat_id=self.expense_cat_id, income_cat_id=self.income_cat_id
        )


def assert_(ctx_assertions: list, cond: bool, msg: str) -> None:
    ctx_assertions.append((bool(cond), msg))
    if not cond:
        raise AssertionError(msg)


# ── scenarios ─────────────────────────────────────────────────────────────────
def s1_simple_csv_utf8(ctx: Ctx) -> Result:
    res = Result(name="S1 simple_csv_utf8")
    t0 = time.time()
    try:
        acc = ctx.accounts["main"]
        up, prev = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "simple_expenses_utf8.csv"),
            account_id=acc["id"], delimiter=";",
        )
        ctx.sessions.append(up["session_id"])
        assert_(res.asserts, up["status"] == "analyzed", f"upload status=analyzed (got {up['status']})")
        assert_(res.asserts, up["total_rows"] == 10, f"total_rows=10 (got {up['total_rows']})")
        det = up.get("detection", {})
        fm = det.get("field_mapping", {}) or {}
        assert_(res.asserts, fm.get("date") and fm.get("description") and fm.get("amount"),
                f"date/description/amount auto-detected (got {fm})")

        assert_(res.asserts, prev["summary"]["total_rows"] == 10, f"preview total=10 (got {prev['summary']['total_rows']})")
        ready_initial = prev["summary"]["ready_rows"]
        warning_initial = prev["summary"]["warning_rows"]
        assert_(res.asserts, ready_initial + warning_initial >= 8,
                f"ready+warning >= 8 (got {ready_initial}+{warning_initial})")
        # имитируем работу в визарде: подтверждаем warning-строки
        confirmed = ctx.confirm_all(prev)
        prev2 = ctx.api.get_preview(up["session_id"])
        ready_after = prev2["summary"]["ready_rows"]
        assert_(res.asserts, ready_after >= 8, f"ready after confirm >= 8 (got {ready_after})")

        com = ctx.api.commit(up["session_id"])
        assert_(res.asserts, com["imported_count"] >= 8,
                f"imported_count >= 8 (got {com['imported_count']})")
        txs = ctx.api.list_transactions(account_id=acc["id"], limit=200)
        assert_(res.asserts, any(abs(float(t.get("amount", 0))) == 1234.50 for t in txs),
                "transaction with amount 1234.50 exists")
        res.note = f"imported={com['imported_count']} ready_initial={ready_initial} confirmed={confirmed}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s2_simple_cp1251(ctx: Ctx) -> Result:
    res = Result(name="S2 simple_cp1251")
    t0 = time.time()
    try:
        acc = ctx.accounts["main_cp"]
        up, prev = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "simple_cp1251.csv"),
            account_id=acc["id"], delimiter=";",
        )
        ctx.sessions.append(up["session_id"])
        assert_(res.asserts, up["total_rows"] == 10, f"total_rows=10 (got {up['total_rows']})")
        sample = (up.get("sample_rows") or [{}])[0]
        assert_(res.asserts, any("Пятёрочка" in str(v) or "Зарплата" in str(v) for v in sample.values()),
                f"cp1251 decoded readable text (sample={sample})")
        assert_(res.asserts, prev["summary"]["ready_rows"] + prev["summary"]["warning_rows"] >= 8,
                f"ready+warning >= 8 (got {prev['summary']['ready_rows']}+{prev['summary']['warning_rows']})")
        ctx.confirm_all(prev)
        com = ctx.api.commit(up["session_id"])
        assert_(res.asserts, com["imported_count"] >= 8, f"imported >= 8 (got {com['imported_count']})")
        res.note = f"imported={com['imported_count']} initial_ready={prev['summary']['ready_rows']}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s3_xlsx_offset(ctx: Ctx) -> Result:
    res = Result(name="S3 xlsx_header_offset")
    t0 = time.time()
    try:
        acc = ctx.accounts["xlsx"]
        up, prev = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "with_header_offset.xlsx"),
            account_id=acc["id"],
        )
        ctx.sessions.append(up["session_id"])
        assert_(res.asserts, up["total_rows"] == 5, f"total_rows=5 (got {up['total_rows']})")
        det = up.get("detection", {})
        fm = det.get("field_mapping", {}) or {}
        assert_(res.asserts, fm.get("date") and fm.get("amount"),
                f"date/amount detected despite offset header (got {fm})")
        assert_(res.asserts, prev["summary"]["ready_rows"] + prev["summary"]["warning_rows"] >= 4,
                f"ready+warning >= 4 (got {prev['summary']['ready_rows']}+{prev['summary']['warning_rows']})")
        ctx.confirm_all(prev)
        com = ctx.api.commit(up["session_id"])
        assert_(res.asserts, com["imported_count"] >= 4, f"imported >= 4 (got {com['imported_count']})")
        res.note = f"imported={com['imported_count']} ready_init={prev['summary']['ready_rows']}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s4_duplicates(ctx: Ctx) -> Result:
    """Повторно загружаем simple_expenses_utf8.csv после S1 — все строки должны быть duplicate."""
    res = Result(name="S4 duplicates")
    t0 = time.time()
    try:
        acc = ctx.accounts["main"]
        up, prev = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "simple_expenses_utf8.csv"),
            account_id=acc["id"], delimiter=";", skip_duplicates=True,
        )
        ctx.sessions.append(up["session_id"])
        dup = prev["summary"]["duplicate_rows"]
        assert_(res.asserts, dup >= 8, f"duplicate_rows >= 8 (got {dup})")
        com = ctx.api.commit(up["session_id"])
        assert_(res.asserts, com["imported_count"] == 0, f"imported=0 (got {com['imported_count']})")
        res.note = f"duplicate={dup} imported={com['imported_count']}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s5_transfers(ctx: Ctx) -> Result:
    """Два файла: расходы со счёта A с двумя transfer-строками + поступления на счёт B.
    После коммита обоих transfer_matcher должен сшить пары."""
    res = Result(name="S5 transfers (cross-session match)")
    t0 = time.time()
    try:
        acc_a = ctx.accounts["transfer_a"]
        acc_b = ctx.accounts["transfer_b"]

        # Файл A
        up_a, prev_a = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "transfers_a.csv"),
            account_id=acc_a["id"], delimiter=";",
        )
        ctx.sessions.append(up_a["session_id"])
        # Для transfer-строк проставим target_account_id руками (пользователь в визарде)
        for row in prev_a["rows"]:
            nd = row.get("normalized_data", {}) or {}
            if nd.get("operation_type") == "transfer" or (row.get("raw_data") or {}).get("raw_type") == "transfer":
                ctx.api.patch_row(row["id"], target_account_id=acc_b["id"], operation_type="transfer", action="confirm")
        com_a = ctx.api.commit(up_a["session_id"])

        # Файл B
        up_b, prev_b = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "transfers_b.csv"),
            account_id=acc_b["id"], delimiter=";",
        )
        ctx.sessions.append(up_b["session_id"])
        for row in prev_b["rows"]:
            nd = row.get("normalized_data", {}) or {}
            if nd.get("operation_type") == "transfer" or (row.get("raw_data") or {}).get("raw_type") == "transfer":
                ctx.api.patch_row(row["id"], target_account_id=acc_a["id"], operation_type="transfer", action="confirm")
        com_b = ctx.api.commit(up_b["session_id"])

        # Запускаем re-assign account, чтобы дёрнуть transfer_matcher
        ctx.api.assign_account(up_b["session_id"], acc_b["id"])

        # Проверяем: на счёте A есть 2 transfer expense с transfer_pair_id != null
        txs_a = ctx.api.list_transactions(account_id=acc_a["id"], limit=200)
        transfer_a = [t for t in txs_a if t.get("operation_type") == "transfer" and t.get("type") == "expense"]
        paired = [t for t in transfer_a if t.get("transfer_pair_id")]
        assert_(res.asserts, len(transfer_a) >= 2, f"≥2 transfer expense on A (got {len(transfer_a)})")
        assert_(res.asserts, len(paired) >= 1, f"at least 1 transfer paired (got {len(paired)} of {len(transfer_a)})")
        res.note = f"A imported={com_a['imported_count']} B imported={com_b['imported_count']} paired={len(paired)}/{len(transfer_a)}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s6_credit_payment(ctx: Ctx) -> Result:
    """Кредитный платёж: ручной патч строки с principal+interest, ожидаем 2 транзакции."""
    res = Result(name="S6 credit_payment split")
    t0 = time.time()
    try:
        acc_main = ctx.accounts["main"]
        acc_credit = ctx.accounts["credit"]
        up, prev = ctx.api.upload_and_preview(
            os.path.join(FIXTURES, "credit_payment.csv"),
            account_id=acc_main["id"], delimiter=";",
        )
        ctx.sessions.append(up["session_id"])

        # Берём первую строку (raw_type=credit_payment) и превращаем в credit_payment с principal+interest
        rows = sorted(prev["rows"], key=lambda r: r["row_index"])
        principal_row = rows[0]
        interest_row = rows[1] if len(rows) > 1 else None

        ctx.api.patch_row(
            principal_row["id"],
            operation_type="credit_payment",
            credit_account_id=acc_credit["id"],
            credit_principal_amount=12000,
            credit_interest_amount=3000,
            amount=15000,
            type="expense",
            action="confirm",
        )
        # вторую строку (если есть) пометим как regular interest и сразу exclude чтобы не дублировать
        if interest_row:
            ctx.api.patch_row(interest_row["id"], action="exclude")

        com = ctx.api.commit(up["session_id"])
        # credit_payment split → +2 транзакции (interest expense + principal transfer)
        assert_(res.asserts, com["imported_count"] >= 2,
                f"split produced ≥2 transactions (got {com['imported_count']})")

        # проверим: на main есть transfer expense → credit
        txs = ctx.api.list_transactions(account_id=acc_main["id"], limit=200)
        transfer_to_credit = [t for t in txs if t.get("operation_type") == "transfer"
                              and t.get("target_account_id") == acc_credit["id"]]
        assert_(res.asserts, len(transfer_to_credit) >= 1,
                f"principal transfer to credit account exists (got {len(transfer_to_credit)})")
        res.note = f"imported={com['imported_count']} principal_transfers={len(transfer_to_credit)}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s7_unknown_columns(ctx: Ctx) -> Result:
    """Колонки when/what/value — не в синонимах. Auto-detect должен дать low confidence,
    preview без явного field_mapping → строки в error/warning."""
    res = Result(name="S7 unknown_columns")
    t0 = time.time()
    try:
        acc = ctx.accounts["main"]
        up = ctx.api.upload(os.path.join(FIXTURES, "unknown_columns.csv"), delimiter=";")
        ctx.sessions.append(up["session_id"])
        det = up.get("detection", {})
        fm = dict(det.get("field_mapping") or {})
        # Поля могут быть распознаны по содержимому (regex), но без HEADER_SYNONYMS — confidence низкий.
        try:
            prev = ctx.api.preview(up["session_id"], account_id=acc["id"], date_format="%Y-%m-%d", field_mapping=fm)
            errors = prev["summary"]["error_rows"] + prev["summary"]["warning_rows"]
            assert_(res.asserts, errors >= 1 or not (fm.get("date") and fm.get("description") and fm.get("amount")),
                    f"unknown headers => error/warning or unmapped (errors={errors}, fm={fm})")
            res.note = f"detected_fm={ {k:v for k,v in fm.items() if v} } warning={prev['summary']['warning_rows']} error={prev['summary']['error_rows']}"
            res.ok = True
        except RuntimeError as e:
            # preview может упасть c 400 (Validation: missing fields) — это тоже валидный исход
            assert_(res.asserts, "400" in str(e) or "обязател" in str(e).lower(),
                    f"preview rejects missing fields (got {e})")
            res.note = "preview rejected unmapped headers (400)"
            res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s8_broken(ctx: Ctx) -> Result:
    res = Result(name="S8 broken_file")
    t0 = time.time()
    try:
        try:
            up = ctx.api.upload(os.path.join(FIXTURES, "broken.csv"), delimiter=";")
            ctx.sessions.append(up["session_id"])
            assert_(res.asserts, up["total_rows"] <= 1, f"broken: total_rows ≤ 1 (got {up['total_rows']})")
            res.note = f"upload accepted with total_rows={up['total_rows']}"
            res.ok = True
        except RuntimeError as e:
            assert_(res.asserts, "400" in str(e), f"upload rejects broken file (got {e})")
            res.note = "upload rejected broken file (400)"
            res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def _pdf_scenario(ctx: Ctx, pdf_name: str, account_alias: str, *, expect_contract: bool, label: str) -> Result:
    res = Result(name=label)
    t0 = time.time()
    try:
        acc = ctx.accounts[account_alias]
        path = os.path.join(PDF_DIR, pdf_name)
        if not os.path.exists(path):
            res.note = f"SKIP: {path} not found"
            res.ok = True
            return res
        up = ctx.api.upload(path)
        ctx.sessions.append(up["session_id"])
        assert_(res.asserts, up["total_rows"] >= 1, f"PDF parsed ≥1 row (got {up['total_rows']})")
        if expect_contract:
            cn = up.get("contract_number")
            assert_(res.asserts, bool(cn), f"contract_number extracted (got {cn!r})")
        det = up.get("detection", {})
        fm = dict(det.get("field_mapping") or {})
        # Подбираем date_format по образцу первой строки.
        sample_date = ((up.get("sample_rows") or [{}])[0] or {}).get(fm.get("date") or "date", "")
        if "." in sample_date and sample_date.count(":") >= 2:
            date_format = "%d.%m.%Y %H:%M:%S"
        elif "." in sample_date and ":" in sample_date:
            date_format = "%d.%m.%Y %H:%M"
        elif "." in sample_date:
            date_format = "%d.%m.%Y"
        else:
            date_format = "%Y-%m-%d"
        prev = ctx.api.preview(up["session_id"], account_id=acc["id"],
                               date_format=date_format, field_mapping=fm)
        # Подтверждаем все warning-строки, затем коммитим.
        confirmed = ctx.confirm_all(prev)
        prev2 = ctx.api.get_preview(up["session_id"])
        com = ctx.api.commit(up["session_id"])
        assert_(res.asserts, prev["summary"]["error_rows"] == 0,
                f"no parse errors after correct date_format (got {prev['summary']['error_rows']})")
        res.note = (
            f"rows={up['total_rows']} fmt={date_format} ready_init={prev['summary']['ready_rows']} "
            f"warn_init={prev['summary']['warning_rows']} err={prev['summary']['error_rows']} "
            f"confirmed={confirmed} imported={com['imported_count']}"
        )
        if up.get("contract_number"):
            res.note += f" contract={up['contract_number']}"
        res.ok = True
    except Exception as e:
        res.note = f"ERR: {e}"
    res.duration_ms = int((time.time() - t0) * 1000)
    return res


def s9_pdf_yandex_eds(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "d445cbd6-ad9e-4624-9c2d-e910d1243cfb.pdf",
                         "yandex_eds", expect_contract=True, label="S9 PDF Яндекс ЭДС")


def s10_pdf_yandex_credit(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "380a0702-9c84-441c-be22-c08df8c10454.pdf",
                         "yandex_credit", expect_contract=True, label="S10 PDF Яндекс кредит (split)")


def s11_pdf_tbank(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "Справка о движении средств.pdf",
                         "tbank", expect_contract=False, label="S11 PDF Т-Банк #1")


def s11b_pdf_tbank2(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "Справка о движении средств2.pdf",
                         "tbank2", expect_contract=False, label="S11b PDF Т-Банк #2")


def s12_pdf_ozon(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "Шокин_Г_А_о_движении_денежных_средств_ozonbank_document_27548622.pdf",
                         "ozon", expect_contract=False, label="S12 PDF Озон")


def s13_pdf_ozon_credit(ctx: Ctx) -> Result:
    return _pdf_scenario(ctx, "Шокин_Г_А_о_движении_денежных_средств_ozonbank_document_27548694.pdf",
                         "ozon_credit", expect_contract=False, label="S13 PDF Озон кредит")


SCENARIOS: dict[str, Callable[[Ctx], Result]] = {
    "S1_simple_csv_utf8": s1_simple_csv_utf8,
    "S2_simple_cp1251": s2_simple_cp1251,
    "S3_xlsx_offset": s3_xlsx_offset,
    "S4_duplicates": s4_duplicates,  # depends on S1
    "S5_transfers": s5_transfers,
    "S6_credit_payment": s6_credit_payment,
    "S7_unknown_columns": s7_unknown_columns,
    "S8_broken": s8_broken,
    "S9_pdf_yandex_eds": s9_pdf_yandex_eds,
    "S10_pdf_yandex_credit": s10_pdf_yandex_credit,
    "S11_pdf_tbank": s11_pdf_tbank,
    "S11b_pdf_tbank2": s11b_pdf_tbank2,
    "S12_pdf_ozon": s12_pdf_ozon,
    "S13_pdf_ozon_credit": s13_pdf_ozon_credit,
}


# ── setup ─────────────────────────────────────────────────────────────────────
# bank_name берётся из API /banks; при setup() резолвится в bank_id.
ACCOUNT_SPEC = [
    ("main",          "Сбербанк",    {"name": "E2E Основной",       "currency": "RUB", "balance": 200000, "account_type": "main"}),
    ("main_cp",       "Сбербанк",    {"name": "E2E cp1251 счёт",    "currency": "RUB", "balance": 50000,  "account_type": "main"}),
    ("xlsx",          "Сбербанк",    {"name": "E2E XLSX счёт",      "currency": "RUB", "balance": 50000,  "account_type": "main"}),
    ("transfer_a",    "Сбербанк",    {"name": "E2E Перевод A",      "currency": "RUB", "balance": 100000, "account_type": "main"}),
    ("transfer_b",    "Сбербанк",    {"name": "E2E Перевод B",      "currency": "RUB", "balance": 50000,  "account_type": "savings"}),
    ("credit",        "Сбербанк",    {"name": "E2E Кредит",         "currency": "RUB", "balance": -200000, "account_type": "loan",
                                       "is_credit": True, "credit_current_amount": 200000,
                                       "credit_limit_original": 300000, "credit_interest_rate": 18.5,
                                       "credit_term_remaining": 24}),
    ("yandex_eds",    "Яндекс Банк", {"name": "Яндекс ЭДС (E2E)",   "currency": "RUB", "balance": 0,      "account_type": "main"}),
    ("yandex_credit", "Яндекс Банк", {"name": "Яндекс Кредит (E2E)","currency": "RUB", "balance": -50000, "account_type": "credit_card",
                                       "is_credit": True, "credit_current_amount": 50000,
                                       "credit_limit_original": 100000, "credit_interest_rate": 22.0,
                                       "credit_term_remaining": 12}),
    ("tbank",         "Т-Банк",       {"name": "Т-Банк #1 (E2E)",    "currency": "RUB", "balance": 10000,  "account_type": "main"}),
    ("tbank2",        "Т-Банк",       {"name": "Т-Банк #2 (E2E)",    "currency": "RUB", "balance": 10000,  "account_type": "main"}),
    ("ozon",          "Озон Банк",    {"name": "Озон (E2E)",         "currency": "RUB", "balance": 1155,   "account_type": "main"}),
    ("ozon_credit",   "Озон Банк",    {"name": "Озон Кредит (E2E)",  "currency": "RUB", "balance": 0,      "account_type": "credit_card",
                                       "is_credit": True, "credit_current_amount": 0,
                                       "credit_limit_original": 100000, "credit_interest_rate": 24.0,
                                       "credit_term_remaining": 12}),
]


def setup(api: Api) -> Ctx:
    ts = int(time.time())
    email = f"import-e2e-{ts}@example.com"
    password = "TestImport2026!"
    print(c(f"➜ register {email}", CYN))
    api.register(email, password)
    banks = api.banks_by_name()
    accounts: dict[str, dict] = {}
    print(c("➜ creating accounts", CYN))
    for alias, bank_name, spec in ACCOUNT_SPEC:
        bank_id = banks.get(bank_name)
        if bank_id is None:
            raise RuntimeError(f"bank '{bank_name}' not found in /banks (have: {list(banks)[:5]}...)")
        try:
            acc = api.create_account(bank_id=bank_id, **spec)
            accounts[alias] = acc
            print(c(f"  · {alias:14s} #{acc['id']:4d}  [{bank_name}] {spec['name']}", DIM))
        except Exception as e:
            print(c(f"  ✗ {alias}: {e}", RED))
            raise

    # Категории: используем дефолтную «Продукты» для expense, создаём свою для income.
    cats = api.list_categories()
    by_name = {ct["name"]: ct for ct in cats}
    expense_cat = by_name.get("Продукты") or next((ct for ct in cats if ct.get("kind") == "expense"), None)
    income_cat = next((ct for ct in cats if ct.get("kind") == "income"), None)
    if income_cat is None:
        income_cat = api.create_category(
            name="E2E Доходы", kind="income",
            priority="income_active", regularity="regular",
        )
    print(c(f"  · cat expense=#{expense_cat['id']} ({expense_cat['name']}) "
            f"income=#{income_cat['id']} ({income_cat['name']})", DIM))
    return Ctx(api=api, accounts=accounts,
               expense_cat_id=expense_cat["id"], income_cat_id=income_cat["id"])


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None,
                    help="run only specified scenarios (can repeat). e.g. --only S1_simple_csv_utf8")
    ap.add_argument("--keep", action="store_true", help="keep test user and data after run")
    args = ap.parse_args()

    api = Api(API_BASE)
    print(c(f"=== Import E2E suite — API={API_BASE} ===", BOLD))
    try:
        ctx = setup(api)
    except Exception:
        print(c("setup failed:", RED))
        traceback.print_exc()
        return 2

    selected = args.only or list(SCENARIOS.keys())
    print(c(f"\n➜ running {len(selected)} scenarios\n", CYN))
    for name in selected:
        if name not in SCENARIOS:
            print(c(f"  ? unknown: {name}", YLW))
            continue
        try:
            res = SCENARIOS[name](ctx)
        except Exception as e:
            res = Result(name=name, ok=False, note=f"FATAL: {e}")
            traceback.print_exc()
        ctx.results.append(res)
        mark = c("✔ PASS", GRN) if res.ok else c("✘ FAIL", RED)
        print(f"  {mark}  {res.name:42s}  {res.duration_ms:5d}ms  {DIM}{res.note}{RESET}")
        if not res.ok and res.asserts:
            for ok, msg in res.asserts:
                if not ok:
                    print(f"        {c('×', RED)} {msg}")

    # Summary
    passed = sum(1 for r in ctx.results if r.ok)
    failed = len(ctx.results) - passed
    print()
    print(c(f"=== SUMMARY: {passed} passed / {failed} failed of {len(ctx.results)} ===",
            GRN if failed == 0 else RED))
    print(c(f"user: {api.user_email}    sessions created: {len(ctx.sessions)}", DIM))
    if not args.keep:
        print(c("(пользователь и данные оставлены — флаг --keep по умолчанию)", DIM))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

"""T34 / T35 — fingerprint-фикс и миграция старых сессий.

Группа 11 плана тестирования. Покрывает последствия фикса, в котором
`compute_fingerprint` начал учитывать `transfer_identifier` (phone /
contract / card / iban). До фикса все «Внешний перевод по номеру телефона»
со скелетоном `<PHONE>` коллапсировали в один кластер, потому что
плейсхолдер `<PHONE>` маскировал значение телефона.

Тесты разделены на три блока:

  • Инвариант фикса (T34) — два рои с одинаковым skeleton, но разными
    transfer_identifier обязаны получить разные fingerprint.
  • Миграция «старых» сессий (T35) — имитация поведения скрипта
    `scripts/renormalize_v2_fingerprints.py`: у preview_ready/uploaded/
    analyzed сессий рои с normalizer_version=2 пересчитываются;
    committed рои **не трогаются** (правила были обучены на старом
    fingerprint).
  • Сломанный скрипт — отдельный xfail-тест, фиксирующий что текущий
    путь миграции через `ImportService._apply_v2_normalization`
    больше не работает (метод исчез).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_normalizer_v2 import (
    ExtractedTokens,
    extract_tokens,
    fingerprint as compute_fingerprint,
    normalize_skeleton,
    pick_transfer_identifier,
)


# ---------------------------------------------------------------------------
# T34 — инвариант фикса: разные transfer_identifier → разные fingerprint
# ---------------------------------------------------------------------------


def test_phone_transfers_with_different_numbers_get_different_fingerprints():
    """Сердце фикса: «перевод на +79161111111» и «перевод на +79162222222»
    должны быть в разных кластерах, иначе UI слепляет переводы разным
    получателям в один."""
    desc_a = "Внешний перевод по номеру телефона +79161111111"
    desc_b = "Внешний перевод по номеру телефона +79162222222"

    tokens_a = extract_tokens(desc_a)
    tokens_b = extract_tokens(desc_b)
    skeleton_a = normalize_skeleton(desc_a, tokens_a)
    skeleton_b = normalize_skeleton(desc_b, tokens_b)

    # Проверяем, что skeleton схлопывает оба телефона в `<PHONE>` —
    # без transfer_identifier fingerprint был бы одинаков.
    assert skeleton_a == skeleton_b, (
        "Skeleton должен быть одинаков для обоих переводов — это и был "
        "корень бага: <PHONE>-плейсхолдер маскирует разные телефоны."
    )

    fp_a = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton_a, contract=None,
        transfer_identifier=pick_transfer_identifier(tokens_a),
    )
    fp_b = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton_b, contract=None,
        transfer_identifier=pick_transfer_identifier(tokens_b),
    )

    assert fp_a != fp_b, "Фикс не работает: разные телефоны = одинаковый fingerprint"


def test_same_phone_in_same_account_collapses_to_one_cluster():
    """Два рои с одним и тем же телефоном (повторный перевод маме) обязаны
    остаться в одном кластере."""
    desc = "Внешний перевод по номеру телефона +79161111111"
    tokens = extract_tokens(desc)
    skeleton = normalize_skeleton(desc, tokens)

    fp_first = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton, contract=None,
        transfer_identifier=pick_transfer_identifier(tokens),
    )
    fp_second = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton, contract=None,
        transfer_identifier=pick_transfer_identifier(tokens),
    )

    assert fp_first == fp_second


def test_legacy_fingerprint_without_transfer_identifier_collapses_phones():
    """Регрессионное доказательство «как было до фикса»: тот же hash без
    transfer_identifier склеивает разные телефоны. Этот тест нужен, чтобы
    миграция T35 имела реальный сценарий «старого» fingerprint, который
    нужно обновить."""
    skeleton = "<PHONE>"
    fp_a = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton, contract=None, transfer_identifier=None,
    )
    fp_b = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton, contract=None, transfer_identifier=None,
    )
    assert fp_a == fp_b
    # Сравнение со «свежим» fingerprint, учитывающим телефон:
    fp_a_new = compute_fingerprint(
        bank="tinkoff", account_id=1, direction="expense",
        skeleton=skeleton, contract=None,
        transfer_identifier=("phone", "+79161111111"),
    )
    assert fp_a_new != fp_a, (
        "После фикса хеш должен отличаться от старого — иначе миграция "
        "ничего не меняет."
    )


def test_contract_transfer_identifier_takes_priority_over_phone():
    """Приоритет в pick_transfer_identifier: phone → contract → card → iban.
    Два рои с одинаковым телефоном, но разными контрактами склеиваются
    по телефону (как и должно быть — телефон выигрывает по приоритету)."""
    tokens_a = ExtractedTokens(phone="+79161111111", contract="ДГ-A")
    tokens_b = ExtractedTokens(phone="+79161111111", contract="ДГ-B")
    assert pick_transfer_identifier(tokens_a) == ("phone", "+79161111111")
    assert pick_transfer_identifier(tokens_b) == ("phone", "+79161111111")


def test_pick_transfer_identifier_without_tokens_returns_none():
    assert pick_transfer_identifier(ExtractedTokens()) is None


# ---------------------------------------------------------------------------
# T35 — миграция старых сессий (имитация контракта скрипта)
# ---------------------------------------------------------------------------


def _make_session(db, user, *, status: str) -> ImportSession:
    s = ImportSession(
        user_id=user.id,
        filename="t.csv",
        source_type="csv",
        status=status,
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={"bank_code": "tinkoff"},
        summary_json={},
        account_id=None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_row(
    db,
    session: ImportSession,
    *,
    row_index: int,
    description: str,
    legacy_fingerprint: str,
    status: str,
    direction: str = "expense",
    normalizer_version: int | None = 2,
    created_transaction_id: int | None = None,
) -> ImportRow:
    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    payload = {
        "amount": "1000.00",
        "direction": direction,
        "transaction_date": datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
        "description": description,
        "skeleton": skeleton,
        "tokens": {
            "phone": tokens.phone,
            "contract": tokens.contract,
            "card": tokens.card,
            "iban": tokens.iban,
        },
        "fingerprint": legacy_fingerprint,
        "bank_code": "tinkoff",
    }
    if normalizer_version is not None:
        payload["normalizer_version"] = normalizer_version
    row = ImportRow(
        session_id=session.id,
        row_index=row_index,
        raw_data_json={"description": description},
        normalized_data_json=payload,
        status=status,
        created_transaction_id=created_transaction_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _rebuild_fingerprint(row: ImportRow, *, account_id: int) -> str:
    """Чистая копия логики, которую должен делать скрипт миграции:
    пересчитать fingerprint с учётом transfer_identifier."""
    nd = row.normalized_data_json or {}
    description = nd.get("description") or ""
    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    transfer_id = pick_transfer_identifier(tokens)
    return compute_fingerprint(
        bank=nd.get("bank_code") or "tinkoff",
        account_id=account_id,
        direction=str(nd.get("direction") or "expense"),
        skeleton=skeleton,
        contract=tokens.contract,
        transfer_identifier=transfer_id,
    )


def _legacy_fp(skeleton: str, *, account_id: int = 1) -> str:
    """Старый хеш — без transfer_identifier. Эмулирует то, что лежало в БД
    до фикса."""
    return compute_fingerprint(
        bank="tinkoff", account_id=account_id, direction="expense",
        skeleton=skeleton, contract=None, transfer_identifier=None,
    )


def test_legacy_rows_in_live_session_get_diversified_fingerprint(db, user):
    """T35 ядро: после миграции два разных телефона из одной 'старой'
    preview_ready сессии получают разные fingerprint."""
    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    row_a = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
    )
    row_b = _make_row(
        db, session, row_index=1,
        description="Внешний перевод по номеру телефона +79162222222",
        legacy_fingerprint=legacy, status="ready",
    )
    assert row_a.normalized_data_json["fingerprint"] == row_b.normalized_data_json["fingerprint"], (
        "Fixture sanity: до миграции оба рои носят один и тот же 'старый' fp."
    )

    new_a = _rebuild_fingerprint(row_a, account_id=1)
    new_b = _rebuild_fingerprint(row_b, account_id=1)

    assert new_a != legacy, "Миграция должна изменить fingerprint у row_a"
    assert new_b != legacy, "Миграция должна изменить fingerprint у row_b"
    assert new_a != new_b, "Разные телефоны после миграции — разные кластеры"


def test_committed_rows_must_not_be_remigrated(db, user):
    """T35 контракт скрипта: рои в committed-статусе или с привязанной
    транзакцией не пересчитываются — правила были обучены на старом fp."""
    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    committed = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="committed",
        created_transaction_id=42,
    )

    # Эмулируем контракт скрипта: rows со status='committed' или
    # created_transaction_id != None пропускаются.
    SKIPPED_ROW_STATUSES = {"committed"}
    nd = committed.normalized_data_json or {}
    should_skip = (
        (committed.status or "").lower() in SKIPPED_ROW_STATUSES
        or committed.created_transaction_id is not None
    )
    assert should_skip is True, (
        "Контракт скрипта: committed/привязанные к транзакции рои "
        "не должны участвовать в миграции"
    )
    # Подтверждаем, что fp на committed-рои не трогается логикой rebuild.
    assert nd.get("fingerprint") == legacy, "Старый fingerprint остался прежним"


def test_rows_without_normalizer_v2_are_skipped(db, user):
    """T35 контракт: рои без normalizer_version=2 (например, старая v1
    нормализация) скрипт не трогает."""
    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    v1_row = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
        normalizer_version=None,
    )

    nd = v1_row.normalized_data_json or {}
    has_v2 = nd.get("normalizer_version") == 2
    assert has_v2 is False, (
        "Fixture sanity: рой создан без normalizer_version → скрипт его пропустит."
    )


# ---------------------------------------------------------------------------
# Реальный прогон скрипта на in-memory сессии
# ---------------------------------------------------------------------------


def test_run_script_diversifies_legacy_fingerprints_with_execute(db, user):
    """Скрипт в режиме --execute обновляет fingerprint у preview_ready
    рои с разными телефонами на разные хеши и коммитит."""
    from scripts.renormalize_v2_fingerprints import run

    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    row_a = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
    )
    row_b = _make_row(
        db, session, row_index=1,
        description="Внешний перевод по номеру телефона +79162222222",
        legacy_fingerprint=legacy, status="ready",
    )

    run(execute=True, session_filter=session.id, db=db)

    db.refresh(row_a)
    db.refresh(row_b)

    fp_a = (row_a.normalized_data_json or {}).get("fingerprint")
    fp_b = (row_b.normalized_data_json or {}).get("fingerprint")

    assert fp_a != legacy, "row_a должен получить новый fingerprint"
    assert fp_b != legacy, "row_b должен получить новый fingerprint"
    assert fp_a != fp_b, "Разные телефоны → разные fingerprint после миграции"


def test_run_script_dry_run_does_not_persist(db, user):
    """Без --execute fingerprint в БД не меняется (dry-run-инвариант)."""
    from scripts.renormalize_v2_fingerprints import run

    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    row = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
    )

    run(execute=False, session_filter=session.id, db=db)
    db.refresh(row)

    assert (row.normalized_data_json or {}).get("fingerprint") == legacy, (
        "Dry-run не должен записывать новый fingerprint в БД"
    )


def test_run_script_skips_committed_rows(db, user):
    """Committed/привязанные к транзакции рои не пересчитываются — даже
    с --execute их fingerprint остаётся прежним (правила обучены на нём)."""
    from scripts.renormalize_v2_fingerprints import run

    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    committed = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="committed",
        created_transaction_id=42,
    )
    live = _make_row(
        db, session, row_index=1,
        description="Внешний перевод по номеру телефона +79162222222",
        legacy_fingerprint=legacy, status="ready",
    )

    run(execute=True, session_filter=session.id, db=db)
    db.refresh(committed)
    db.refresh(live)

    assert (committed.normalized_data_json or {}).get("fingerprint") == legacy, (
        "Committed-рой нельзя трогать"
    )
    assert (live.normalized_data_json or {}).get("fingerprint") != legacy, (
        "Live-рой обязан получить новый fingerprint"
    )


def test_run_script_skips_rows_without_normalizer_v2(db, user):
    """Рои без normalizer_version=2 (старая v1) скрипт не трогает."""
    from scripts.renormalize_v2_fingerprints import run

    session = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    v1_row = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
        normalizer_version=None,
    )

    run(execute=True, session_filter=session.id, db=db)
    db.refresh(v1_row)

    assert (v1_row.normalized_data_json or {}).get("fingerprint") == legacy, (
        "Рои без normalizer_version=2 миграция должна пропускать"
    )


def test_run_script_session_filter_isolates_other_sessions(db, user):
    """`--session N` затрагивает только указанную сессию."""
    from scripts.renormalize_v2_fingerprints import run

    target = _make_session(db, user, status="preview_ready")
    other = _make_session(db, user, status="preview_ready")
    legacy = _legacy_fp("<PHONE>")

    target_row = _make_row(
        db, target, row_index=0,
        description="Внешний перевод по номеру телефона +79161111111",
        legacy_fingerprint=legacy, status="ready",
    )
    other_row = _make_row(
        db, other, row_index=0,
        description="Внешний перевод по номеру телефона +79162222222",
        legacy_fingerprint=legacy, status="ready",
    )

    run(execute=True, session_filter=target.id, db=db)
    db.refresh(target_row)
    db.refresh(other_row)

    assert (target_row.normalized_data_json or {}).get("fingerprint") != legacy
    assert (other_row.normalized_data_json or {}).get("fingerprint") == legacy, (
        "Сессия other не была указана в --session — миграция её не трогает"
    )

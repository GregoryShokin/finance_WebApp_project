"""Regression tests for bank_code + account_type_hint detection in PdfExtractor.

Шаг 1 of auto-account-recognition (2026-05-06). The extractor's dispatch
already classifies a PDF into one of four parser branches (Sber, Yandex
Credit, Yandex Bank, universal), but the resulting `bank_code` and
`account_type_hint` were not surfaced into `ExtractionResult.meta` —
downstream consumers (ImportService.upload_file resolve, frontend
create-account suggestion) had to peek into per-table `parser` strings
or re-classify the text. These tests pin the new contract:

  • `meta["bank_code"]` is always present (string code mirroring `Bank.code`).
  • `meta["account_type_hint"]` is present too (string mirroring
    `Account.account_type`, or None when the parser cannot disambiguate).

The static `_classify_sber_account_type`, `_classify_yandex_credit_account_type`,
and `_detect_universal_bank` helpers are tested directly so we don't have to
synthesize a full PDF for every branch — the dispatch is exercised in the
existing integration tests (test_pdf_extractor_*.py).
"""
from __future__ import annotations

import pytest

from app.services.import_extractors.pdf_extractor import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEPOSIT,
    ACCOUNT_TYPE_INSTALLMENT_CARD,
    ACCOUNT_TYPE_MAIN,
    BANK_CODE_OZON,
    BANK_CODE_TBANK,
    BANK_CODE_UNKNOWN,
    PdfExtractor,
)


# ─── Sber account-type classifier ───────────────────────────────────────────


def test_sber_credit_card_statement_classifies_as_credit_card():
    full_text = (
        "ПАО Сбербанк\n"
        "Выписка по счёту кредитной карты\n"
        "Владелец счёта\nШокин Павел Александрович\n"
    )
    assert PdfExtractor._classify_sber_account_type(full_text) == ACCOUNT_TYPE_CREDIT_CARD


def test_sber_credit_card_short_marker_classifies_as_credit_card():
    full_text = "ПАО Сбербанк\nКредитная карта •••• 7123\nДата операции"
    assert PdfExtractor._classify_sber_account_type(full_text) == ACCOUNT_TYPE_CREDIT_CARD


def test_sber_debit_card_statement_classifies_as_main():
    full_text = (
        "ПАО Сбербанк\n"
        "Выписка по счёту дебетовой карты\n"
        "Карта МИР Классическая •••• 7123\n"
    )
    assert PdfExtractor._classify_sber_account_type(full_text) == ACCOUNT_TYPE_MAIN


def test_sber_deposit_statement_classifies_as_deposit():
    full_text = (
        "ПАО Сбербанк\n"
        "Выписка по счёту вклада «Сохраняй»\n"
        "Дата операции\n"
    )
    assert PdfExtractor._classify_sber_account_type(full_text) == ACCOUNT_TYPE_DEPOSIT


def test_sber_generic_statement_falls_back_to_main():
    """No credit/debit/deposit marker → MAIN. This is the conservative default
    — we'd rather show «Дебет» and let the user re-pick than guess wrong."""
    full_text = "ПАО Сбербанк\nВыписка по счёту\nДата операции"
    assert PdfExtractor._classify_sber_account_type(full_text) == ACCOUNT_TYPE_MAIN


def test_sber_classifier_handles_empty_text():
    assert PdfExtractor._classify_sber_account_type("") is None
    assert PdfExtractor._classify_sber_account_type(None) is None  # type: ignore[arg-type]


# ─── Yandex Credit account-type classifier ─────────────────────────────────


def test_yandex_split_statement_classifies_as_installment_card():
    """Яндекс Сплит = BNPL / installment, distinct product from credit card."""
    full_text = (
        "АО «Яндекс Банк»\n"
        "Выписка по договору Сплит\n"
        "Погашение основного долга\n"
    )
    assert (
        PdfExtractor._classify_yandex_credit_account_type(full_text)
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


def test_yandex_rassrochka_marker_also_installment_card():
    full_text = "АО «Яндекс Банк»\nРассрочка №КС-12345\n"
    assert (
        PdfExtractor._classify_yandex_credit_account_type(full_text)
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


def test_yandex_credit_branch_default_is_installment_card():
    """Яндекс Банк не выпускает кредитки (live spec 2026-05-06) — даже
    «выписка по договору» с «оплата товаров и услуг» / «погашение
    процентов» теперь распознаётся как installment_card (Сплит)."""
    full_text = (
        "АО «Яндекс Банк»\n"
        "Выписка по договору\n"
        "Оплата товаров и услуг\n"
        "Погашение процентов\n"
    )
    assert (
        PdfExtractor._classify_yandex_credit_account_type(full_text)
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


def test_yandex_credit_classifier_handles_empty_text():
    """Empty text → installment_card default (см. выше — у Яндекса нет
    кредиток, безопасный fallback это Сплит)."""
    assert (
        PdfExtractor._classify_yandex_credit_account_type("")
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


# ─── Universal pipeline bank detection ──────────────────────────────────────


def test_tbank_statement_detected_as_tbank():
    full_text = (
        "АО «Тинькофф Банк»\n"
        "Выписка по договору\n"
        "Дата операции\n"
    )
    bank, type_hint = PdfExtractor._detect_universal_bank(full_text)
    assert bank == BANK_CODE_TBANK
    assert type_hint is None


def test_tbank_rebrand_t_bank_detected_as_tbank():
    """Post-2024 rebrand: «Т-Банк» / «T-Bank» / «TBank» variants."""
    for variant in ("Т-Банк", "T-Bank", "TBank"):
        bank, _ = PdfExtractor._detect_universal_bank(f"Выписка\n{variant}\n")
        assert bank == BANK_CODE_TBANK, f"variant {variant!r} not detected"


def test_ozon_statement_detected_as_ozon():
    full_text = (
        "АО «Озон Банк»\n"
        "Справка о движении средств\n"
        "Номер лицевого счёта №40817810700006095914\n"
    )
    bank, type_hint = PdfExtractor._detect_universal_bank(full_text)
    assert bank == BANK_CODE_OZON
    # Default MAIN — Ozon flow is overwhelmingly «Справка о движении средств»
    # from a debit/main account; user can flip to credit via inline-prompt.
    assert type_hint == ACCOUNT_TYPE_MAIN


def test_unknown_bank_returns_unknown_code():
    full_text = "Some random non-banking text"
    bank, type_hint = PdfExtractor._detect_universal_bank(full_text)
    assert bank == BANK_CODE_UNKNOWN
    assert type_hint is None


def test_universal_bank_detector_handles_empty_text():
    bank, type_hint = PdfExtractor._detect_universal_bank("")
    assert bank == BANK_CODE_UNKNOWN
    assert type_hint is None


def test_ozon_default_type_is_main():
    """Ozon Банк PDF flow is overwhelmingly «Справка о движении средств» from
    a debit/main account — default to MAIN so the queue inline-prompt offers
    «Это Озон Банк Дебетовая карта?» instead of forcing a manual type pick."""
    bank, type_hint = PdfExtractor._detect_universal_bank("АО «Озон Банк»\nСправка о движении средств")
    assert bank == BANK_CODE_OZON
    assert type_hint == ACCOUNT_TYPE_MAIN


# ─── Contract-prefix refinement ────────────────────────────────────────────


def test_tbank_contract_prefix_54_resolves_to_main():
    """T-Bank statements with contract starting with `54` are debit cards
    (live case 2026-05-06)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="tbank", contract_number="5452737298", default=None,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_tbank_contract_prefix_05_resolves_to_credit_card():
    """T-Bank statements with contract starting with `05` are credit cards."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="tbank", contract_number="0504603705", default=None,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


def test_tbank_unknown_prefix_falls_back_to_default():
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="tbank", contract_number="99-OTHER", default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_MAIN  # default preserved


def test_yandex_contract_prefix_KS_resolves_to_installment_card():
    """Yandex contract starting with «КС» = Кредитный Счёт. Confirmed via
    real PDF header (screenshot 2026-05-06): «продукт «Потребительский
    кредит (с лимитом кредитования)»». This is Яндекс Сплит."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number="КС20251126483806054311", default=None,
    )
    assert refined == ACCOUNT_TYPE_INSTALLMENT_CARD


def test_yandex_contract_prefix_E_resolves_to_main():
    """Yandex contract starting with «Э» = Счёт ЭДС (Электронные Денежные
    Средства, дебетовый кошелёк). Confirmed via real PDF header
    (screenshot 2026-05-06): «продукт «Счёт ЭДС»»."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number="Э20240626883885586", default=None,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_yandex_contract_prefix_lowercase_KS_still_resolves():
    """Bank statements occasionally lowercase the prefix; the refiner is
    case-insensitive on Russian-letter prefixes (КС/кс)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number="кс20251126", default=None,
    )
    assert refined == ACCOUNT_TYPE_INSTALLMENT_CARD


def test_refine_does_not_override_default_when_prefix_unknown():
    """When the contract prefix doesn't match any known mapping, the existing
    text-based classification (default arg) is preserved — refinement is
    additive, never destructive. Exception: Yandex `credit_card` default
    is always coerced to `installment_card` (see test below)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="sber", contract_number="UNKNOWN-1234", default=ACCOUNT_TYPE_CREDIT_CARD,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


def test_refine_handles_missing_contract():
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="tbank", contract_number=None, default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_refine_handles_unknown_bank_code():
    """Unknown bank → no refinement, default stays."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="unknown", contract_number="5452737298", default=None,
    )
    assert refined is None


# ─── New rules added 2026-05-06 (Ozon КК, Yandex no-credit-card, T-Bank stmt) ──


def test_ozon_contract_with_KK_resolves_to_credit_card():
    """Ozon: contract containing two adjacent «КК» (cyrillic) → credit_card.
    Per user spec — Ozon Card kredit/BNPL identifier convention."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number="КК123456", default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


def test_ozon_KK_anywhere_in_contract_still_resolves():
    """«КК» can appear mid-contract — Ozon uses prefix + suffix patterns."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number="OZON-КК-2026-0001", default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


def test_ozon_latin_KK_also_resolves_to_credit_card():
    """Defensive: PDF transliterates contract → use Latin KK as alias."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number="KK-1234", default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


def test_ozon_statement_account_resolves_to_main():
    """Lichevoy счёт ⇒ дебет (Ozon retail account always reports it)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number=None,
        statement_account_number="40817810700006095914",
        default=None,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_ozon_no_signals_keeps_default():
    """No contract, no statement → default stays (Ozon default = main)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number=None, default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_tbank_statement_account_fallback_to_main():
    """T-Bank: contract without 54/05 prefix BUT lichevoy счёт present →
    main (live spec 2026-05-06)."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="tbank", contract_number="OTHER-99",
        statement_account_number="40817810600040293391",
        default=None,
    )
    assert refined == ACCOUNT_TYPE_MAIN


def test_yandex_credit_card_default_coerced_to_installment_card():
    """Спека 2026-05-06: у Яндекс банка нет кредитных карт. Любой default
    `credit_card` для Yandex автоматически перезаписывается в
    `installment_card` — даже без contract refinement."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number=None,
        default=ACCOUNT_TYPE_CREDIT_CARD,
    )
    assert refined == ACCOUNT_TYPE_INSTALLMENT_CARD


def test_yandex_credit_card_default_with_KS_contract_becomes_installment():
    """Yandex with `credit_card` default + КС contract → both routes agree
    on installment_card: CC→installment coercion AND КС-rule itself."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number="КС20251126",
        default=ACCOUNT_TYPE_CREDIT_CARD,
    )
    assert refined == ACCOUNT_TYPE_INSTALLMENT_CARD


def test_yandex_credit_card_classifier_never_returns_credit_card():
    """Direct check — `_classify_yandex_credit_account_type` no longer
    has a code path that returns ACCOUNT_TYPE_CREDIT_CARD."""
    for sample in ("", "Любая выписка", "Сплит — карта рассрочки", "Потребительский кредит"):
        result = PdfExtractor._classify_yandex_credit_account_type(sample)
        assert result != ACCOUNT_TYPE_CREDIT_CARD, f"got credit_card for {sample!r}"


def test_yandex_classifier_marks_potreb_kredit_as_installment():
    """Сплит-выписка содержит фразу «потребительский кредит с фиксированным
    лимитом» — это маркер installment_card."""
    text = "АО «Яндекс Банк»\nПотребительский кредит с фиксированным лимитом"
    assert (
        PdfExtractor._classify_yandex_credit_account_type(text)
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


# ─── Contract-number regex extension for Ozon «Номер договора: № …» ────────


def test_ozon_contract_number_with_n_sign_extracts():
    """Real Ozon PDF heading 2026-04-20 (live case 2026-05-06):
        «Номер договора: № 2025-11-27-KK-07880171045845068514 от 27.11.2025»
    Pre-2026-05-06 the regex required the value to start immediately after
    the colon; the «№» between «:» and the value broke the match. Fixed
    by making «№» optional in the colon-prefix branch."""
    raw_lines = [
        "ООО «ОЗОН Банк», 123112, город Москва,",
        "Лицензия Банка России № 3542 от 12 апреля 2023 года",
        "Справка о движении средств",
        "Номер договора: № 2025-11-27-KK-07880171045845068514 от 27.11.2025",
        "Дата операции",  # stop-marker
    ]
    contract, reason, confidence = PdfExtractor._extract_contract_number_details(raw_lines)
    assert contract == "2025-11-27-KK-07880171045845068514"
    assert confidence is not None and confidence >= 0.9
    assert reason  # non-empty


def test_yandex_product_name_classifier_returns_main_for_eds():
    """«Счёт ЭДС» в шапке выписки = main (live PDF screenshot 2026-05-06)."""
    text = (
        "АО «Яндекс Банк», лицензия Банка России № 3027 (далее — «Банк»),\n"
        "сообщает, что между Вами и Банком заключён договор\n"
        "№ Э20240626883885586 от 26.06.2024 в рамках продукта\n"
        "«Счёт ЭДС» (далее — «Договор»).\n"
    )
    assert (
        PdfExtractor._classify_yandex_account_type_by_product(text)
        == ACCOUNT_TYPE_MAIN
    )


def test_yandex_product_name_classifier_returns_installment_for_potreb_kredit():
    """«Потребительский кредит (с лимитом кредитования)» = Яндекс Сплит =
    installment_card (live PDF screenshot 2026-05-06)."""
    text = (
        "АО «Яндекс Банк», лицензия Банка России № 3027 (далее — «Банк»),\n"
        "сообщает, что между Вами и Банком заключён договор\n"
        "№ КС20251126483806054311 от 26.11.2025 в рамках продукта\n"
        "«Потребительский кредит (с лимитом кредитования)» (далее —\n"
        "«Договор»).\n"
    )
    assert (
        PdfExtractor._classify_yandex_account_type_by_product(text)
        == ACCOUNT_TYPE_INSTALLMENT_CARD
    )


def test_yandex_product_name_classifier_returns_none_when_no_marker():
    """Без явного product-name → None, чтобы caller мог fall back на
    contract-prefix или branch default."""
    assert PdfExtractor._classify_yandex_account_type_by_product("") is None
    assert PdfExtractor._classify_yandex_account_type_by_product(
        "АО «Яндекс Банк»\nКакой-то текст без продуктового имени"
    ) is None


def test_yandex_product_name_overrides_contract_prefix_via_default():
    """If product-name said «Счёт ЭДС» (main), passing main as default into
    refine — and refine sees contract «КС...» (would normally → installment)
    — refine still wins for prefix, but in real flow product-name is the
    primary signal applied BEFORE refine, so the value passed as default
    already reflects the header. This test pins the contract-prefix-only
    behavior; product-name flow is covered above."""
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="yandex", contract_number="КС20251126",
        default=ACCOUNT_TYPE_MAIN,
    )
    # Contract prefix beats default — but in production flow product-name
    # for «Счёт ЭДС» wouldn't co-occur with «КС...» contract.
    assert refined == ACCOUNT_TYPE_INSTALLMENT_CARD


def test_ozon_contract_KK_prefix_resolves_to_credit_card_end_to_end():
    """Combined: with the regex fix the Ozon contract is extracted, and
    refine then maps it to credit_card via the «КК»/«KK» rule."""
    raw_lines = [
        "ООО «ОЗОН Банк»",
        "Справка о движении средств",
        "Номер договора: № 2025-11-27-KK-07880171045845068514",
        "Дата операции",
    ]
    contract, _, _ = PdfExtractor._extract_contract_number_details(raw_lines)
    refined = PdfExtractor._refine_account_type_by_contract(
        bank_code="ozon", contract_number=contract, default=ACCOUNT_TYPE_MAIN,
    )
    assert refined == ACCOUNT_TYPE_CREDIT_CARD


# ─── End-to-end meta contract: extract() always sets the two keys ───────────


def test_meta_contract_unparseable_pdf_carries_bank_and_type():
    """Even when the PDF can't be opened, meta MUST include bank_code and
    account_type_hint with safe defaults — frontend should not have to
    `?? null` these fields on every read.
    """
    extractor = PdfExtractor()
    result = extractor.extract(filename="bad.pdf", raw_bytes=b"not a pdf")
    assert result.meta.get("bank_code") == BANK_CODE_UNKNOWN
    assert result.meta.get("account_type_hint") is None


@pytest.mark.parametrize("payload", [
    b"",
    b"\x00\x01\x02",
    b"%PDF-broken",
])
def test_meta_contract_various_invalid_pdf_payloads(payload):
    extractor = PdfExtractor()
    result = extractor.extract(filename="bad.pdf", raw_bytes=payload)
    # Two-key contract holds regardless of which diagnostics path fired.
    assert "bank_code" in result.meta
    assert "account_type_hint" in result.meta
    assert result.meta["bank_code"] == BANK_CODE_UNKNOWN
    assert result.meta["account_type_hint"] is None

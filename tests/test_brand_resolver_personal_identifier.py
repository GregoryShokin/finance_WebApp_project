"""Brand vs personal-identifier separation (Brand Registry §X, spec v1.26).

Product rule: a phone number, contract number, or person name identifies a
personal counterparty, NOT a brand. One person sends money for food, debt,
rent, gifts — the category changes every time. Auto-binding such rows to a
Brand entity would mislead the user into thinking all payments to «Мама» are
«Продукты» or whatever the first confirmed row happened to be.

Guard applied at three points:

  A. BrandResolverService.resolve(): text/alias_exact matches are rejected
     when tokens.phone / .contract / .person_name is set without an org or
     SBP merchant ID. sbp_merchant_id and org_full matches still pass — those
     signal an actual merchant, not a personal contact.

  B. BrandConfirmService._learn_pattern_from_row(): auto-learn is silently
     skipped for personal-identifier rows so a user confirm on a «погашение
     кредита» row doesn't create a text:«погашение» pattern that would match
     all future credit-repayment rows to the same brand.

  C. ImportClusterService._group_by_brand(): BrandCluster is not emitted for
     clusters whose primary identifier is phone / contract / person_hash.
     Explicit BrandGroup (user binding) is NOT filtered — that is an
     intentional user action.

Six scenarios are tested:

  1. phone-row + private text pattern → resolver returns None.
  2. contract-row + private text pattern → resolver returns None.
  3. person_name-row + private text pattern → resolver returns None.
  4. org_full row (merchant) → resolver works normally (not personal).
  5. SBP merchant ID row → resolver works normally.
  6. explicit user-confirm on phone-row → brand_id stamped, BUT _learn is
     silent skip → no new private text pattern created.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.models.brand import Brand, BrandPattern
from app.services.brand_extractor_service import is_personal_identifier_row
from app.services.brand_resolver_service import BrandResolverService
from app.services.import_normalizer_v2 import ExtractedTokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern(
    *,
    brand_id: int,
    kind: str,
    pattern: str,
    scope_user_id: int | None = 1,
    confirms: int = 3,
    rejections: int = 0,
    is_regex: bool = False,
    pattern_id: int = 1,
) -> BrandPattern:
    p = MagicMock(spec=BrandPattern)
    p.id = pattern_id
    p.brand_id = brand_id
    p.kind = kind
    p.pattern = pattern
    p.scope_user_id = scope_user_id
    p.confirms = Decimal(str(confirms))
    p.rejections = Decimal(str(rejections))
    p.is_regex = is_regex
    return p


def _make_brand(brand_id: int = 1, name: str = "Тест бренд") -> Brand:
    b = MagicMock(spec=Brand)
    b.id = brand_id
    b.slug = name.lower()
    b.canonical_name = name
    b.category_hint = "Разное"
    return b


def _resolver_with_pattern(db, pattern: BrandPattern, brand: Brand) -> BrandResolverService:
    svc = BrandResolverService(db)
    svc._patterns_cache[1] = [pattern]
    svc._brands_cache[brand.id] = brand
    return svc


# ---------------------------------------------------------------------------
# A. Resolver guard — personal-identifier rows return None
# ---------------------------------------------------------------------------

class TestResolverPersonalIdentifierGuard:
    """text / alias_exact matches are blocked for personal-identifier rows."""

    def test_phone_row_text_pattern_returns_none(self, db):
        """Private text-pattern «перевод» must NOT match a phone-identified row.

        A user once confirmed «Мама» on a «Перевод +79161234567» row, which
        created text:перевод as a pattern. Without the guard, the next import
        row «перевод +79161234567» would hit the pattern and suggest «Мама»
        as a brand — but this is a personal contact, not a merchant.
        """
        brand = _make_brand(1, "Мама")
        pattern = _make_pattern(brand_id=1, kind="text", pattern="перевод")
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(phone="+79161234567")
        result = svc.resolve(
            skeleton="перевод +79161234567",
            tokens=tokens,
            user_id=1,
        )
        assert result is None, (
            "Resolver must return None for phone-identified row even when a "
            "text-pattern matches the skeleton."
        )

    def test_contract_row_text_pattern_returns_none(self, db):
        """Contract-identified rows must not be matched by text-kind patterns."""
        brand = _make_brand(2, "Кредит банк")
        pattern = _make_pattern(brand_id=2, kind="text", pattern="погашение")
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(contract="КС20251126483806054311")
        result = svc.resolve(
            skeleton="погашение тела <CONTRACT>",
            tokens=tokens,
            user_id=1,
        )
        assert result is None

    def test_person_name_row_text_pattern_returns_none(self, db):
        """Person-name-identified rows (ФИО) must not be matched by text-patterns."""
        brand = _make_brand(3, "Отец")
        pattern = _make_pattern(brand_id=3, kind="text", pattern="иванов")
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(person_name="Иванов Иван Иванович")
        result = svc.resolve(
            skeleton="перевод иванов иван иванович",
            tokens=tokens,
            user_id=1,
        )
        assert result is None

    def test_alias_exact_also_blocked_for_phone_row(self, db):
        """alias_exact kind is also blocked for personal-identifier rows."""
        brand = _make_brand(4, "Брат")
        pattern = _make_pattern(
            brand_id=4, kind="alias_exact",
            pattern="+79161234567 на счёт",
        )
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(phone="+79161234567")
        result = svc.resolve(
            skeleton="+79161234567 на счёт",
            tokens=tokens,
            user_id=1,
        )
        assert result is None, "alias_exact is also blocked for phone rows."

    def test_org_row_text_pattern_still_matches(self, db):
        """Merchant row with counterparty_org must NOT be filtered — it IS a brand."""
        brand = _make_brand(5, "Пятёрочка")
        pattern = _make_pattern(brand_id=5, kind="text", pattern="pyaterochka")
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(counterparty_org="ООО Пятёрочка")
        result = svc.resolve(
            skeleton="оплата в pyaterochka volgodonsk rus",
            tokens=tokens,
            user_id=1,
        )
        # org_full kind would match counterparty_org — but pattern is text-kind
        # AND org is set → is_personal_identifier_row=False → text matches.
        assert result is not None, "Merchant row with org must pass through."
        assert result.brand_id == 5

    def test_sbp_merchant_id_pattern_still_matches(self, db):
        """SBP merchant ID match (kind=sbp_merchant_id) bypasses the guard."""
        brand = _make_brand(6, "Яндекс Такси")
        pattern = _make_pattern(brand_id=6, kind="sbp_merchant_id", pattern="26033")
        svc = _resolver_with_pattern(db, pattern, brand)

        tokens = ExtractedTokens(sbp_merchant_id="26033")
        result = svc.resolve(
            skeleton="26033 mor sbp 0387",
            tokens=tokens,
            user_id=1,
        )
        assert result is not None, "SBP merchant ID match must pass through."
        assert result.brand_id == 6


# ---------------------------------------------------------------------------
# B. Auto-learn guard — _learn_pattern_from_row skips personal rows
# ---------------------------------------------------------------------------

class TestLearnPatternPersonalIdentifierGuard:
    def test_learn_skips_phone_row(self, db):
        """When tokens carry a phone and no org/sbp, _learn must not create a
        text pattern (the extracted token would be a generic verb like «перевод»
        — but «перевод» is already blocked by extract_brand; test with a word
        that extract_brand WOULD return, like «поступление»)."""
        from app.services.brand_confirm_service import BrandConfirmService

        svc = BrandConfirmService(db)
        brand = _make_brand(1, "Мама")
        tokens_with_phone = {"phone": "+79161234567", "contract": None,
                              "person_name": None, "counterparty_org": None,
                              "sbp_merchant_id": None}

        with patch.object(svc.brand_repo, "list_patterns_for_brand", return_value=[]):
            with patch.object(svc.brand_repo, "upsert_pattern") as mock_upsert:
                svc._learn_pattern_from_row(
                    user_id=1,
                    brand=brand,
                    skeleton="поступление <PHONE>",
                    tokens=tokens_with_phone,
                )
                mock_upsert.assert_not_called()

    def test_learn_skips_contract_row_with_generic_verb(self, db):
        """Contract-identified row with «погашение» in skeleton — must not create
        text:погашение pattern even though extract_brand returns 'погашение'."""
        from app.services.brand_confirm_service import BrandConfirmService

        svc = BrandConfirmService(db)
        brand = _make_brand(2, "МойБанк")
        tokens_with_contract = {"phone": None, "contract": "КС123",
                                 "person_name": None, "counterparty_org": None,
                                 "sbp_merchant_id": None}

        with patch.object(svc.brand_repo, "list_patterns_for_brand", return_value=[]):
            with patch.object(svc.brand_repo, "upsert_pattern") as mock_upsert:
                svc._learn_pattern_from_row(
                    user_id=1,
                    brand=brand,
                    skeleton="погашение тела договор <CONTRACT>",
                    tokens=tokens_with_contract,
                )
                mock_upsert.assert_not_called()

    def test_learn_proceeds_for_merchant_row(self, db):
        """Merchant row (org present) — auto-learn proceeds normally."""
        from app.services.brand_confirm_service import BrandConfirmService

        svc = BrandConfirmService(db)
        brand = _make_brand(3, "МРТшка")
        tokens_with_org = {"phone": None, "contract": None,
                            "person_name": None,
                            "counterparty_org": "ООО МРТшка",
                            "sbp_merchant_id": None}

        with patch.object(svc.brand_repo, "list_patterns_for_brand", return_value=[]):
            with patch.object(svc.brand_repo, "upsert_pattern") as mock_upsert:
                svc._learn_pattern_from_row(
                    user_id=1,
                    brand=brand,
                    skeleton="оплата в mrtshka volgodonsk rus",
                    tokens=tokens_with_org,
                )
                # extract_brand returns "mrtshka" → upsert should be called.
                mock_upsert.assert_called_once()

    def test_learn_proceeds_when_no_tokens(self, db):
        """No token dict (legacy row) — guard is skipped, normal flow runs."""
        from app.services.brand_confirm_service import BrandConfirmService

        svc = BrandConfirmService(db)
        brand = _make_brand(4, "Пятёрочка")

        with patch.object(svc.brand_repo, "list_patterns_for_brand", return_value=[]):
            with patch.object(svc.brand_repo, "upsert_pattern") as mock_upsert:
                svc._learn_pattern_from_row(
                    user_id=1,
                    brand=brand,
                    skeleton="оплата в pyaterochka volgodonsk rus",
                    tokens=None,
                )
                mock_upsert.assert_called_once()


# ---------------------------------------------------------------------------
# C. is_personal_identifier_row predicate — unit tests
# ---------------------------------------------------------------------------

class TestIsPersonalIdentifierRow:
    def test_phone_no_org(self):
        assert is_personal_identifier_row("перевод <PHONE>",
            {"phone": "+79161234567", "counterparty_org": None, "sbp_merchant_id": None}) is True

    def test_contract_no_org(self):
        assert is_personal_identifier_row("погашение <CONTRACT>",
            {"contract": "КС123", "counterparty_org": None, "sbp_merchant_id": None}) is True

    def test_person_name_no_org(self):
        assert is_personal_identifier_row("перевод <PERSON>",
            {"person_name": "Иванов Иван", "counterparty_org": None, "sbp_merchant_id": None}) is True

    def test_phone_with_org_is_false(self):
        """org present → merchant row, not personal."""
        assert is_personal_identifier_row("оплата ооо ромашка",
            {"phone": "+79161234567", "counterparty_org": "ООО Ромашка", "sbp_merchant_id": None}) is False

    def test_sbp_merchant_id_is_false(self):
        assert is_personal_identifier_row("26033 mor sbp 0387",
            {"phone": None, "contract": None, "person_name": None,
             "counterparty_org": None, "sbp_merchant_id": "26033"}) is False

    def test_no_personal_signal_is_false(self):
        assert is_personal_identifier_row("оплата pyaterochka volgodonsk",
            {"phone": None, "contract": None, "person_name": None,
             "counterparty_org": None, "sbp_merchant_id": None}) is False

    def test_none_tokens_is_false(self):
        assert is_personal_identifier_row("any skeleton", None) is False

    def test_extracted_tokens_dataclass_phone(self):
        """Also works with the ExtractedTokens dataclass (resolver path)."""
        tokens = ExtractedTokens(phone="+79161234567")
        assert is_personal_identifier_row("перевод <PHONE>", tokens) is True

    def test_extracted_tokens_with_org_is_false(self):
        tokens = ExtractedTokens(phone="+79161234567", counterparty_org="ООО Ромашка")
        assert is_personal_identifier_row("оплата ооо ромашка", tokens) is False

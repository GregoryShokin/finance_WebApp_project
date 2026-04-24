"""Unit tests for app.services.brand_extractor_service."""
from __future__ import annotations

import pytest

from app.services.brand_extractor_service import extract_brand


# Real skeletons taken from session 204 analysis.
@pytest.mark.parametrize("skeleton,expected", [  # type: ignore[misc]
    ("оплата в pyaterochka 14130 volgodonsk rus", "pyaterochka"),
    ("оплата в pyaterochka 20046 volgodonsk rus", "pyaterochka"),
    ("оплата в magnit gm volgodonsk 1 volgodonsk rus", "magnit"),
    ("оплата в magnit mm illertaler volgodonsk rus", "magnit"),
    ("оплата в magnit mm tulkas volgodonsk rus", "magnit"),
    ("оплата в kofemoloko volgodonsk rus", "kofemoloko"),
    ("оплата в dodo pizza volgodonsk volgodonsk rus", "dodo"),
    # qsr / volgodonsk / rus are all filler → no brand (one of those
    # ambiguous kiosk-style rows that stay at fingerprint level).
    ("оплата в qsr 26033 volgodonsk rus", None),
    ("оплата в poplavo volgodonsk rus", "poplavo"),
    ("оплата в krasnoe beloe volgodonsk rus", "krasnoe"),
    ("оплата в nippon volgodonsk rus", "nippon"),
    ("оплата в vkusnyj el volgodonsk rus", "vkusnyj"),
    ("оплата в antikafe arenda volgodonsk rus", "antikafe"),
    # underscores are not letters → tokenizer splits "kofejnya_shu" into
    # "kofejnya" + "shu"; the first non-filler wins.
    ("оплата в kofejnya_shu shu volgodonsk rus", "kofejnya"),
    # IP-prefixed shops: legal form is filler, person surname is brand.
    ("оплата в ip drugov ms volgodonsk rus", "drugov"),
    ("оплата в md ip drugov m s volgodonsk rus", "drugov"),
])
def test_extract_brand_session_204_samples(skeleton: str, expected: str) -> None:
    assert extract_brand(skeleton) == expected


@pytest.mark.parametrize("skeleton", [
    "",
    "   ",
    "rus moscow volgodonsk",          # all filler
    "<phone> <contract> <amount>",    # all placeholders
    "внешний перевод номеру телефона <phone>",  # transfer row — no brand
    "внутрибанковский перевод с <contract>",    # transfer row — no brand
    "12345 6789",                     # all digits
    "k t p",                          # too short
])
def test_extract_brand_returns_none_for_no_brand(skeleton: str) -> None:
    assert extract_brand(skeleton) is None


def test_extract_brand_case_insensitive_but_lowercased_output() -> None:
    assert extract_brand("Оплата в PYATEROCHKA 14130 Volgodonsk RUS") == "pyaterochka"


def test_extract_brand_skips_filler_and_keeps_first_real_token() -> None:
    # "оплата" + "в" → filler. "Pyaterochka" → brand. Digits → skip.
    assert extract_brand("оплата в 14130 pyaterochka rus") == "pyaterochka"


def test_extract_brand_stable_across_paren_locations() -> None:
    # Brand identity must not depend on where the TT number appears.
    a = extract_brand("оплата в pyaterochka 14130 volgodonsk rus")
    b = extract_brand("оплата в 14130 pyaterochka volgodonsk rus")
    c = extract_brand("оплата в pyaterochka volgodonsk 14130 rus")
    assert a == b == c == "pyaterochka"

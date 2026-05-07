"""Seed the global brand registry from data/brands_seed_v1.csv (Brand registry Ph2).

Idempotent — safe to re-run. The script does NOT touch user-private brands
or patterns (`is_global=False`); it only creates / updates global entries.

Usage:
    docker compose exec api python -m scripts.seed_brand_registry --dry-run
    docker compose exec api python -m scripts.seed_brand_registry --execute

CSV format:
    slug,canonical_name,category_hint,patterns

Where `patterns` is a pipe-separated list of `kind:value` items, for example:
    text:pyaterochka|text:пятёрочка|sbp_merchant_id:26033

Supported kinds (matched against BRAND_PATTERN_KINDS in the model):
    text, sbp_merchant_id, org_full, alias_exact

What "update" means:
  - Brand row: canonical_name and category_hint may be refreshed when CSV
    differs from DB. is_global is NOT toggled — once a brand is global it
    stays global; downgrading is a manual maintainer step.
  - Pattern: idempotent upsert by (brand_id, kind, pattern, scope_user_id=NULL).
    Strength counters (confirms / rejections) are NEVER touched here.

What seed does NOT do:
  - Delete patterns that disappeared from the CSV. Removing a global pattern
    is a deliberate maintainer action (it could orphan user history).
  - Touch anything user-scope.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.brand import BRAND_PATTERN_KINDS
from app.repositories.brand_repository import BrandRepository

logger = logging.getLogger(__name__)

DEFAULT_CSV_PATH = Path("data/brands_seed_v1.csv")


@dataclass
class SeedReport:
    brands_created: int = 0
    brands_updated: int = 0
    brands_unchanged: int = 0
    patterns_created: int = 0
    patterns_unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def total_changes(self) -> int:
        return (
            self.brands_created
            + self.brands_updated
            + self.patterns_created
        )

    def summary_line(self) -> str:
        return (
            f"brands: +{self.brands_created} created / "
            f"~{self.brands_updated} updated / ={self.brands_unchanged} unchanged | "
            f"patterns: +{self.patterns_created} created / "
            f"={self.patterns_unchanged} unchanged"
        )


def parse_patterns_field(raw: str) -> list[tuple[str, str, bool]]:
    """Decode the pipe-encoded `patterns` CSV column into [(kind, value, is_regex), …].

    `re:` prefix marks a regex text pattern: `re:yandex.{0,30}plus` →
    (kind="text", value="yandex.{0,30}plus", is_regex=True). Used for
    split-token descriptions like "yandex 5815 plus" where substring
    matching would force one wide-net pattern per legitimate variant.
    """
    if not raw or not raw.strip():
        return []
    out: list[tuple[str, str, bool]] = []
    for chunk in raw.split("|"):
        item = chunk.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"pattern item missing ':' separator: {item!r}")
        kind, _, value = item.partition(":")
        kind = kind.strip()
        value = value.strip()
        if not kind or not value:
            raise ValueError(f"pattern item has empty kind/value: {item!r}")

        is_regex = False
        if kind == "re":
            kind = "text"
            is_regex = True

        if kind not in BRAND_PATTERN_KINDS:
            raise ValueError(
                f"unsupported pattern kind {kind!r} (allowed: "
                f"{sorted(BRAND_PATTERN_KINDS) + ['re (text regex)']})"
            )
        out.append((kind, value, is_regex))
    return out


def seed_from_csv(
    db: Session, csv_path: Path, *, report: SeedReport | None = None,
) -> SeedReport:
    """Apply the CSV to the DB. Caller owns the transaction (commit/rollback).

    The script flushes after each Brand/BrandPattern upsert so SQL errors
    surface immediately attached to the offending row, rather than at commit
    time when blame is hard to attribute.
    """
    if report is None:
        report = SeedReport()
    repo = BrandRepository(db)
    seen_slugs: set[str] = set()

    with open(csv_path, encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        required_cols = {"slug", "canonical_name", "category_hint", "patterns"}
        if reader.fieldnames is None or not required_cols.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV missing required columns. Got: {reader.fieldnames}; "
                f"required: {sorted(required_cols)}"
            )

        for row_no, row in enumerate(reader, start=2):
            slug = (row.get("slug") or "").strip()
            canonical_name = (row.get("canonical_name") or "").strip()
            category_hint = (row.get("category_hint") or "").strip() or None
            patterns_raw = row.get("patterns") or ""

            if not slug or not canonical_name:
                report.errors.append(
                    f"row {row_no}: slug and canonical_name are required",
                )
                continue
            if slug in seen_slugs:
                report.errors.append(
                    f"row {row_no}: duplicate slug {slug!r} in CSV",
                )
                continue
            seen_slugs.add(slug)

            try:
                pattern_items = parse_patterns_field(patterns_raw)
            except ValueError as exc:
                report.errors.append(f"row {row_no} ({slug}): {exc}")
                continue

            brand = repo.get_brand_by_slug(slug)
            if brand is None:
                brand = repo.create_brand(
                    slug=slug,
                    canonical_name=canonical_name,
                    category_hint=category_hint,
                    is_global=True,
                )
                report.brands_created += 1
            else:
                changed = False
                if brand.canonical_name != canonical_name:
                    brand.canonical_name = canonical_name
                    changed = True
                if brand.category_hint != category_hint:
                    brand.category_hint = category_hint
                    changed = True
                if changed:
                    db.add(brand)
                    db.flush()
                    report.brands_updated += 1
                else:
                    report.brands_unchanged += 1

            for kind, value, is_regex in pattern_items:
                _, is_new = repo.upsert_pattern(
                    brand_id=brand.id,
                    kind=kind,
                    pattern=value,
                    is_global=True,
                    is_regex=is_regex,
                )
                if is_new:
                    report.patterns_created += 1
                else:
                    report.patterns_unchanged += 1

    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed the global brand registry from a CSV file.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Path to the seed CSV (default: {DEFAULT_CSV_PATH})",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Apply changes inside a transaction, then ROLL BACK; report only.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes and COMMIT.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_parser().parse_args(argv)
    csv_path: Path = args.csv

    if not csv_path.exists():
        logger.error("CSV not found: %s", csv_path)
        return 2

    from app.core.db import SessionLocal

    with SessionLocal() as db:
        report = seed_from_csv(db, csv_path)
        if args.execute:
            db.commit()
            logger.info("EXECUTED. %s", report.summary_line())
        else:
            db.rollback()
            logger.info("DRY-RUN. %s", report.summary_line())

    if report.errors:
        logger.warning("Errors encountered (%d):", len(report.errors))
        for err in report.errors:
            logger.warning("  - %s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

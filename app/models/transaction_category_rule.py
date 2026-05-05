from __future__ import annotations

from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# Allowed values for `scope`. Stored as plain VARCHAR(32) in PG (enums are
# painful to evolve), validated in Python — business rules land in Phase 2.3.
RULE_SCOPES: frozenset[str] = frozenset(
    {"exact", "bank", "global", "legacy_pattern", "specific", "general"}
)

# Scopes admitted to the preview rule-matching path. §6.1 + §14.7: the
# old `bank` / `legacy_pattern` scopes are deprecated and must NOT match
# silently; they live on in the table for history (organic decay /
# manual migration), but rule lookup ignores them. `exact` rules are
# matched through a different identifier-based code path, not through
# `get_best_rule`. `general` is the future skeleton-based scope (post
# §14.7 migration). `specific` is reserved for the new identifier-based
# scope name. See PR1 of the legacy-cleanup work.
ACTIVE_PREVIEW_SCOPES: frozenset[str] = frozenset({"specific", "general"})

# Scopes considered LEGACY — kept inactive after the cleanup migration,
# never participate in matching. Listed here so callers can detect &
# report them rather than hardcode the enum.
LEGACY_RULE_SCOPES: frozenset[str] = frozenset({"bank", "legacy_pattern"})

# Allowed values for `identifier_key` when scope == 'exact'.
RULE_IDENTIFIER_KEYS: frozenset[str] = frozenset(
    {"phone", "contract", "iban", "card", "person_hash"}
)


class TransactionCategoryRule(Base):
    __tablename__ = "transaction_category_rules"
    # UNIQUE on (user_id, normalized_description, category_id, operation_type)
    # is declared here so SQLite test fixtures (which use Base.metadata.create_all)
    # see the same index name. In Postgres the migration 0062 creates the
    # *same* index but with `NULLS NOT DISTINCT` — SQLite already treats NULLs
    # as equal in UNIQUE, so the two engines converge on the same semantics.
    # The shared index name (`uq_tx_cat_rule_user_desc_cat_optype`) is what
    # `bulk_upsert` / `upsert` target via `INSERT ... ON CONFLICT (...)`.
    __table_args__ = (
        Index(
            "uq_tx_cat_rule_user_desc_cat_optype",
            "user_id",
            "normalized_description",
            "category_id",
            "operation_type",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    normalized_description: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    # Этап 2: learned operation_type. NULL means the rule was created before
    # Этап 2 (legacy) or by a code path that doesn't supply op_type. NULL
    # rules never participate in the op_type-suggestion path of enrichment;
    # they continue to drive category-suggestion exactly as before.
    # NOTE: indexed via partial PG index `ix_rules_operation_type`
    # (operation_type IS NOT NULL only) — see migration 0062. Don't add
    # `index=True` here — would duplicate the index on every row including
    # legacy NULL rows. UNIQUE on (user_id, normalized_description,
    # category_id, operation_type) lives as a NULLS NOT DISTINCT index in
    # the same migration.
    operation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Strength counters (И-08 Phase 2, §10.2). Numeric so `warning` bulk-ack
    # confirmations can weigh 0.5 while `ready` confirmations weigh 1.0.
    confirms: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("1.00"), server_default="1.00"
    )
    rejections: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )

    # Activation + scope. See RULE_SCOPES for allowed `scope` values.
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="legacy_pattern", server_default="legacy_pattern"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Scope qualifiers — nullable, populated depending on `scope`.
    bank_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id_scope: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL", name="fk_tx_cat_rule_account_scope"),
        nullable=True,
    )
    identifier_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identifier_value: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

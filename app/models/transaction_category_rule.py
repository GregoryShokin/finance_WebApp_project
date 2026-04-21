from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# Allowed values for `scope`. Stored as plain VARCHAR(32) in PG (enums are
# painful to evolve), validated in Python — business rules land in Phase 2.3.
RULE_SCOPES: frozenset[str] = frozenset(
    {"exact", "bank", "global", "legacy_pattern"}
)

# Allowed values for `identifier_key` when scope == 'exact'.
RULE_IDENTIFIER_KEYS: frozenset[str] = frozenset(
    {"phone", "contract", "iban", "card", "person_hash"}
)


class TransactionCategoryRule(Base):
    __tablename__ = "transaction_category_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_description", "category_id", name="uq_tx_cat_rule_user_desc_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    normalized_description: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    original_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)

    # Strength counters (И-08 Phase 2).
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    rejections: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

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

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="csv", server_default="csv")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded", server_default="uploaded", index=True)
    file_content: Mapped[str] = mapped_column(Text, nullable=False)
    detected_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    parse_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    mapping_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

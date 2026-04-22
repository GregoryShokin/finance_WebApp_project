from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Bank(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    bik: Mapped[str | None] = mapped_column(String(9), nullable=True, unique=True, index=True)
    is_popular: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    accounts = relationship("Account", back_populates="bank")

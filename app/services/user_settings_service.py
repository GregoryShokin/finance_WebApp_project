from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.user_settings import UserSettings


_DEFAULT_THRESHOLD = Decimal("0.200")
_MIN_THRESHOLD = Decimal("0.050")
_MAX_THRESHOLD = Decimal("0.500")


class UserSettingsValidationError(Exception):
    pass


class UserSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_default(self, user_id: int) -> UserSettings:
        """Return the user's settings row, or an in-memory default if none exists yet."""
        row = (
            self.db.query(UserSettings)
            .filter(UserSettings.user_id == user_id)
            .first()
        )
        if row is None:
            # Return a transient object with defaults — not saved to DB.
            row = UserSettings(
                user_id=user_id,
                large_purchase_threshold_pct=_DEFAULT_THRESHOLD,
            )
        return row

    def update(self, user_id: int, large_purchase_threshold_pct: float) -> UserSettings:
        value = Decimal(str(large_purchase_threshold_pct)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
        if not (_MIN_THRESHOLD <= value <= _MAX_THRESHOLD):
            raise UserSettingsValidationError(
                f"Порог должен быть в диапазоне {float(_MIN_THRESHOLD * 100):.0f}–"
                f"{float(_MAX_THRESHOLD * 100):.0f}%."
            )

        row = (
            self.db.query(UserSettings)
            .filter(UserSettings.user_id == user_id)
            .first()
        )
        if row is None:
            row = UserSettings(user_id=user_id, large_purchase_threshold_pct=value)
            self.db.add(row)
        else:
            row.large_purchase_threshold_pct = value
            self.db.add(row)

        self.db.flush()
        return row

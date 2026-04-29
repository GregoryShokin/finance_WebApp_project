"""Регрессионные тесты на починку «зеркальных» внутрибанковских переводов.

Кейс пользователя 2026-04-25: импорт двух выписок одного банка с зеркальными
суммами/датами разъезжался между сторонами:
    Сплит-сторона:  «Внутрибанковский перевод с договора 5452737298» → transfer
    Дебет-сторона:  «Внутренний перевод на договор 0504603705»       → regular

Корневые дыры:
1. `TransactionEnrichmentService._resolve_operation_type` держал
   «внутрибанковский/внутренний/межбанковский перевод» в WEAK (0.70) — ниже
   порога caller'а 0.88, из-за чего одна сторона уезжала в regular.
2. `import_service` слепо вызывал `_create_transfer_pair`, не проверяя
   наличие `transfer_match.matched_tx_id`. Если matcher уже свёл активную
   строку с committed orphan transfer — создавалась ВТОРАЯ зеркальная
   транзакция и target-счёт получал double-credit по балансу.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.transaction import Transaction
from app.services.transaction_enrichment_service import TransactionEnrichmentService
from app.services.import_service import ImportService


# ---------------------------------------------------------------------------
# Фикс №1: классификатор operation_type
# ---------------------------------------------------------------------------


class TestInternalTransferKeywordsAreStrong:
    """«Внутрибанковский / внутренний / межбанковский перевод» — STRONG-сигнал."""

    @pytest.fixture
    def enrichment(self, db):
        return TransactionEnrichmentService(db=db)

    @pytest.mark.parametrize("description", [
        "Внутрибанковский перевод с договора 5452737298",
        "Внутренний перевод на договор 0504603705",
        "Межбанковский перевод по СБП",
    ])
    def test_internal_transfer_phrases_classify_as_transfer_strong(
        self, enrichment, description,
    ):
        op_type, confidence, _reason = enrichment._resolve_operation_type(
            description=description, raw_type="", history=[],
        )
        assert op_type == "transfer"
        # Должно быть выше порога 0.88, который caller использует для
        # downgrade. До фикса было 0.70 — strict greater-than 0.88.
        assert confidence > 0.88


# ---------------------------------------------------------------------------
# Фикс №2: линковка к committed orphan transfer вместо создания дубля
# ---------------------------------------------------------------------------


@pytest.fixture
def split_account(db, user, bank):
    """Счёт-target (например, Тинькофф Сплит), на котором уже лежит committed orphan."""
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Сплит",
        account_type="main",
        balance=Decimal("86000"),  # уже получил 86 000 при предыдущем коммите orphan'а
        currency="RUB",
        is_active=True,
        is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def debit_account(db, user, bank):
    """Активная сторона — счёт, который сейчас коммитится (Тинькофф Дебет)."""
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Дебет",
        account_type="main",
        balance=Decimal("100000"),
        currency="RUB",
        is_active=True,
        is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def orphan_committed_transfer(db, user, split_account):
    """Уже закоммиченный transfer без второй стороны — orphan."""
    when = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
    tx = Transaction(
        user_id=user.id,
        account_id=split_account.id,
        target_account_id=None,
        transfer_pair_id=None,
        amount=Decimal("86000"),
        currency="RUB",
        type="income",
        operation_type="transfer",
        description="Внутрибанковский перевод с договора 5452737298",
        normalized_description="внутрибанковский перевод с договора <contract>",
        skeleton="внутрибанковский перевод с договора <contract>",
        transaction_date=when,
        affects_analytics=False,
    )
    db.add(tx); db.commit(); db.refresh(tx)
    return tx


@pytest.fixture
def import_service(db):
    """Минимальный ImportService — нам нужен только метод _link_transfer_to_committed_pair.

    Step 2 of the §1 god-object decomposition (2026-04-29) extracted the
    transfer-linking logic into TransferLinkingService. The wrapper method
    now delegates through `self.transfer_linker`, so this minimal fixture
    must wire that service up too.
    """
    svc = ImportService.__new__(ImportService)
    svc.db = db
    from app.repositories.account_repository import AccountRepository
    from app.services.transaction_enrichment_service import TransactionEnrichmentService
    from app.services.transfer_linking_service import TransferLinkingService
    svc.account_repo = AccountRepository(db)
    svc.enrichment = TransactionEnrichmentService(db=db)
    svc.transfer_linker = TransferLinkingService(
        db, normalize_description=svc.enrichment.normalize_description,
    )
    return svc


class TestLinkTransferToCommittedPair:

    def test_links_to_orphan_without_creating_duplicate(
        self, db, user, split_account, debit_account, orphan_committed_transfer, import_service,
    ):
        """Активная сторона создаётся, committed orphan достраивается, дубля нет."""
        before_split_balance = split_account.balance
        before_debit_balance = debit_account.balance

        active_tx = import_service._link_transfer_to_committed_pair(
            user_id=user.id,
            payload={
                "account_id": debit_account.id,
                "target_account_id": split_account.id,
                "amount": Decimal("86000"),
                "currency": "RUB",
                "type": "expense",
                "description": "Внутренний перевод на договор 0504603705",
                "transaction_date": datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
                "skeleton": "внутренний перевод на договор <contract>",
            },
            committed_tx_id=orphan_committed_transfer.id,
        )

        assert active_tx is not None
        assert active_tx.account_id == debit_account.id
        assert active_tx.target_account_id == split_account.id
        assert active_tx.type == "expense"
        assert active_tx.operation_type == "transfer"
        assert active_tx.affects_analytics is False
        assert active_tx.transfer_pair_id == orphan_committed_transfer.id

        db.refresh(orphan_committed_transfer)
        assert orphan_committed_transfer.target_account_id == debit_account.id
        assert orphan_committed_transfer.transfer_pair_id == active_tx.id
        assert orphan_committed_transfer.operation_type == "transfer"
        assert orphan_committed_transfer.affects_analytics is False

        # ВАЖНО: на target-счёте баланс остался прежним (был учтён при
        # предыдущем коммите orphan'а). Дубля начисления +86 000 быть не должно.
        db.refresh(split_account)
        assert split_account.balance == before_split_balance
        # Активный счёт списал.
        db.refresh(debit_account)
        assert debit_account.balance == before_debit_balance - Decimal("86000")

        # Не появилось третьей транзакции — только active_tx + orphan.
        all_tx = db.query(Transaction).filter(Transaction.user_id == user.id).all()
        assert len(all_tx) == 2

    def test_returns_none_when_committed_already_paired(
        self, db, user, split_account, debit_account, orphan_committed_transfer, import_service,
    ):
        """Если committed уже спарен — возвращаем None, чтобы caller сделал fallback."""
        orphan_committed_transfer.transfer_pair_id = 999999
        db.add(orphan_committed_transfer); db.commit()

        result = import_service._link_transfer_to_committed_pair(
            user_id=user.id,
            payload={
                "account_id": debit_account.id,
                "target_account_id": split_account.id,
                "amount": Decimal("86000"),
                "currency": "RUB",
                "type": "expense",
                "description": "Внутренний перевод",
                "transaction_date": datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
            },
            committed_tx_id=orphan_committed_transfer.id,
        )
        assert result is None

    def test_returns_none_on_amount_mismatch(
        self, db, user, split_account, debit_account, orphan_committed_transfer, import_service,
    ):
        """Защита от несогласованных пар: суммы должны совпадать."""
        result = import_service._link_transfer_to_committed_pair(
            user_id=user.id,
            payload={
                "account_id": debit_account.id,
                "target_account_id": split_account.id,
                "amount": Decimal("12345"),  # ≠ 86000 у orphan
                "currency": "RUB",
                "type": "expense",
                "description": "Внутренний перевод",
                "transaction_date": datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
            },
            committed_tx_id=orphan_committed_transfer.id,
        )
        assert result is None

    def test_returns_none_on_same_direction(
        self, db, user, split_account, debit_account, orphan_committed_transfer, import_service,
    ):
        """Обе стороны income — это не transfer."""
        result = import_service._link_transfer_to_committed_pair(
            user_id=user.id,
            payload={
                "account_id": debit_account.id,
                "target_account_id": split_account.id,
                "amount": Decimal("86000"),
                "currency": "RUB",
                "type": "income",  # совпадает с orphan.type=income
                "description": "Внутренний перевод",
                "transaction_date": datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
            },
            committed_tx_id=orphan_committed_transfer.id,
        )
        assert result is None

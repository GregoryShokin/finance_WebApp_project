"""Package that eagerly imports every ORM model so SQLAlchemy's declarative
registry sees the full class graph before the first query.

Without this file, a consumer that imports only (say) Category will trigger
mapper configuration for relationship("User") and blow up with
`InvalidRequestError: failed to locate a name ('User')`. The API layer
accidentally works because FastAPI routers transitively import most models
before their first request; Celery workers have no such guarantee, which is
why Phase 4's moderate_import_session task failed at runtime.

Adding a model? Import it here.
"""
from app.models.account import Account
from app.models.bank import Bank
from app.models.bank_support_request import BankSupportRequest
from app.models.base import Base
from app.models.global_pattern import GlobalPattern, GlobalPatternVote
from app.models.budget import Budget
from app.models.budget_alert import BudgetAlert
from app.models.capital_snapshot import CapitalSnapshot
from app.models.category import Category
from app.models.counterparty import Counterparty
from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.models.counterparty_identifier import CounterpartyIdentifier
from app.models.debt_partner import DebtPartner
from app.models.fingerprint_alias import FingerprintAlias
from app.models.goal import Goal
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.installment_purchase import InstallmentPurchase
from app.models.real_asset import RealAsset
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transaction
from app.models.transaction_category_rule import TransactionCategoryRule
from app.models.user import User

__all__ = [
    "Account",
    "Bank",
    "BankSupportRequest",
    "Base",
    "GlobalPattern",
    "GlobalPatternVote",
    "Budget",
    "BudgetAlert",
    "CapitalSnapshot",
    "Category",
    "Counterparty",
    "CounterpartyFingerprint",
    "CounterpartyIdentifier",
    "DebtPartner",
    "FingerprintAlias",
    "Goal",
    "ImportRow",
    "ImportSession",
    "InstallmentPurchase",
    "RealAsset",
    "RefreshToken",
    "Transaction",
    "TransactionCategoryRule",
    "User",
]

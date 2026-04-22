"""add banks table with 30 popular Russian banks

Revision ID: 0045
Revises: 0044
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044_rename_confirms"
branch_labels = None
depends_on = None

BANKS = [
    # (name, code, bik, is_popular)
    ("Сбербанк",                "sber",            "044525225", True),
    ("Т-Банк",                  "tbank",           "044525974", True),
    ("Альфа-Банк",              "alfa",            "044525593", True),
    ("ВТБ",                     "vtb",             "044525187", True),
    ("Газпромбанк",             "gazprombank",     "044525823", True),
    ("Яндекс Банк",             "yandex",          "044525025", True),
    ("Озон Банк",               "ozon",            "044525354", True),
    ("Райффайзенбанк",          "raiffeisen",      "044525700", True),
    ("Росбанк",                 "rosbank",         "044525256", True),
    ("Промсвязьбанк",           "psb",             "044525555", True),
    ("Совкомбанк",              "sovcombank",      "043469743", True),
    ("Русский Стандарт",        "russkiy_standart","044525388", True),
    ("МТС Банк",                "mts",             "044525232", True),
    ("Почта Банк",              "pochta",          "044525214", True),
    ("Открытие",                "otkrytie",        "044525985", True),
    ("Хоум Банк",               "home_credit",     "044525245", True),
    ("ДОМ.РФ",                  "domrf",           "044525244", True),
    ("РНКБ",                    "rnkb",            "040349001", False),
    ("БКС Банк",                "bks",             "044525601", False),
    ("Ак Барс",                 "akbars",          "049205805", False),
    ("Банк Санкт-Петербург",    "bspb",            "044030790", False),
    ("Уралсиб",                 "uralsib",         "044030662", False),
    ("СМП Банк",                "smp",             "044525503", False),
    ("ВБРР",                    "vbrr",            "044525590", False),
    ("Абсолют Банк",            "absolut",         "044525976", False),
    ("Авангард",                "avangard",        "044525051", False),
    ("Экспобанк",               "expo",            "044525545", False),
    ("Банк ДОМ.РФ",             "domrf_bank",      "044525266", False),
    ("Ренессанс Кредит",        "renaissance",     "044525436", False),
    ("Банк Зенит",              "zenit",           "044525272", False),
]


def upgrade() -> None:
    op.create_table(
        "banks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("bik", sa.String(9), nullable=True),
        sa.Column("is_popular", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("bik"),
    )
    op.create_index("ix_banks_id", "banks", ["id"])
    op.create_index("ix_banks_code", "banks", ["code"])
    op.create_index("ix_banks_bik", "banks", ["bik"])

    op.bulk_insert(
        sa.table(
            "banks",
            sa.column("name", sa.String),
            sa.column("code", sa.String),
            sa.column("bik", sa.String),
            sa.column("is_popular", sa.Boolean),
        ),
        [{"name": name, "code": code, "bik": bik, "is_popular": popular} for name, code, bik, popular in BANKS],
    )


def downgrade() -> None:
    op.drop_index("ix_banks_bik", "banks")
    op.drop_index("ix_banks_code", "banks")
    op.drop_index("ix_banks_id", "banks")
    op.drop_table("banks")

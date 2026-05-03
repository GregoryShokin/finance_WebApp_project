"""Генерирует бинарные/специально закодированные фикстуры для теста импорта.

Запуск (из контейнера api, чтобы был openpyxl):
    docker compose exec -T api python /app/tests/import_fixtures/_generate_binary.py

Создаёт:
    simple_cp1251.csv  — то же содержимое что simple_expenses_utf8.csv, но в cp1251
    with_header_offset.xlsx — заголовок на 3-й строке, мусор сверху
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def make_cp1251():
    src = os.path.join(HERE, "simple_expenses_utf8.csv")
    dst = os.path.join(HERE, "simple_cp1251.csv")
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()
    with open(dst, "w", encoding="cp1251") as f:
        f.write(text)
    print(f"wrote {dst}")


def make_xlsx_with_offset():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Выписка"
    ws.append(["Отчёт по счёту"])
    ws.append(["Период: 01.04.2026 — 30.04.2026"])
    ws.append(["date", "description", "amount", "direction"])
    rows = [
        ("2026-04-01", "Озон покупка", -780.00, "expense"),
        ("2026-04-02", "Зарплата", 80000.00, "income"),
        ("2026-04-03", "Кофе с собой", -250.00, "expense"),
        ("2026-04-04", "Перевод другу", -1500.00, "expense"),
        ("2026-04-05", "Возврат", 320.00, "income"),
    ]
    for r in rows:
        ws.append(list(r))
    dst = os.path.join(HERE, "with_header_offset.xlsx")
    wb.save(dst)
    print(f"wrote {dst}")


if __name__ == "__main__":
    make_cp1251()
    make_xlsx_with_offset()

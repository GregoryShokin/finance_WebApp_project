from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CATEGORY_COLOR_PALETTE = [
    '#2563eb',  # blue
    '#7c3aed',  # violet
    '#db2777',  # pink
    '#ea580c',  # orange
    '#16a34a',  # green
    '#0891b2',  # cyan
    '#ca8a04',  # amber
    '#dc2626',  # red
    '#4f46e5',  # indigo
    '#0f766e',  # teal
    '#9333ea',  # purple
    '#0284c7',  # sky
    '#65a30d',  # lime
    '#c2410c',  # orange-dark
]


@dataclass(frozen=True)
class DefaultCategoryDefinition:
    name: str
    kind: str
    priority: str
    icon_name: str
    is_system: bool = False
    regularity: str = "regular"


# System category created automatically for every user (cannot be deleted/renamed).
# Decision 2026-04-19: credit_payment abolished — interest portion is classified as
# a regular expense in this category.
# Ref: financeapp-vault/01-Metrics/Поток.md
SYSTEM_CATEGORIES: tuple[DefaultCategoryDefinition, ...] = (
    DefaultCategoryDefinition(
        name="Проценты по кредитам",
        kind="expense",
        priority="expense_essential",
        icon_name="percent",
        is_system=True,
        regularity="regular",
    ),
)

DEFAULT_CATEGORIES: tuple[DefaultCategoryDefinition, ...] = (
    DefaultCategoryDefinition('Жильё', 'expense', 'expense_essential', 'house'),
    DefaultCategoryDefinition('Продукты', 'expense', 'expense_essential', 'shopping-basket'),
    DefaultCategoryDefinition('Транспорт', 'expense', 'expense_essential', 'car'),
    DefaultCategoryDefinition('Связь и интернет', 'expense', 'expense_essential', 'smartphone'),
    DefaultCategoryDefinition('Здоровье', 'expense', 'expense_essential', 'heart-pulse'),
    DefaultCategoryDefinition('Образование', 'expense', 'expense_essential', 'book-open'),
    DefaultCategoryDefinition('Кафе и рестораны', 'expense', 'expense_secondary', 'utensils-crossed'),
    DefaultCategoryDefinition('Маркетплейсы', 'expense', 'expense_secondary', 'shopping-bag'),
    DefaultCategoryDefinition('Одежда', 'expense', 'expense_secondary', 'shirt'),
    DefaultCategoryDefinition('Развлечения', 'expense', 'expense_secondary', 'clapperboard'),
    DefaultCategoryDefinition('Путешествия', 'expense', 'expense_secondary', 'plane'),
    DefaultCategoryDefinition('Подарки', 'expense', 'expense_secondary', 'gift'),
    DefaultCategoryDefinition('Красота и уход', 'expense', 'expense_secondary', 'sparkles'),
    DefaultCategoryDefinition('Животные', 'expense', 'expense_secondary', 'paw-print'),
)

DEFAULT_CATEGORY_LOOKUP = {item.name.casefold(): item for item in DEFAULT_CATEGORIES}


def resolve_category_icon_name(name: str) -> str:
    normalized = name.strip().casefold()
    default_item = DEFAULT_CATEGORY_LOOKUP.get(normalized)
    if default_item:
        return default_item.icon_name
    return 'tag'


def resolve_next_category_color(used_colors: list[str] | tuple[str, ...]) -> str:
    normalized_used = {str(color).strip().lower() for color in used_colors if color}
    for color in DEFAULT_CATEGORY_COLOR_PALETTE:
        if color.lower() not in normalized_used:
            return color

    if not normalized_used:
        return DEFAULT_CATEGORY_COLOR_PALETTE[0]

    usage_counts = {color.lower(): 0 for color in DEFAULT_CATEGORY_COLOR_PALETTE}
    for color in normalized_used:
        if color in usage_counts:
            usage_counts[color] += 1

    return min(DEFAULT_CATEGORY_COLOR_PALETTE, key=lambda item: (usage_counts.get(item.lower(), 0), DEFAULT_CATEGORY_COLOR_PALETTE.index(item)))

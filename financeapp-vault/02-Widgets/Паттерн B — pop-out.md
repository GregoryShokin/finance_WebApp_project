# Паттерн B — pop-out

#виджеты #ui

> Для виджетов с графиками и детализацией. Фиксированная ширина, одновременно открыт только один.

- Ширина: `min(860px, 100vw-2rem)`
- Позиция: `resolveExpandUp` + `resolveExpandDirection` из `widget-expand.ts`
- Анимация: `scale 0.6 → 1.0 + opacity`
- Одновременно открыт только один
- Координация через `FI_SCORE_WIDGET_EVENT`

---

## Связи
- Альтернатива: [[Паттерн A — scale]]
- Используется на [[Страница Dashboard]]
- Код: `frontend/lib/widget-expand.ts`

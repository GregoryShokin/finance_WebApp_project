# Фича — Frontend audit_notes vs issues (pre-emptive)
#бэклог #frontend #пост-mvp #низкий-приоритет

> Pre-emptive backlog: если UI начнёт рендерить `result.issues` как warnings/badges — `apply_decisions` audit-reasons (например, «operation_type из обученного правила #42») попадут в красную плашку. Юзер увидит их как проблемы, не как explanations.

---

## Контекст

Обнаружено при review Этапа 2 (2026-05-04). Pre-emptive — не блокер сейчас.

На 2026-05-04 grep подтверждает: `result.issues` нигде не рендерится в frontend как warning/error UI. Поле audit-only. Этап 2 пишет в `issues` строку `"operation_type из обученного правила #42"` через `decision.assignment_reasons` — безопасно, никто не видит.

## Риск

Если в будущем добавится UI-рендер `issues` (например, для review-flow), audit-reasons попадут в плашку рядом с реальными warnings. Юзер увидит «правило #42» как issue → confusion.

## Решение

Когда понадобится UI-рендер `issues` — разделить на два поля:

```typescript
type ImportPreviewRowResponse = {
  // ...
  issues: string[];        // warnings / errors (UI-warning style)
  audit_notes: string[];   // info-level explanations (UI-info style or hidden)
};
```

Backend:
- `EnrichmentSuggestion.review_reasons` → `issues` (нужно review).
- `EnrichmentSuggestion.assignment_reasons` + `DecisionRow.assignment_reasons` → `audit_notes` (informational).

## Тесты

```python
def test_apply_decisions_writes_audit_note_not_issue():
    # rule-based op_type → decision.audit_notes содержит reason
    # decision.issues НЕ содержит rule-related reason
```

## Скоуп

- Backend: новое поле `audit_notes` в `ImportPreviewRowResponse`.
- Refactor `result.issues.extend(suggestion.assignment_reasons)` → `result.audit_notes.extend(...)`.
- Frontend: новый секции в `tx-row.tsx` (если/когда понадобится).

## Эстимейт

0.5 дня (только backend split). Frontend visualization — отдельно при необходимости.

## Приоритет

**Низкий** — pre-emptive. Активируется только при появлении UI-рендера `issues`.

## Связанные документы

- Этап 2 review (2026-05-04) — Action #1 «issues vs audit_notes UI semantics».

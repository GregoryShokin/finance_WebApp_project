# Фича — Cleanup pre-existing test failures
#бэклог #техдолг #тесты #блокирует-launch

> 7 pre-existing test failures накопились от 2026-04 по 2026-05. Этап 0.7 Launch Gate требует «pytest зелёный».

---

## Список fails (на 2026-05-04)

### `test_bulk_cluster_grouping.py` — 4 fail

Все 4 fails об одной симптоме: тесты ожидают `cluster_size < 3` → пустой список, получают cluster=2. Похоже бизнес-правило `MIN_CLUSTER_SIZE` снизилось с 3 до 2 в коде, тесты не обновлены.

| Тест | Симптом |
|---|---|
| `TestGroupByBrand::test_brand_group_skipped_when_total_below_min_size` | `assert 2 == 3` |
| `TestBuildBulkClustersFilters::test_committed_rows_do_not_inflate_cluster_size` | `Left contains one more item: Cluster(...)` |
| `TestBuildBulkClustersFilters::test_rows_with_any_transfer_match_excluded` | `Left contains one more item: Cluster(...)` |
| `TestBuildBulkClustersFilters::test_duplicate_rows_dropped_but_remaining_cluster_still_qualifies` | `Left contains one more item: Cluster(...)` |

Action: `grep -rn "MIN_CLUSTER_SIZE\|cluster_size" app/` — найти когда понизился порог. Если intentional — обновить тесты на новое значение. Если случайный regression — фикс в коде.

### `test_auth_refresh.py` — 2 fail

Этап 0.1 (Refresh Token), требует прогона в docker compose. Не SQLite-фикстура, нужна реальная Postgres + Redis.

| Тест | Симптом |
|---|---|
| `test_login_returns_pair_and_persists_refresh_record` | требует docker stack |
| `test_revoke_all_for_user_only_marks_active_tokens` | требует docker stack |

Action: запустить `docker compose exec api pytest tests/test_auth_refresh.py` после старта стека и проверить что они зелёные. Если падают на docker — diagnostic.

### `test_category_rule_lifecycle.py::test_resolve_category_with_skip_llm_false_calls_llm_when_enabled` — 1 fail

LLM был удалён 2026-05-03 (см. CLAUDE.md). Тест ожидает что LLM вызывается, теперь LLM нет.

Action: либо удалить тест полностью, либо оставить с `@pytest.mark.skip(reason="LLM removed 2026-05-03")` для исторической ценности.

## Итого

7 fails:
- 4 — clean fix через `grep MIN_CLUSTER_SIZE` + обновление expected (или фикс кода если regression).
- 2 — docker run + проверка (могут быть зелёные при правильной env).
- 1 — удалить или skip.

## Эстимейт

1-2 часа на все 7. Большинство — не реальные регрессии, а stale тесты.

## Блокирует

Этап 0.7.4 Launch Gate (требует «полный pytest зелёный» как критерий closed-beta).

## Связанные документы

- [[Подготовка к запуску MVP]] Этап 0.7
- Этап 2 review (2026-05-04) — где fails были диагностированы.

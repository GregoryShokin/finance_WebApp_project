# Import normalization fixtures (И-08)

Golden dataset для нормализатора импорта (Phase 1). Два уровня:

```
raw/        ← реальные выписки, gitignored (персональные данные)
expected/   ← ожидаемые результаты нормализации, коммитится
```

## Правила приватности

**`raw/` никогда не попадает в git.** Это живые банковские выписки
с номерами карт, ФИО, балансами, контрагентами. Папка добавлена в
корневой `.gitignore` — проверяй, что файлы не застейджены, прежде
чем коммитить что-то рядом.

**`expected/` — только обработанные данные.** Никакого сырого
описания транзакций. Идентификаторы (договор, телефон, карта, IBAN)
хранятся как `sha256(value)[:16]`. ФИО и `counterparty_org` — как
`"PRESENT"` / `null`. `amounts`/`dates` — как счётчики (`amounts_count`,
`dates_count`), сами значения не сохраняются. `skeleton` — уже после
нормализации, идентификаторов там нет. `raw_description_sha256` —
sha16-хеш полного описания, привязывает expected к конкретной строке
raw-файла, но не раскрывает её содержание.

## Целевые сценарии

| Файл | Что должно проверяться |
|------|------------------------|
| `yandex_bank_implicit_direction.pdf` | Яндекс Банк: нет явного знака +/−, направление извлекается из контекста |
| `yandex_split_multirow_transfer.csv` | Яндекс Сплит: многострочный перевод (17569 + 431 = 18000). Phase 6 — расширение transfer_matcher под суммы-пары |
| `tbank_contract_numbers.pdf` | Т-Банк: номер договора в описании → токен `contract`, две строки с одним договором дают одинаковый fingerprint |
| `credit_card_repayments.xlsx` | Кредитная карта: погашения → operation=transfer, target — credit-счёт того же банка |
| `generic_plus_minus.csv` | Базовый случай: явные +/− суммы, простейший путь нормализации |

## Как добавить fixture

1. Положи исходный файл в `raw/<bank>_<scenario>.<ext>` (имя из таблицы выше).
2. Извлеки из выписки список строк в TSV-форме `<direction>\t<description>`
   (direction ∈ `expense` / `income` / `unknown`). Это одноразовая
   ручная работа — формат выписки у каждого банка свой, универсального
   парсера нет и для Phase 1.4 не планируется. Промежуточный TSV храни
   тоже в `raw/` (всё в папке gitignored).
3. Прогони генератор на получившемся TSV — он печатает draft expected
   в stdout:

   ```bash
   python -m scripts.generate_golden_expected \
       --fixture tbank_contract_numbers.pdf \
       --bank tbank \
       --account-id 0 \
       --input raw/tbank_contract_numbers.tsv \
     > expected/tbank_contract_numbers.expected.json
   ```

   Генератор никогда не пишет в `expected/` сам — редиректом управляешь
   ты. Все идентификаторы хешируются внутри скрипта; ФИО и orgs
   превращаются в `"PRESENT"`. Raw-описание в output не утекает.
4. Просмотри draft, оставь 10–20 репрезентативных строк (сверху
   генератор печатает все), убери лишние поля если появились
   ложные срабатывания регулярок.
5. Смени `status` с `"draft"` на `"ready"`.
6. Для raw-файлов в формате CSV тестовый раннер читает колонки
   `direction` и `description` напрямую. Для PDF/XLSX: когда первая
   такая raw-выписка появится, нужно будет дописать loader в
   `tests/test_import_normalizer_v2_golden.py` (`_load_raw_rows`). До
   тех пор тест на такой fixture скипается с явной причиной.

## Как тесты ведут себя без raw

Тест [test_import_normalizer_v2_golden.py](../../test_import_normalizer_v2_golden.py)
параметризуется по всем `expected/*.expected.json` и скипает
параметр если:

- `status == "pending_raw_fixture"` (expected — только скелет), или
- `raw/<fixture>` отсутствует, или
- для расширения raw-файла loader пока не реализован.

Юнит-тесты нормализатора (Phase 1.1/1.2/1.3) прогоняются на
синтетических входах независимо и не требуют raw. Unit-тест генератора
([test_generate_golden_expected.py](../../test_generate_golden_expected.py))
тоже работает без raw — проверяет `parse_input_lines` / `generate_expected`
на синтетических строках.

## Статус (2026-04-22)

Структура + infra (Phase 1.4) готовы. Все `expected/*.expected.json` —
скелеты со `status: "pending_raw_fixture"`. Наполнение raw → TSV →
генератор → expected идёт итеративно по ходу последующих фаз по мере
появления реальных выписок.

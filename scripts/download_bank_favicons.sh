#!/usr/bin/env bash
# Download bank favicons via Google's S2 favicon service into
# frontend/public/bank-logos/<code>.png. Used as a temporary stand-in for
# proper SVG brand assets.
#
# Re-run safe — overwrites existing files. Run once after adding new banks
# to alembic/versions/0045_add_banks_table.py.

set -euo pipefail

OUT="$(cd "$(dirname "$0")/../frontend/public/bank-logos" && pwd)"

# code:domain pairs — domain is whatever surface produces a usable favicon.
# Some banks have multiple domains; the "right" one is the one whose
# favicon is the brand mark.
PAIRS=(
  "sber:sberbank.ru"
  "tbank:tbank.ru"
  "alfa:alfabank.ru"
  "vtb:vtb.ru"
  "gazprombank:gazprombank.ru"
  "yandex:bank.yandex.ru"
  "ozon:ozonbank.ru"
  "raiffeisen:raiffeisen.ru"
  "rosbank:rosbank.ru"
  "psb:psbank.ru"
  "sovcombank:sovcombank.ru"
  "russkiy_standart:rsb.ru"
  "mts:mtsbank.ru"
  "pochta:pochtabank.ru"
  "otkrytie:open.ru"
  "home_credit:homecredit.ru"
  "domrf:domrfbank.ru"
  "rnkb:rncb.ru"
  "bks:bcs-bank.com"
  "akbars:akbars.ru"
  "bspb:bspb.ru"
  "uralsib:uralsib.ru"
  "smp:smpbank.ru"
  "vbrr:vbrr.ru"
  "absolut:absolutbank.ru"
  "avangard:avangard.ru"
  "expo:expobank.ru"
  "domrf_bank:domrfbank.ru"
  "renaissance:rencredit.ru"
  "zenit:zenit.ru"
)

for entry in "${PAIRS[@]}"; do
  code="${entry%%:*}"
  domain="${entry##*:}"
  url="https://www.google.com/s2/favicons?domain=${domain}&sz=128"
  out="$OUT/${code}.png"
  printf "→ %s ← %s\n" "$code" "$domain"
  curl -fsSL "$url" -o "$out" || echo "   (failed: $code)"
done

printf "\nDone. Files in: %s\n" "$OUT"
ls -la "$OUT" | tail -n +2

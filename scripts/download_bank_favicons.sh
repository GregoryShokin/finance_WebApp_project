#!/usr/bin/env bash
# Download bank logo PNGs into frontend/public/bank-logos/<code>.png.
#
# Strategy per bank:
#   1. Try the bank site's apple-touch-icon.png directly (typically 180-192px,
#      brand-quality; what banks ship for iOS home-screen pinning).
#   2. Fallback: Google S2 favicon service at sz=128 (low-res, sometimes a
#      generic placeholder — used only when the bank's apple-touch-icon
#      isn't reachable).
#
# Re-run safe — overwrites existing files. Run after adding new banks
# to alembic/versions/0045_add_banks_table.py. Codes match that seed.

set -euo pipefail

OUT="$(cd "$(dirname "$0")/../frontend/public/bank-logos" && pwd)"

# code:domain pairs. Domain should be the bank's primary site (or a
# subdomain that hosts the brand-quality apple-touch-icon).
PAIRS=(
  "sber:sberbank.ru"
  "tbank:tbank.ru"
  "alfa:alfabank.ru"
  "vtb:vtb.ru"
  "gazprombank:gazprombank.ru"
  "yandex:bank.yandex.ru"
  "ozon:finance.ozon.ru"
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

try_apple_touch() {
  # Probe a couple of common apple-touch-icon paths. Echo the URL of the
  # first one that returns a >1KB PNG; otherwise empty.
  local domain="$1"
  for path in "/apple-touch-icon.png" "/apple-touch-icon-precomposed.png" "/static/apple-touch-icon.png"; do
    local url="https://${domain}${path}"
    local tmp; tmp="$(mktemp)"
    if curl -fsSL --max-time 8 "$url" -o "$tmp" 2>/dev/null; then
      local size; size="$(wc -c <"$tmp")"
      if [ "$size" -gt 1000 ]; then
        echo "$url"
        rm -f "$tmp"
        return
      fi
    fi
    rm -f "$tmp"
  done
}

for entry in "${PAIRS[@]}"; do
  code="${entry%%:*}"
  domain="${entry##*:}"
  out="$OUT/${code}.png"

  apple_url="$(try_apple_touch "$domain")"
  if [ -n "$apple_url" ]; then
    printf "→ %-18s ← %s [apple-touch]\n" "$code" "$apple_url"
    curl -fsSL --max-time 10 "$apple_url" -o "$out" || echo "   (failed: $code)"
    continue
  fi

  google_url="https://www.google.com/s2/favicons?domain=${domain}&sz=128"
  printf "→ %-18s ← %s [google s2]\n" "$code" "$domain"
  curl -fsSL --max-time 10 "$google_url" -o "$out" || echo "   (failed: $code)"
done

printf "\nDone. Files in: %s\n" "$OUT"
ls -la "$OUT" | tail -n +2

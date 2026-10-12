#!/usr/bin/env bash
# Public smoke check of every site behind the edge Traefik.
# Prints "<http_code> <tls_ok> <redirect> <url>" per URL. Run before and after
# any edge change and diff the two outputs:
#   ./edge/smoke.sh > /tmp/before.txt   ...   ./edge/smoke.sh | diff /tmp/before.txt -
set -uo pipefail

URLS=(
  https://lemonfit.kolberg.uz/
  https://lemonfit.kolberg.uz/app/
  https://main.kolberg.uz/
  https://kp.kolberg.uz/app/
  https://lemonfit.kolberg.uz/static/admin/css/base.css
  https://lemonfit.kolberg.uz/api/
  https://dev.kolberg.uz/
  https://lemonfit.kolberg.uz/form/
  https://lemonfit.kolberg.uz/webhook/
  https://construction.kolberg.uz/form/
  https://syrop.kolberg.uz/webhook/
  https://tg-gateway.kolberg.uz/v1/messaging/webhook/
  https://whatsapp.kolberg.uz/
  https://mcp.kolberg.uz/
  https://icloud.mcp.kolberg.uz/
  https://postgres-mcp.kolberg.uz/
  https://database.kolberg.uz/
  https://medical-portal.botiq.uz/
  https://medical-portal.botiq.uz/api/
  http://lemonfit.kolberg.uz/
  https://bot.botiq.uz/health
  https://barbaza.botiq.uz/
  https://bubbleking.kolberg.uz/
  https://sklad.about-muse.uz/
  https://signage.kolberg.uz/
  https://syrop-recipebook.botiq.uz/
)

for url in "${URLS[@]}"; do
  out=$(curl -sS -o /dev/null --max-time 15 \
    -w '%{http_code} %{ssl_verify_result} %{redirect_url}' "$url" 2>/dev/null) || out="ERR - -"
  read -r code tls redirect <<<"$out"
  [[ "$tls" == "0" ]] && tls=tls-ok || tls="tls-$tls"
  printf '%s %s %s %s\n' "$code" "$tls" "${redirect:--}" "$url"
done

#!/usr/bin/env bash
# Cron wrapper: runs one pipeline pass and reports it to healthchecks.io.
set -u

cd "$(dirname "$0")/.." || exit 3

HC_PING_URL=$(sed -n 's/^HC_PING_URL=//p' .env | tail -n 1 | tr -d '\r')

ping() {
    [ -n "$HC_PING_URL" ] || return 0
    curl -fsS -m 10 --retry 3 -o /dev/null "${HC_PING_URL}$1" || true
}

ping /start
.venv/bin/companies-watch run --limit 100
code=$?
ping "/$code"
exit "$code"
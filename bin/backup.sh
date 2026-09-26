#!/usr/bin/env bash
# Nightly backup: pg_dump -> age -> Backblaze B2, verified by size and sha256.
set -euo pipefail

cd "$(dirname "$0")/.."

env_get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }

HC_URL=$(env_get HC_BACKUP_URL)
ping() {
    [ -n "$HC_URL" ] || return 0
    curl -fsS -m 10 --retry 3 -o /dev/null "${HC_URL}$1" || true
}

WORK=$(mktemp -d)
trap 'code=$?; rm -rf "$WORK"; ping "/$code"' EXIT
ping /start

DATABASE_URL=$(env_get DATABASE_URL)
BUCKET=$(env_get B2_BUCKET)
RECIPIENT=$(env_get AGE_RECIPIENT)
RCLONE_CONFIG_B2_TYPE=b2
RCLONE_CONFIG_B2_ACCOUNT=$(env_get B2_KEY_ID)
RCLONE_CONFIG_B2_KEY=$(env_get B2_APP_KEY)
export RCLONE_CONFIG_B2_TYPE RCLONE_CONFIG_B2_ACCOUNT RCLONE_CONFIG_B2_KEY

: "${DATABASE_URL:?DATABASE_URL is empty}"
: "${BUCKET:?B2_BUCKET is empty}"
: "${RECIPIENT:?AGE_RECIPIENT is empty}"
: "${RCLONE_CONFIG_B2_ACCOUNT:?B2_KEY_ID is empty}"
: "${RCLONE_CONFIG_B2_KEY:?B2_APP_KEY is empty}"

NAME="companies-watch-$(date -u +%Y%m%dT%H%M%SZ).dump.age"

pg_dump --format=custom --no-owner "$DATABASE_URL" > "$WORK/db.dump"
pg_restore --list "$WORK/db.dump" > /dev/null
age -r "$RECIPIENT" -o "$WORK/$NAME" "$WORK/db.dump"

LOCAL_SIZE=$(stat -c %s "$WORK/$NAME")
LOCAL_SHA=$(sha256sum "$WORK/$NAME" | cut -d ' ' -f 1)

rclone copyto "$WORK/$NAME" "b2:$BUCKET/$NAME"

REMOTE_SIZE=$(rclone lsf --format s "b2:$BUCKET/$NAME")
REMOTE_SHA=$(rclone cat "b2:$BUCKET/$NAME" | sha256sum | cut -d ' ' -f 1)

if [ "$REMOTE_SIZE" != "$LOCAL_SIZE" ]; then
    echo "size mismatch: local $LOCAL_SIZE, remote $REMOTE_SIZE" >&2
    exit 1
fi
if [ "$REMOTE_SHA" != "$LOCAL_SHA" ]; then
    echo "sha256 mismatch: local $LOCAL_SHA, remote $REMOTE_SHA" >&2
    exit 1
fi

echo "$LOCAL_SHA  $NAME" > "$WORK/$NAME.sha256"
rclone copyto "$WORK/$NAME.sha256" "b2:$BUCKET/$NAME.sha256"

echo "backup ok: $NAME, $LOCAL_SIZE bytes, sha256 $LOCAL_SHA" >&2
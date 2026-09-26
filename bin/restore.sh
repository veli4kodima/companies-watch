#!/usr/bin/env bash
# Restore drill: download a backup from B2, verify sha256, decrypt, restore into
# a throwaway Postgres container and compare row counts with the backup manifest.
# Usage: bin/restore.sh <age-identity-file> [backup-name|latest]
set -euo pipefail

cd "$(dirname "$0")/.."

IDENTITY=${1:?usage: bin/restore.sh <age-identity-file> [backup-name|latest]}
WANT=${2:-latest}
CONTAINER=cw-restore-check

env_get() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }

BUCKET=$(env_get B2_BUCKET)
RCLONE_CONFIG_B2_TYPE=b2
RCLONE_CONFIG_B2_ACCOUNT=$(env_get B2_KEY_ID)
RCLONE_CONFIG_B2_KEY=$(env_get B2_APP_KEY)
export RCLONE_CONFIG_B2_TYPE RCLONE_CONFIG_B2_ACCOUNT RCLONE_CONFIG_B2_KEY
rc() { rclone --config "" "$@"; }

: "${BUCKET:?B2_BUCKET is empty}"
: "${RCLONE_CONFIG_B2_ACCOUNT:?B2_KEY_ID is empty}"
: "${RCLONE_CONFIG_B2_KEY:?B2_APP_KEY is empty}"

WORK=$(mktemp -d)
cleanup() {
    docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

if [ "$WANT" = latest ]; then
    NAME=$(rc lsf --include '*.dump.age' "b2:$BUCKET" | sort | tail -n 1)
else
    NAME=$WANT
fi
: "${NAME:?no backups found in b2:$BUCKET}"
echo "restoring $NAME" >&2

for f in "$NAME" "$NAME.sha256" "$NAME.counts"; do
    rc copyto "b2:$BUCKET/$f" "$WORK/$f"
done

(cd "$WORK" && sha256sum --check --quiet "$NAME.sha256")
age -d -i "$IDENTITY" -o "$WORK/db.dump" "$WORK/$NAME"

docker run -d --rm --name "$CONTAINER" \
    -e POSTGRES_PASSWORD=check -e POSTGRES_DB=check postgres:16 > /dev/null
for _ in $(seq 60); do
    docker exec "$CONTAINER" pg_isready -q -h 127.0.0.1 -U postgres -d check && break
    sleep 1
done
docker exec "$CONTAINER" pg_isready -q -h 127.0.0.1 -U postgres -d check

docker exec -i "$CONTAINER" pg_restore -U postgres -d check --no-owner --exit-on-error \
    < "$WORK/db.dump"
docker exec -i "$CONTAINER" psql -U postgres -d check -At -F ' ' \
    < bin/row-counts.sql > "$WORK/restored.counts"

if diff -u "$WORK/$NAME.counts" "$WORK/restored.counts"; then
    echo "restore ok: $NAME, $(wc -l < "$WORK/restored.counts") tables, row counts match" >&2
else
    echo "row counts differ" >&2
    exit 1
fi
#!/usr/bin/env bash
# Run on the server, from anywhere: /opt/survey/deploy.sh
#
# 1. Build .env from Parameter Store (the server's IAM role is the only credential).
# 2. Pull the newest image.
# 3. Run database migrations *before* starting the new containers.
# 4. Start (or restart) everything.
# 5. Run Django's deployment check against the running container.
#
# Safe to run again at any time. To roll back, pin an older build first:
#   APP_IMAGE=ghcr.io/<owner>/<repo>:<commit-sha> ./deploy.sh

set -euo pipefail

cd "$(dirname "$0")"

REGION="${AWS_REGION:-us-west-2}"
SSM_PATH="${SSM_PATH:-/survey/prod}"

echo "==> Rendering .env from Parameter Store ($SSM_PATH, $REGION)"
# Write to a temporary file with owner-only permissions, then move it into place,
# so a failure half way never leaves a broken or world-readable .env behind.
umask 077
tmp="$(mktemp .env.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
aws ssm get-parameters-by-path \
  --path "$SSM_PATH" --with-decryption --region "$REGION" --output json \
  | python3 render_env.py "$SSM_PATH" > "$tmp"
mv "$tmp" .env

echo "==> Pulling images"
docker compose pull

echo "==> Applying migrations"
docker compose run --rm web python manage.py migrate --noinput

echo "==> Ensuring the cache table exists"
# Rate limits are counted in a PostgreSQL table (settings CACHES). The command
# does nothing if the table is already there.
docker compose run --rm web python manage.py createcachetable

echo "==> Starting containers"
docker compose up -d --remove-orphans

echo "==> Deployment check"
docker compose exec -T web python manage.py check --deploy --fail-level WARNING

# Old image layers pile up on a 20 GB disk. Remove only ones nothing uses.
docker image prune -f > /dev/null

echo "==> Done"

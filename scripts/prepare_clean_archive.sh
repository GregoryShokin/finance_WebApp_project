#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="$(basename "$ROOT_DIR")"
OUTPUT_DIR="$(dirname "$ROOT_DIR")"
OUTPUT_ARCHIVE="$OUTPUT_DIR/${PROJECT_NAME}_clean.zip"

cd "$ROOT_DIR"

rm -rf \
  ./.pytest_cache \
  ./.mypy_cache \
  ./.ruff_cache \
  ./htmlcov \
  ./__pycache__ \
  ./app/__pycache__ \
  ./alembic/__pycache__ \
  ./tests/__pycache__ \
  ./frontend/.next \
  ./frontend/out \
  ./frontend/node_modules \
  ./frontend/coverage

find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.tsbuildinfo' -o -name '*.log' \) -delete

rm -f ./.env ./frontend/.env.local

rm -f "$OUTPUT_ARCHIVE"
zip -rq "$OUTPUT_ARCHIVE" "$PROJECT_NAME" \
  -x '*/.git/*' \
  -x '*/node_modules/*' \
  -x '*/.next/*' \
  -x '*/__pycache__/*' \
  -x '*/.pytest_cache/*' \
  -x '*/.mypy_cache/*' \
  -x '*/.ruff_cache/*' \
  -x '*/htmlcov/*' \
  -x '*/coverage/*' \
  -x '*/.env' \
  -x '*/frontend/.env.local'

echo "Created archive: $OUTPUT_ARCHIVE"

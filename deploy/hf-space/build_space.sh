#!/bin/bash
# Assembles the Space build context:  deploy/hf-space/build_space.sh [output-dir]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd); OUT=${1:-/tmp/copilot-space}
rm -rf "$OUT" && mkdir -p "$OUT/data/manuals"
cp -R "$ROOT/app" "$OUT/app" && cp "$ROOT/alembic.ini" "$ROOT/requirements.txt" "$OUT/"
rsync -a --exclude node_modules --exclude dist "$ROOT/frontend/" "$OUT/frontend/"
cp "$ROOT/data/manuals/electric_motor_manual.pdf" "$OUT/data/manuals/"
cd "$ROOT/deploy/hf-space" && cp Dockerfile supervisord.conf nginx.conf start.sh seed.sh "$OUT/" && cp README.space.md "$OUT/README.md"
find "$OUT" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Space build context ready: $OUT"

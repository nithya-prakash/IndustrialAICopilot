#!/usr/bin/env bash
# Terminal walkthrough for the README demo recording.
# Assumes `docker compose up --build` is already running (all 8 services healthy).
# Run this in a freshly cleared terminal (e.g. `clear`) right before you start recording.
set -e

pause() { sleep "${1:-2}"; }
banner() {
  echo ""
  echo "── $1 ──────────────────────────────────────────────"
  pause 1
}

banner "1. Health check — is the stack actually up?"
curl -s localhost:8000/api/v1/health | python3 -m json.tool
pause 3

banner "2. Register a technician and get a JWT"
DEMO_USER="tech-demo-$(date +%s)"
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$DEMO_USER\",\"email\":\"$DEMO_USER@example.com\",\"password\":\"correct-horse-battery\",\"tenant_id\":\"acme\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "Token acquired: ${TOKEN:0:24}..."
pause 3

banner "3. Upload a real PDF manual — real extraction, OCR fallback, chunking, embedding, Qdrant indexing"
docker compose run --rm backend python scripts/generate_sample_manual.py
DOC_ID=$(curl -s -X POST localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/manuals/electric_motor_manual.pdf;type=application/pdf" \
  -F "equipment_type=electric_motor" -F "equipment_id=MOTOR-001" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "Document $DOC_ID uploaded — polling ingestion status..."
pause 2
for i in 1 2 3 4 5 6 7 8; do
  STATUS=$(curl -s localhost:8000/api/v1/documents/$DOC_ID -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
  echo "  status: $STATUS"
  [ "$STATUS" = "ready" ] && break
  sleep 2
done
pause 3

banner "4. Seed sensor history and pull real analytics — trend, anomalies, threshold check, all computed"
docker compose run --rm backend python scripts/seed_sensor_data.py acme
curl -s "localhost:8000/api/v1/sensors/MOTOR-001/analysis?metric=vibration_rms&start_time=2026-08-09T00:00:00Z&end_time=2026-08-23T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
pause 4

banner "5. Full test suite — 271 tests, real Postgres/Qdrant/Docker infra, no mocks at the infra layer"
docker compose run --rm backend python -m pytest -q
pause 3

banner "Done."

#!/bin/bash
# Creates the public demo workspace: an admin, a technician and a supervisor, and indexes the sample manual.
set -u
API=http://127.0.0.1:8000/api/v1; PW="${DEMO_PASSWORD:-Demo-Copilot-2026}"
for _ in $(seq 1 120); do curl -sf "$API/health" > /dev/null && break; sleep 2; done
post() { curl -s -X POST "$API$1" -H 'content-type: application/json' ${3:+-H "Authorization: Bearer $3"} -d "$2"; }
TOKEN=$(post /auth/register "{\"username\":\"demo_admin\",\"email\":\"admin@example.com\",\"password\":\"$PW\",\"tenant_id\":\"demo\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
[ -z "$TOKEN" ] && { echo "seed: workspace not created"; exit 1; }
post /users "{\"username\":\"demo_technician\",\"email\":\"tech@example.com\",\"password\":\"$PW\",\"role\":\"technician\"}" "$TOKEN" > /dev/null
post /users "{\"username\":\"demo_supervisor\",\"email\":\"supervisor@example.com\",\"password\":\"$PW\",\"role\":\"supervisor\"}" "$TOKEN" > /dev/null
curl -s -X POST "$API/documents/upload" -H "Authorization: Bearer $TOKEN" -F "file=@/home/user/sample/electric_motor_manual.pdf" > /dev/null
echo "seed: demo workspace ready"

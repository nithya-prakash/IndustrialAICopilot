#!/usr/bin/env bash
# End-to-end deployment walkthrough for the README recording: start the whole stack, then use it.
# Needs Docker, the images built (`docker compose build`), a working LLM in .env, and curl + python3.
set -u
pause() { sleep "${1:-2}"; }
banner() { echo ""; echo "── $1 ──"; pause 1; }
field() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
API=localhost:8000/api/v1
STAMP=$(date +%s)

banner "1. Start the whole stack: Postgres, Qdrant, Redis, API, worker, web UI, Prometheus, Grafana"
docker compose down 2>&1 | grep -c Removed | sed 's/^/containers stopped: /'
docker compose up -d --wait 2>&1 | grep -E "Container .*(Healthy|Started)" | sed 's/ Container //' | head -12
docker compose ps --format "table {{.Service}}\t{{.Status}}"
pause 3

banner "2. Health check"
curl -s $API/health | python3 -m json.tool
pause 3

banner "3. Create a company workspace (you become its admin), then add a supervisor"
TOKEN=$(curl -s -X POST $API/auth/register -H "Content-Type: application/json" \
  -d "{\"username\":\"plant-$STAMP\",\"email\":\"plant-$STAMP@example.com\",\"password\":\"correct-horse-battery\",\"tenant_id\":\"plant-$STAMP\"}" | field "d['access_token']")
echo "admin token: ${TOKEN:0:24}..."
curl -s -X POST $API/users -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"username\":\"sup-$STAMP\",\"email\":\"sup-$STAMP@example.com\",\"password\":\"correct-horse-battery\",\"role\":\"supervisor\"}" \
  | field "'created supervisor ' + d['username'] + ' (role ' + d['role'] + ')'"
pause 3

banner "4. Upload a real public manual (DOE motor-systems tip sheet): extract, chunk, embed, index"
DOC=$(curl -s -X POST $API/documents/upload -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/manuals/eval/extend_motor_operlife_motor_systemts3.pdf;type=application/pdf" \
  -F "equipment_type=hydraulic_system" -F "equipment_id=HYDRAULIC-001" | field "d['id']")
for i in $(seq 1 30); do
  curl -s $API/documents/$DOC -H "Authorization: Bearer $TOKEN" | field "d['status'] + ', ' + str(d['chunk_count']) + ' chunks, ' + str(d['page_count']) + ' pages'" | sed 's/^/  /'
  curl -s $API/documents/$DOC -H "Authorization: Bearer $TOKEN" | field "d['status']" | grep -q ready && break
  sleep 2
done
pause 3

banner "5. Load real sensor history from a hydraulic test rig (UCI, CC BY 4.0) and analyse it"
docker compose run --rm -v "$PWD/data/sensors:/app/data/sensors" backend python scripts/seed_sensor_data.py "plant-$STAMP" 2>/dev/null | grep -E "loaded|skip"
curl -s "$API/sensors/HYDRAULIC-001/analysis?metric=temperature&start_time=2026-08-09T00:00:00Z&end_time=2026-08-10T13:00:00Z" \
  -H "Authorization: Bearer $TOKEN" | field "{k: d[k] for k in ('metric','trend','anomalies') if k in d}" | cut -c1-230
pause 3

banner "6. Ask the supervised agent: it gathers manual and sensor evidence, then proposes a diagnosis"
echo "question: the rig's temperature keeps climbing and motor power looks high - what should I check?"
RESP=$(curl -s --max-time 1500 -X POST $API/copilot/query/supervised -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"The hydraulic rig temperature keeps climbing and motor power looks high. What should I check first?","equipment_id":"HYDRAULIC-001"}')
echo "$RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('status:', d['status'], '| severity:', d['severity'], '| confidence:', d['confidence'], '| needs human approval:', d['requires_human_approval'])
for c in d['possible_causes'][:3]: print(f\"  {c['rank']}. {c['cause'][:110]}  {c['supporting_citations'][:1]}\")
print('evidence items:', len(d['evidence']), '| model:', d['llm_provider'], d['llm_model'])"
DIAG=$(echo "$RESP" | field "d['id']")
pause 4

banner "7. A supervisor reviews and approves; every decision lands in the audit log"
STOKEN=$(curl -s -X POST $API/auth/login -H "Content-Type: application/json" \
  -d "{\"username\":\"sup-$STAMP\",\"password\":\"correct-horse-battery\"}" | field "d['access_token']")
curl -s -X POST $API/diagnoses/$DIAG/approve -H "Authorization: Bearer $STOKEN" -H "Content-Type: application/json" \
  -d '{"comments":"Checked on site, proceeding with the cooler inspection"}' | field "'decision: ' + d['approval']['decision'] + ' by supervisor'"
curl -s $API/audit-logs -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
for a in json.load(sys.stdin)[:6]: print('  audit:', a.get('action'), a.get('resource_type', ''))"
pause 3

banner "8. Prometheus is scraping the API"
curl -s "localhost:9091/api/v1/query?query=up" | python3 -c "
import sys,json
for r in json.load(sys.stdin)['data']['result']: print('  target', r['metric'].get('job'), 'up =', r['value'][1])"
pause 3
banner "Done: web UI on :3002, API docs on :8000/docs, Grafana on :3003"

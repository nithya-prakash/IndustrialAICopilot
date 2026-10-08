# Sample multimodal input and output

A diagnosis combines a question, optional sensor readings, an optional component photo and the manuals
already indexed for the workspace. All calls need a bearer token (`POST /api/v1/auth/login`).

## 1. Index a manual
```bash
curl -X POST localhost:8000/api/v1/documents/upload -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/manuals/electric_motor_manual.pdf"
```

## 2. Optional: analyze a photo
```bash
curl -X POST localhost:8000/api/v1/images/analyze -H "Authorization: Bearer $TOKEN" \
  -F "file=@motor.jpg" -F "equipment_id=MOTOR-001" -F "question=Is there visible damage?"
# -> {"id": "<image_analysis_id>", ...structured visual observations with confidence...}
```
The repo ships no sample photo; use a photo of your own. The vision model needs a provider with image
input (`VISION_PROVIDER`), and small local models give shallow observations (see Limitations).

## 3. Ask
```bash
curl -X POST localhost:8000/api/v1/copilot/query -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{
    "question": "The motor housing feels very hot. What could be wrong?",
    "equipment_id": "MOTOR-001",
    "sensor_readings": {"temperature": 91.5, "vibration_rms": 5.2},
    "image_analysis_id": "<id from step 2, optional>"
  }'
```
Use `/api/v1/copilot/query/supervised` for the LangGraph supervisor (specialist agents, maintenance planner,
approval pause). Sample sensor history: `data/sensors/motor_001.csv`.

## Output
[`docs/sample-diagnosis.json`](sample-diagnosis.json) is a real stored response (question only, manual indexed,
Groq `gpt-oss-120b`): ranked causes, each with citations to the manual section it came from, a computed confidence,
severity, the recommended action and checks, limitations, and `requires_human_approval`. A supervisor then
approves or rejects it in the web app; the decision is recorded in the audit log.

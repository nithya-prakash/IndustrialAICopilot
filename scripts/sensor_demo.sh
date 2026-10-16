#!/usr/bin/env bash
# Terminal walkthrough of the real-sensor pipeline, for the README recording.
# Needs `docker compose` services (postgres) reachable; downloads nothing if data/sensors/ is populated.
set -e
pause() { sleep "${1:-2}"; }
banner() { echo ""; echo "── $1 ──"; pause 1; }
run() { docker compose run --rm -v "$PWD/data/sensors:/app/data/sensors" backend "$@" 2>/dev/null; }

banner "1. Real recordings: UCI hydraulic test rig, one row per 60 s load cycle"
head -4 data/sensors/hydraulic_001.csv | cut -c1-100
pause 3

banner "2. Component conditions kept apart from the sensor readings"
head -4 data/sensors/hydraulic_001_labels.csv
pause 3

banner "3. Load the history for a workspace (7 sensors x 2,205 cycles)"
run python scripts/seed_sensor_data.py "demo-$(date +%s)" 2>&1 | grep -E "loaded|skip"
pause 3

banner "4. Can the baseline checks spot a degraded component? (AUROC)"
run python -m evaluation.sensor_fault_eval --compact 2>&1 | grep -v Warning
pause 5
echo ""
echo "Cooler and pump leaks are easy; valve and accumulator faults need all sensors together."
pause 4

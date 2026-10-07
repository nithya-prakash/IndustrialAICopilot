"""Load test:  locust -f loadtest/locustfile.py --host http://localhost:8000

Env: LOAD_USERNAME / LOAD_PASSWORD (an existing user; create one first).
LOAD_SKIP_AI=1 skips the copilot endpoints (a local 7B model takes minutes per call).
Weights keep cheap endpoints dominant. AI endpoints are rate limited (see
RATE_LIMIT_AI), so 429s are counted as expected throttling, not failures —
the interesting numbers are latency of the non-AI paths and how the limiter
behaves under pressure.
"""

import os
import random

from locust import HttpUser, between, task

QUESTIONS = [
    "What should I check if motor vibration increases?",
    "The motor housing feels very hot. What could be wrong?",
    "I hear a grinding noise from the motor.",
]


class Technician(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        res = self.client.post(
            "/api/v1/auth/login",
            json={
                "username": os.environ["LOAD_USERNAME"],
                "password": os.environ["LOAD_PASSWORD"],
            },
        )
        self.client.headers["Authorization"] = f"Bearer {res.json()['access_token']}"

    @task(5)
    def health(self):
        self.client.get("/api/v1/health")

    @task(3)
    def list_diagnoses(self):
        self.client.get("/api/v1/diagnoses")

    @task(1)
    def ask_copilot(self):
        if os.environ.get("LOAD_SKIP_AI"):
            return
        with self.client.post(
            "/api/v1/copilot/query/supervised"
            if random.random() < 0.5
            else "/api/v1/copilot/query",
            json={"question": random.choice(QUESTIONS), "equipment_id": "MOTOR-001"},
            catch_response=True,
        ) as res:
            if res.status_code == 429:
                res.success()  # expected: AI rate limit

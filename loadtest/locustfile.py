"""Load test:  locust -f loadtest/locustfile.py --host http://localhost:8000

Env: LOAD_USERNAME / LOAD_PASSWORD (an existing user in a workspace that has the sample manual).
Two user types: `Reader` (cheap endpoints, default weight) and `Diagnostician` (real LLM
diagnoses; weight 0 unless LOAD_AI_USERS is set, so a read-only run needs no model).
Per-IP rate limits apply to all locust users (one IP); raise RATE_LIMIT_* on the server for a
capacity run, otherwise 429s are counted as expected throttling rather than failures.
"""

import os
import random

from locust import HttpUser, between, task

QUESTIONS = [
    "What should I check if motor vibration increases?",
    "The motor housing feels very hot. What could be wrong?",
    "I hear a grinding noise from the motor.",
]


class _Base(HttpUser):
    abstract = True

    def on_start(self):
        res = self.client.post(
            "/api/v1/auth/login",
            json={"username": os.environ["LOAD_USERNAME"], "password": os.environ["LOAD_PASSWORD"]},
            name="login",
        )
        self.client.headers["Authorization"] = f"Bearer {res.json()['access_token']}"

    def _get(self, path, name=None):
        with self.client.get(path, name=name or path, catch_response=True) as r:
            if r.status_code == 429:
                r.success()


class Reader(_Base):
    weight = 10
    wait_time = between(0.5, 2)

    @task(5)
    def health(self):
        self._get("/api/v1/health")

    @task(3)
    def list_diagnoses(self):
        self._get("/api/v1/diagnoses")

    @task(2)
    def list_documents(self):
        self._get("/api/v1/documents")


class Diagnostician(_Base):
    weight = int(os.environ.get("LOAD_AI_USERS", "0"))
    wait_time = between(5, 15)

    @task
    def ask(self):
        path = random.choice(["/api/v1/copilot/query", "/api/v1/copilot/query/supervised"])
        with self.client.post(
            path,
            json={"question": random.choice(QUESTIONS), "equipment_id": "MOTOR-001"},
            name=path,
            catch_response=True,
            timeout=300,
        ) as r:
            if r.status_code == 429:
                r.success()  # throttled by our limiter: expected
            elif r.status_code == 200 and r.json().get("status") != "completed":
                r.failure("diagnosis failed: " + str(r.json().get("error_message"))[:80])

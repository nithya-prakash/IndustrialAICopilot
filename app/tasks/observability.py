"""Prometheus metrics for the Celery worker process.

The FastAPI backend's /metrics endpoint (app/main.py) only ever covered
the HTTP/LLM/agent path it directly serves — the Celery worker running
document ingestion was never scraped at all. Wiring it in isn't just
"add a Counter": the worker runs a prefork pool (docker-compose.yml's
`--concurrency=2`), meaning task code executes in forked child processes,
each with its own memory space. prometheus_client's default in-memory
registry can't aggregate across those — a counter incremented in one fork
is invisible to the others. This uses prometheus_client's documented
multiprocess mode instead: every process (main + forked children) writes
metric deltas to files under PROMETHEUS_MULTIPROC_DIR, and a small HTTP
server started once in the main process (before forking, via Celery's
worker_init signal) aggregates those files and exposes the combined view
for Prometheus to scrape — see docker-compose.yml's `worker` service and
observability/prometheus/prometheus.yml for the wiring.

Importing this module registers the signal handlers below (Celery signals
are connected at import time, not called directly) — see
app/tasks/celery_app.py.
"""
import os
import shutil
import time

from celery.signals import task_failure, task_prerun, task_retry, task_success, worker_init

from app.observability.metrics import celery_task_duration_seconds, celery_tasks_total

_task_start_times: dict[str, float] = {}


def reset_multiprocess_dir(path: str) -> None:
    """Stale .db files from a previous run of this same directory would
    double-count against process IDs that no longer exist once the worker
    restarts and forks new children with reused PIDs — prometheus_client's
    own multiprocess documentation recommends clearing the directory at
    startup for exactly this reason. NOT called from _on_worker_init below:
    by the time that signal fires, this process has already imported
    app.observability.metrics (celery_app.py imports this module, which
    imports that one), and prometheus_client opens each Counter/Gauge's
    mmap file in PROMETHEUS_MULTIPROC_DIR at construction time — i.e. at
    that import, not at worker_init. Calling this here would unlink files
    those metric objects already have open, silently losing whatever they
    recorded before the collector ever reads the (now-recreated) directory.
    The actual reset happens earlier, at the shell level, in the worker
    service's `command:` in docker-compose.yml, before `celery` (and so
    Python) ever starts. Kept here as a standalone, tested utility for that
    same shell-level use, not because anything in this module calls it."""
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def _start_metrics_server(port: int) -> None:
    from prometheus_client import CollectorRegistry, multiprocess, start_http_server

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(port, registry=registry)


@worker_init.connect
def _on_worker_init(**kwargs) -> None:
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return  # multiprocess metrics not configured for this environment — skip, don't fail
    port = int(os.environ.get("CELERY_METRICS_PORT", "8001"))
    _start_metrics_server(port)


@task_prerun.connect
def _on_task_prerun(task_id=None, **kwargs) -> None:
    _task_start_times[task_id] = time.perf_counter()


def _pop_duration(task_id: str) -> float:
    start = _task_start_times.pop(task_id, None)
    return time.perf_counter() - start if start is not None else 0.0


@task_success.connect
def _on_task_success(sender=None, **kwargs) -> None:
    task_name = sender.name
    task_id = sender.request.id
    celery_tasks_total.labels(task_name=task_name, status="success").inc()
    celery_task_duration_seconds.labels(task_name=task_name).observe(_pop_duration(task_id))


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, **kwargs) -> None:
    task_name = sender.name
    celery_tasks_total.labels(task_name=task_name, status="failure").inc()
    celery_task_duration_seconds.labels(task_name=task_name).observe(_pop_duration(task_id))


@task_retry.connect
def _on_task_retry(sender=None, **kwargs) -> None:
    celery_tasks_total.labels(task_name=sender.name, status="retry").inc()

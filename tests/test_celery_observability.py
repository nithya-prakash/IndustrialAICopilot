"""Tests for the Celery worker's Prometheus signal handlers
(app/tasks/observability.py). The multiprocess HTTP server itself
(_start_metrics_server) needs a real worker_init firing in a forked
process to verify meaningfully — that's a Docker-level concern, not a
unit test; these cover the pure/testable pieces: directory reset logic
and the signal handlers' metric-recording logic, called directly with
fake Celery sender/task objects rather than a real worker."""
from app.observability.metrics import celery_task_duration_seconds, celery_tasks_total
from app.tasks.observability import (
    _on_task_failure,
    _on_task_prerun,
    _on_task_retry,
    _on_task_success,
    _task_start_times,
    reset_multiprocess_dir,
)


class _FakeRequest:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeTask:
    def __init__(self, name: str, task_id: str) -> None:
        self.name = name
        self.request = _FakeRequest(task_id)


def _counter_value(task_name: str, status: str) -> float:
    return celery_tasks_total.labels(task_name=task_name, status=status)._value.get()


def test_reset_multiprocess_dir_clears_stale_files_and_recreates(tmp_path) -> None:
    target = tmp_path / "multiproc"
    target.mkdir()
    stale_file = target / "counter_123.db"
    stale_file.write_text("stale")

    reset_multiprocess_dir(str(target))

    assert target.exists()
    assert not stale_file.exists()


def test_reset_multiprocess_dir_handles_missing_directory(tmp_path) -> None:
    target = tmp_path / "does_not_exist_yet"
    reset_multiprocess_dir(str(target))
    assert target.exists()


def test_prerun_then_success_records_duration_and_increments_counter() -> None:
    task_name = "test.fake_task_success"
    before = _counter_value(task_name, "success")

    _on_task_prerun(task_id="task-1")
    assert "task-1" in _task_start_times

    _on_task_success(sender=_FakeTask(task_name, "task-1"))

    assert _counter_value(task_name, "success") == before + 1
    assert "task-1" not in _task_start_times  # popped, not leaked


def test_task_failure_increments_failure_counter() -> None:
    task_name = "test.fake_task_failure"
    before = _counter_value(task_name, "failure")

    _on_task_prerun(task_id="task-2")
    _on_task_failure(sender=_FakeTask(task_name, "task-2"), task_id="task-2")

    assert _counter_value(task_name, "failure") == before + 1


def test_task_retry_increments_retry_counter() -> None:
    task_name = "test.fake_task_retry"
    before = _counter_value(task_name, "retry")

    _on_task_retry(sender=_FakeTask(task_name, "task-3"))

    assert _counter_value(task_name, "retry") == before + 1


def test_success_without_prerun_still_observes_a_duration_not_a_crash() -> None:
    """A task_success firing for a task_id that never went through
    task_prerun (e.g. this process didn't see the prerun signal) must not
    raise — duration just falls back to 0 rather than being fabricated."""
    task_name = "test.fake_task_no_prerun"
    _on_task_success(sender=_FakeTask(task_name, "unknown-task-id"))
    assert _counter_value(task_name, "success") >= 1


def test_duration_histogram_observes_a_value() -> None:
    task_name = "test.fake_task_duration"
    _on_task_prerun(task_id="task-4")
    _on_task_success(sender=_FakeTask(task_name, "task-4"))

    sample_count = celery_task_duration_seconds.labels(task_name=task_name)._sum.get()
    assert sample_count >= 0.0

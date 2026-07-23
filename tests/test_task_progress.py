from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.services.task_service import TaskService


def test_progress_reports_ramp_and_running_phases():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = SimpleNamespace(status="running", started_at=started, fio_options='{"runtime_seconds": 60, "ramp_time_seconds": 10}')
    assert TaskService.progress(task, started + timedelta(seconds=5)) == (7, "预热中", 5, 70)
    assert TaskService.progress(task, started + timedelta(seconds=20)) == (28, "正式测试中", 20, 70)


def test_progress_reports_completed_task():
    task = SimpleNamespace(status="completed", started_at=None, fio_options='{"runtime_seconds": 60, "ramp_time_seconds": 10}')
    assert TaskService.progress(task) == (100, "已完成", 70, 70)

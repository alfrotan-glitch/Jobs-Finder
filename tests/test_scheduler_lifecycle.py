from __future__ import annotations

import asyncio

import pytest

import scheduler as scheduler_module


@pytest.fixture(autouse=True)
def clean_scheduler():
    try:
        scheduler_module.stop_scheduler()
    except Exception:
        pass
    for job_id in ["discover", "score", "email", "follow_up"]:
        try:
            scheduler_module.scheduler.remove_job(job_id)
        except Exception:
            pass
    scheduler_module._configured = False
    yield
    try:
        scheduler_module.stop_scheduler()
    except Exception:
        pass
    for job_id in ["discover", "score", "email", "follow_up"]:
        try:
            scheduler_module.scheduler.remove_job(job_id)
        except Exception:
            pass
    scheduler_module._configured = False


def profile(enabled=True, interval=6):
    return {
        "personal": {"first_name": "Allah", "last_name": "Frotan", "email": "doctor@example.org"},
        "watcher": {"enabled": enabled, "scan_interval_hours": interval, "deadline_alert_days": [7, 3, 1]},
        "schedule": {"enabled": enabled, "job_watch_interval_hours": interval, "score_interval_minutes": 60},
        "job_sources": {"test": {"enabled": True}},
    }


@pytest.mark.asyncio
async def test_scheduler_starts_when_configured(monkeypatch):
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=2))
    scheduler_module.setup_scheduler()
    assert scheduler_module.get_scheduler_status()["running"] is False
    assert {job.id for job in scheduler_module.scheduler.get_jobs()} >= {"discover", "score", "follow_up"}
    scheduler_module.start_scheduler()
    assert scheduler_module.get_scheduler_status()["running"] is True
    scheduler_module.stop_scheduler()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_disabled_scheduler_removes_jobs_and_does_not_run(monkeypatch):
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=2))
    scheduler_module.setup_scheduler()
    scheduler_module.start_scheduler()
    assert scheduler_module.scheduler.running
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=False, interval=2))
    scheduler_module.setup_scheduler()
    await asyncio.sleep(0.05)
    assert scheduler_module.get_scheduler_status()["running"] is False
    assert scheduler_module.scheduler.get_jobs() == []


def test_configured_interval_is_respected(monkeypatch):
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=4))
    scheduler_module.setup_scheduler()
    job = scheduler_module.scheduler.get_job("discover")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 4 * 3600


def test_duplicate_scheduler_instances_are_prevented(monkeypatch):
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=3))
    scheduler_module.setup_scheduler()
    scheduler_module.setup_scheduler()
    ids = [job.id for job in scheduler_module.scheduler.get_jobs()]
    assert len(ids) == len(set(ids))
    assert ids.count("discover") == 1


@pytest.mark.asyncio
async def test_failed_scan_does_not_kill_scheduled_job(monkeypatch):
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=2))

    async def boom(_profile):
        raise RuntimeError("network outage")

    import utils.job_watcher as watcher

    monkeypatch.setattr(watcher, "run_job_watch_scan", boom)
    await scheduler_module.scheduled_job_watch_scan()
    assert "network outage" in scheduler_module._last_results["job_watch"]["error"]


@pytest.mark.asyncio
async def test_scheduler_executes_scan_and_survives_until_shutdown(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_module, "get_profile", lambda: profile(enabled=True, interval=0.01))

    async def fake_scan(_profile):
        calls.append("ran")
        return {"scan_id": "scan-test", "new_count": 0, "updated_count": 0, "unchanged_count": 0}

    import utils.job_watcher as watcher

    monkeypatch.setattr(watcher, "run_job_watch_scan", fake_scan)
    scheduler_module.setup_scheduler()
    # Make the first run very soon so the test does not wait for the full interval.
    scheduler_module.start_scheduler()
    scheduler_module.scheduler.get_job("discover").modify(next_run_time=__import__("datetime").datetime.now())
    await asyncio.sleep(0.25)
    assert calls
    assert scheduler_module.scheduler.running
    scheduler_module.stop_scheduler()
    await asyncio.sleep(0.05)
    assert scheduler_module.get_scheduler_status()["running"] is False


def test_manual_discover_alias_uses_same_underlying_watcher():
    assert scheduler_module.scheduled_discover.__doc__
    assert scheduler_module.scheduled_job_watch_scan.__doc__
    assert scheduler_module.scheduled_discover.__name__ == "scheduled_discover"

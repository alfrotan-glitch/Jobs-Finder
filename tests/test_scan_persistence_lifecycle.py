"""Regression coverage for the real discovery-to-match persistence lifecycle.

The scan itself performs HTTP detail work concurrently, but matching and tracker
writes are synchronous.  These tests keep that distinction explicit and verify
that each retained vacancy is inserted and matched on one SQLite writer
transaction, including when the canonical database already contains rows.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import get_ident

import main
from utils import tracker
from utils.discovery import Job, ScanResult, SourceReport
from utils.recommendations import evaluate_scan_jobs


def _job(job_id: str) -> Job:
    return Job(
        job_id,
        "Medical Officer",
        "Example Health Organisation",
        "Kabul",
        f"https://example.org/jobs/{job_id}",
        "hr@example.org",
        "ACBAR",
        "A medical officer vacancy.",
        metadata={
            "source_name": "ACBAR",
            "source_url": "https://example.org/jobs",
            "vacancy_url": f"https://example.org/jobs/{job_id}",
            "application_method": "email",
        },
    )


def _scan(jobs: list[Job]) -> ScanResult:
    return ScanResult(
        "SCANNED",
        jobs,
        [SourceReport("acbar", "ACBAR", "A", attempted=True, ok=True, status="SCANNED")],
        "start",
        "finish",
        "Complete",
    )


def test_real_scan_pairs_use_one_connection_and_leave_no_transaction(
    tmp_path: Path, monkeypatch, capsys
):
    """The production CLI path must not INSERT on one connection then UPDATE on another."""
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    monkeypatch.setenv("JOBS_FINDER_DB_DIAGNOSTICS", "1")
    scan = _scan([_job("pair-1"), _job("pair-2"), _job("pair-3")])

    async def fake_discovery(profile):
        return scan

    monkeypatch.setattr(main, "run_discovery_scan", fake_discovery)
    asyncio.run(main.cmd_scan({}))
    trace = [
        json.loads(line.split(" ", 1)[1])
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("JOBS_FINDER_DB_TRACE ")
    ]

    pairs = [item for item in trace if item["operation"] == "scan_pair"]
    assert [item["phase"] for item in pairs].count("before_begin_immediate") == 3
    assert [item["phase"] for item in pairs].count("after_begin_immediate") == 3
    assert [item["phase"] for item in pairs].count("before_commit") == 3
    assert [item["phase"] for item in pairs].count("after_commit") == 3
    assert all(item["pid"] == trace[0]["pid"] for item in pairs)
    assert len({item["thread_id"] for item in pairs}) == 1
    assert all(item["query_only"] == 0 for item in pairs)
    assert all(item["journal_mode"].lower() == "wal" for item in pairs)
    assert all(item["locking_mode"].lower() == "normal" for item in pairs)
    assert all(item["in_transaction"] is False for item in pairs if item["phase"] == "after_commit")
    assert all(item["database_path"].endswith("applications.db") for item in pairs)

    with sqlite3.connect(tmp_path / "applications.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM vacancies WHERE match_json <> ''").fetchone()[0] == 3


def test_public_discovered_then_match_still_commits_and_closes(tmp_path, monkeypatch):
    """The public helpers retain their documented independent-operation contract."""
    db = tmp_path / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", db)
    job = _job("public-sequence")

    tracker.log_discovered(job)
    assert tracker.get_job_by_id(job.id)["status"] == tracker.FOUND
    tracker.log_medical_match(job.id, {"readiness_status": "NEEDS_VERIFICATION"})

    stored = tracker.get_job_by_id(job.id)
    assert stored["readiness"] == "NEEDS_VERIFICATION"
    assert stored["match"]["readiness_status"] == "NEEDS_VERIFICATION"
    assert stored["status"] == tracker.NEEDS_VERIFICATION


def test_existing_database_scan_updates_rows_without_duplicates(tmp_path, monkeypatch):
    """The exact production order also works against an already-populated DB."""
    db = tmp_path / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", db)
    existing = _job("existing-production-row")
    tracker.log_discovered(existing)

    evaluate_scan_jobs(_scan([existing, _job("second-production-row")]), {})

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 2
        row = conn.execute(
            "SELECT readiness, match_json FROM vacancies WHERE id = ?", (existing.id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "NEEDS_VERIFICATION"
        assert "readiness_status" in row[1]


def test_scan_writer_is_sequential_even_when_several_jobs_are_retained(tmp_path, monkeypatch):
    """Discovery detail fetching may be concurrent; evaluate_scan_jobs is not."""
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "applications.db")
    original = tracker.log_discovered_and_medical_match
    active = 0
    maximum = 0
    calls: list[tuple[str, int]] = []

    def wrapped(job, report):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        calls.append((job.id, get_ident()))
        try:
            original(job, report)
        finally:
            active -= 1

    monkeypatch.setattr(tracker, "log_discovered_and_medical_match", wrapped)
    evaluate_scan_jobs(_scan([_job("sequential-1"), _job("sequential-2"), _job("sequential-3")]), {})

    assert [job_id for job_id, _thread in calls] == ["sequential-1", "sequential-2", "sequential-3"]
    assert maximum == 1
    assert len({thread for _job_id, thread in calls}) == 1


def test_tracker_serializes_explicitly_concurrent_scan_pairs(tmp_path, monkeypatch):
    """If two scan callers overlap, each pair still owns one SQLite writer tx."""
    db = tmp_path / "applications.db"
    monkeypatch.setattr(tracker, "DB_PATH", db)

    def persist(index: int) -> None:
        tracker.log_discovered_and_medical_match(
            _job(f"concurrent-{index}"), {"readiness_status": "NEEDS_VERIFICATION"}
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(persist, range(8)))

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM vacancies WHERE readiness = 'NEEDS_VERIFICATION'").fetchone()[0] == 8

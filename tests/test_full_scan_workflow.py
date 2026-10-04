"""End-to-end integration test of a complete CLI scan.

Setup:
* a profile.yaml holding verified medical facts and no scan budget;
* a realistic ACBAR: 2 full listing pages + 1 empty end page and a truthful
  "24 jobs found" banner.

Asserted invariants:
1. The scan is not capped: END_REACHED, SCANNED (not PARTIAL), all 24
   listings seen, source-reported total matches, no "Configured limits"
   line in the output.
2. The recommended COUNT in the summary equals the number of printed
   recommendation entries equals the length of the collection persisted
   with scan activity — one authoritative collection everywhere.
3. Broad discovery retains generic roles for review, but Project Manager /
   CLIC Operator are absent from recommendations while genuine health-domain
   roles (incl. "Nutrition Trainer") are present.
"""

import asyncio
import re
from datetime import date

import pytest
import yaml

import main
from utils import discovery, tracker

PROFILE_YAML = """
personal:
  first_name: Jane
  last_name: Doe
  email: sample.owner@example.org
  gender: male
  nationality: Afghan
  verification:
    first_name: true
    last_name: true
    email: true
    gender: true
    nationality: true
medical_education:
  - degree: MD (Doctor of Medicine)
    institution: Kabul University of Medical Sciences
    graduation_year: "2016"
    verified: true
license_registration:
  authority: Afghan Medical Council
  status: Valid medical professional registration/license
  verified: true
medical_exit_exam:
  status: Completed
  verified: true
clinical_experience:
  years: 6
  verified: true
ngo_humanitarian_experience:
  years: 5
  verified: true
work_history:
  - title: TFU Medical Doctor
    organization: ACF
    start: "2021-01"
    end: "2023-06"
    verified: true
    bullets: [IMAM, CMAM, HMIS, supervision, reporting]
languages:
  - {name: Dari, level: Native, verified: true}
  - {name: English, level: Professional, verified: true}
preferences:
  locations:
    - name: Afghanistan
      verified: true
  field_deployment:
    value: true
    verified: true
sources:
  enabled: [acbar]
job_sources:
  acbar:
    timeout_seconds: 25.0
    max_detail_concurrency: 5
  reliefweb:
    timeout_seconds: 25.0
    limit: 20
"""

TITLES = [
    "Medical Doctor (MD)", "Nutrition Trainer", "Clinical Mentor", "Health and Nutrition Officer",
    "Project Manager", "CLIC Operator", "Finance Manager", "Nurse",
    "HMIS Officer", "Public Health Coordinator", "Driver", "Medical Officer",
]


def _page_html(page: int) -> str:
    cards = []
    for i in range(12):
        number = (page - 1) * 12 + i + 1
        cards.append(
            f"<div><a href='/en/jobs/details/{1000 + number}/job-{number}'>{TITLES[i]} {number}</a>"
            f"<span>Example NGO {number}</span><span>Kabul</span><span>Close date: 2026-12-31</span></div>"
        )
    return "<html><body><p>24 jobs found</p>" + "\n".join(cards) + "</body></html>"


MEDICAL_DETAIL = """
<html><body>
<h1 class="job-title">TITLE</h1>
<p>Organization: Example NGO</p>
<p>Job Location: Kabul</p>
<p>Job Requirements Graduated from a registered and recognized medical faculty, passed the exit exam.
Two years of relevant work experience in health facilities. HMIS reporting,
IMAM, CMAM and therapeutic feeding protocols. Fluency in English language.</p>
<p>Submission Guideline: send your CV to hr@example.org before 2026-12-31.</p>
</body></html>
"""

PM_DETAIL = """
<html><body>
<h1 class="job-title">TITLE</h1>
<p>Organization: Example NGO</p>
<p>Job Location: Kabul</p>
<p>Manage the health and nutrition project budget, donor reporting, procurement and logistics.
Bachelor degree in management; two years of project management experience,
working closely with the medical doctor and the clinical team. Good English writing skills.</p>
<p>Submission Guideline: send your CV to hr@example.org before 2026-12-31.</p>
</body></html>
"""

CLIC_DETAIL = """
<html><body>
<h1 class="job-title">TITLE</h1>
<p>Organization: Example NGO</p>
<p>Job Location: Kabul</p>
<p>Operate the ACBAR CLIC job board payment system, register employers and job seekers,
data entry, receipt processing and reporting. Bachelor degree preferred. Apply hr@example.org before 2026-12-31.</p>
</body></html>
"""


def _detail_html(title: str) -> str:
    template = PM_DETAIL if "Project Manager" in title else CLIC_DETAIL if "CLIC Operator" in title else MEDICAL_DETAIL
    return template.replace("TITLE", title)


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _fake_acbar():
    class Client:
        pages_requested: list[str] = []
        details_requested: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            if "/details/" in url:
                self.details_requested.append(url)
                number = int(url.rsplit("/job-", 1)[-1])
                return _Resp(_detail_html(f"{TITLES[(number - 1) % 12]} {number}"))
            self.pages_requested.append(url)
            if "page=2" in url:
                return _Resp(_page_html(2))
            if "page=3" in url:
                return _Resp("<html><body><p>24 jobs found</p></body></html>")
            return _Resp(_page_html(1))

    return Client


def _recommended_count(output: str) -> int:
    match = re.search(r"^Recommended from this scan: (\d+)$", output, flags=re.MULTILINE)
    assert match, output
    return int(match.group(1))


def _printed_titles(output: str) -> list[str]:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "Recommended vacancies:")
    titles = []
    for line in lines[start + 1:]:
        if not line.strip():
            break
        match = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
        if match:
            titles.append(match.group(2))
    return titles


def test_full_cli_scan_is_uncapped_and_counts_agree(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    client = _fake_acbar()
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: client())
    # Unit-level orchestration receives an explicit fixture mapping. Runtime
    # commands themselves resolve only the canonical profile repository.
    profile = yaml.safe_load(PROFILE_YAML)
    capsys.readouterr()

    asyncio.run(main.cmd_scan(profile))
    output = capsys.readouterr().out

    # 1. No cap anywhere in the output contract.
    assert "Configured limits" not in output
    assert "Pagination: END_REACHED" in output
    assert "Status: SCANNED" in output
    assert "Listings seen: 24" in output
    assert "Source listings reported: 24" in output
    assert "Not processed due to budget: 0" in output

    # 2. One authoritative collection: summary count == printed list == stored.
    count = _recommended_count(output)
    titles = _printed_titles(output)
    assert count > 0, output
    assert len(titles) == count
    stored = tracker.get_latest_scan()
    assert stored["summary"]["recommended_from_scan"] == count
    assert len(stored["recommendations"]) == count
    stored_titles = [f"{entry['title']} — {entry['company']} ({entry['location']})" for entry in stored["recommendations"]]
    assert titles == stored_titles

    # 3. Role gate end to end with the real matcher.
    assert not any("Project Manager" in title or "CLIC Operator" in title for title in titles)
    assert any("Nutrition Trainer" in title for title in titles)
    assert "Note:" in output  # the gated review-only roles are explained


def test_scan_collection_survives_persistence_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "jobs.db")
    client = _fake_acbar()
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: client())
    profile = yaml.safe_load(PROFILE_YAML)
    asyncio.run(main.cmd_scan(profile))

    scan = tracker.get_latest_scan()
    recommendation_ids = [entry["id"] for entry in scan["recommendations"]]
    assert len(recommendation_ids) == scan["summary"]["recommended_from_scan"]
    # Stored-history view (the `recommended` CLI command) applies the same gate.
    via_tracker = tracker.get_recommended_jobs(limit=500)
    assert not any("Project Manager" in job["title"] for job in via_tracker)


@pytest.mark.asyncio
async def test_real_end_without_any_acbar_budget(monkeypatch):
    monkeypatch.setattr(discovery.httpx, "AsyncClient", lambda **kwargs: _fake_acbar()())
    jobs = await discovery.discover_acbar_jobs({}, today=date(2026, 10, 1))
    assert jobs.metrics.pagination_stop_reason == "END_REACHED"
    assert jobs.metrics.status == "SCANNED"
    assert jobs.metrics.not_processed_due_to_budget == 0
    assert jobs.metrics.listings_seen == 24

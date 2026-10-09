"""ReliefWeb employer and country extraction must stop at the next field label.

Real ReliefWeb cards put the employer, the country and the closing date on one
run of text ("Organization: WHO Closing date: 2026-10-15"). Before the fix the
employer swallowed the closing date, so "WHO Closing date: 2026-10-15" became
the employer name shown to the owner and written into the stable job id.
"""

from __future__ import annotations

import pytest

from utils import discovery

LISTING_URL = "https://reliefweb.int/jobs?country=Afghanistan"


def _listing(html: str):
    return discovery._parse_reliefweb_listing(html, LISTING_URL, limit=20)


@pytest.mark.parametrize(
    ("card_text", "expected"),
    [
        ("Health Programme Officer Afghanistan Organization: WHO Closing date: 2026-10-15", "WHO"),
        ("Finance Manager Afghanistan Source: Example NGO Closing date: 2026-10-20", "Example NGO"),
        ("Medical Adviser Afghanistan Organization: Médecins Sans Frontières Closing date: 2026-11-01", "Médecins Sans Frontières"),
        ("Nutrition Officer Afghanistan Organization: Save the Children Deadline: 2026-11-01 Country: Afghanistan", "Save the Children"),
        ("Protection Officer Afghanistan Organization: International Rescue Committee | Closing date: 2026-10-30", "International Rescue Committee"),
        ("Logistics Officer Afghanistan Organization: UNICEF Afghanistan Closing date 2026-10-30", "UNICEF Afghanistan"),
    ],
)
def test_employer_stops_before_the_next_field(card_text, expected):
    assert discovery._guess_reliefweb_company(card_text) == expected


@pytest.mark.parametrize(
    "card_text",
    [
        "Health Programme Officer Afghanistan Organization: Closing date: 2026-10-15",
        "Health Programme Officer Afghanistan Source: Closing date 2026-10-15",
        "Health Programme Officer Afghanistan Organization: 2026-10-15",
        "Health Programme Officer Afghanistan Organization: Deadline 2026-10-15",
        "Health Programme Officer Afghanistan Organization: Afghanistan Closing date: 2026-10-15",
    ],
)
def test_a_label_with_no_employer_name_yields_no_employer(card_text):
    company = discovery._guess_reliefweb_company(card_text)
    assert company == ""
    for word in ("closing", "deadline", "2026"):
        assert word not in company.lower()


def test_listing_card_employers_are_clean_for_the_real_fixture_markup():
    html = (
        '<article><h3><a href="/job/420001/health-programme-officer">Health Programme Officer</a></h3>'
        "<p>Afghanistan</p><p>Organization: WHO</p><p>Closing date: 2026-10-15</p></article>"
        '<article><a href="/job/420002/finance-manager">Finance Manager</a>'
        "<p>Afghanistan</p><p>Source: Example NGO</p><p>Closing date: 2026-10-20</p></article>"
    )
    by_title = {job.title: job for job in _listing(html)}
    assert by_title["Health Programme Officer"].company == "WHO"
    assert by_title["Finance Manager"].company == "Example NGO"
    for job in by_title.values():
        assert "closing" not in job.company.lower()
        assert not any(ch.isdigit() for ch in job.company)


def test_employer_from_the_listing_never_contains_a_date_or_field_label():
    html = (
        '<article><a href="/job/420010/officer">Protection Officer</a>'
        "<p>Afghanistan</p><p>Organization: Norwegian Refugee Council Closing date: 2026-10-30 "
        "Country: Afghanistan</p></article>"
    )
    (job,) = _listing(html)
    assert job.company == "Norwegian Refugee Council"
    assert job.location == "Afghanistan"


def test_detail_page_with_labels_on_one_line_keeps_employer_and_country_clean():
    listing_card = (
        '<article><a href="/job/420001/health-programme-officer">Health Programme Officer</a>'
        "<p>Afghanistan</p></article>"
    )
    (summary,) = _listing(listing_card)
    detail_html = (
        "<html><body><h1>Health Programme Officer</h1>"
        "<p>Organization: World Health Organization Country: Afghanistan Closing date: 2026-10-15</p>"
        "<p>How to apply: https://careers.who.int/apply/420001</p></body></html>"
    )
    job = discovery._parse_reliefweb_detail(detail_html, summary)
    assert job.company == "World Health Organization"
    assert job.location == "Afghanistan"
    assert job.metadata["closing_date"] == "2026-10-15"
    assert "closing" not in job.company.lower()
    assert "closing" not in job.location.lower()


def test_detail_page_with_separate_lines_is_unchanged():
    (summary,) = _listing(
        '<article><a href="/job/420001/health-programme-officer">Health Programme Officer</a>'
        "<p>Afghanistan</p></article>"
    )
    detail_html = (
        "<html><body><h1>Health Programme Officer</h1>"
        "<p>Organization: World Health Organization</p>"
        "<p>Country: Afghanistan</p>"
        "<p>Closing date: 2026-10-15</p></body></html>"
    )
    job = discovery._parse_reliefweb_detail(detail_html, summary)
    assert job.company == "World Health Organization"
    assert job.location == "Afghanistan"
    # The country is recorded as provenance too: "Afghanistan" is a valid country,
    # so the employer placeholder rule must never drop it.
    assert job.metadata["location"] == "Afghanistan"

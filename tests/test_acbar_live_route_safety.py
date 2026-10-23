"""Regression checks for live-site-shaped ACBAR route ambiguity.

The ACBAR website displays a general contact email in its global footer.
The vacancy-level submission guideline is the only source for the employer's
official application route; a site navigation /jobs link is not an apply URL.
"""

from __future__ import annotations

from utils.discovery import Job, _parse_acbar_detail


def _listing(job_id="146432"):
    return Job(
        job_id,
        "TSFP Supervisor",
        "Example Humanitarian Health NGO",
        "Parwan",
        f"https://www.acbar.org/en/jobs/details/{job_id}/tsfp-supervisor",
        None,
        "acbar",
        "Listing text",
        metadata={},
        application_method="UNAVAILABLE",
    )


FOOTER = """
  <h2>ACBAR Highlights</h2><a href="/en/jobs">Jobs</a>
  <h2>Contact Us</h2><p>webinfo@acbar.org</p>
  <h2>Useful Links</h2><a href="/en/jobs">Jobs</a>
"""


def test_official_google_form_is_used_instead_of_public_site_footer_email():
    html = """
    <h1>TSFP Supervisor</h1>
    <h2>Job Requirements</h2><p>MD required, two years nutrition experience.</p>
    <h2>Submission Guideline</h2>
    <p>Kindly note that this is the ONLY way to apply. Submit a PDF CV via the link.</p>
    <p>Email / Application Form: https://forms.gle/rtGFFigaecLcnW8MA</p>
    """ + FOOTER
    job = _parse_acbar_detail(html, _listing())
    assert job.application_method == "WEB"
    assert job.apply_url == "https://forms.gle/rtGFFigaecLcnW8MA"
    assert not job.apply_email
    assert job.metadata.get("apply_email") is None


def test_nav_jobs_link_does_not_become_application_form():
    html = """
    <nav><a href="/en/jobs">Find Jobs</a></nav>
    <h1>Medical Doctor</h1>
    <h2>Submission Guideline</h2>
    <p>Please contact our organization for details.</p>
    """ + FOOTER
    job = _parse_acbar_detail(html, _listing("146433"))
    assert job.application_method == "UNAVAILABLE"
    assert job.apply_url is None
    assert not job.apply_email


def test_employer_email_inside_submission_guideline_is_accepted():
    html = """
    <h1>Medical Doctor</h1><h2>Submission Guideline</h2>
    <p>Send your application to recruitment@example.org</p>
    """ + FOOTER
    job = _parse_acbar_detail(html, _listing("146434"))
    assert job.application_method == "EMAIL"
    assert job.apply_email == "recruitment@example.org"
    assert job.apply_url is None


def test_explicit_linked_external_form_is_respected_without_visible_url():
    html = """
    <h1>Medical Doctor</h1><h2>Submission Guideline</h2>
    <p>Complete the official form.</p>
    <a href="https://forms.gle/aValidFormLink">Apply online</a>
    """ + FOOTER
    job = _parse_acbar_detail(html, _listing("146435"))
    assert job.application_method == "WEB"
    assert job.apply_url == "https://forms.gle/aValidFormLink"


def test_form_precedence_over_unrelated_email_in_application_area():
    html = """
    <h1>Medical Doctor</h1><h2>Submission Guideline</h2>
    <p>Questions: information@example.org. Submit ONLY using
    https://forms.gle/aValidFormLink</p>
    """ + FOOTER
    job = _parse_acbar_detail(html, _listing("146436"))
    assert job.application_method == "WEB"
    assert job.apply_url == "https://forms.gle/aValidFormLink"

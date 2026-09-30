

def test_parse_web_search_results_acbar_fields_stop_at_next_label_same_line():
    from utils.mcp_source import parse_web_search_results

    jobs = parse_web_search_results([
        {
            "title": "ACBAR: Pediatrics Specialist",
            "url": "https://www.acbar.org/en/jobs/details/145823/pediatrics-specialist-re-announced",
            "description": "Organization: Medical Management and Research Courses Afghanistan (MMRCA). Job Location: Sar-e Pol. Category: Health Care. Deadline: 2026-10-03. Job Requirements: MD with Specialty Degree (Pediatrics).",
        }
    ], platform_hint="test")

    assert jobs[0]["company"] == "Medical Management and Research Courses Afghanistan (MMRCA)"
    assert jobs[0]["location"] == "Sar-e Pol"

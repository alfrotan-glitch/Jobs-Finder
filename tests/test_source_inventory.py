from utils.source_inventory import inventory_as_dicts


def test_source_inventory_is_machine_readable_and_explicit_about_statuses():
    inventory = inventory_as_dicts()
    assert inventory
    required = {
        "source_name",
        "source_type",
        "url_or_domain",
        "country_market_relevance",
        "health_medical_relevance",
        "discovery_method",
        "implementation_status",
        "login_required",
        "captcha_blocks_access",
        "public_job_content_accessible",
        "application_url_can_be_extracted",
        "reliability_provenance_level",
        "last_successful_discovery_test",
        "notes_limitations",
    }
    assert all(required <= set(record) for record in inventory)
    names = {record["source_name"] for record in inventory}
    lower_names = {name.lower() for name in names}
    assert "ACBAR" in names
    assert "UNICEF Careers" in names
    assert "UNJobs Afghanistan" in names
    assert "linkedin public jobs" in lower_names
    assert any(record["implementation_status"].startswith("not_") for record in inventory)

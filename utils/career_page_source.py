"""
Custom / official career page discovery.

This wrapper preserves the old public function name while using the new
deterministic Afghanistan medical career-page scanner. It does not require AI.
"""

import re


async def discover_career_page_jobs(profile: dict) -> list:
    from utils.afghan_sources import discover_official_career_pages

    return await discover_official_career_pages(profile)


def _extract_domain(url: str) -> str:
    """Extract company name from URL domain."""
    match = re.search(r"://(?:www\.)?([^/]+)", url)
    if match:
        domain = match.group(1)
        for suffix in [".com", ".io", ".co", ".org", ".net", ".int"]:
            domain = domain.replace(suffix, "")
        return domain
    return "Unknown"

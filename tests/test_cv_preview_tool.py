"""The preserved PR25 preview utility uses the real, read-only product flow."""
from pathlib import Path

import pdfplumber
import pytest

from tools import render_previews
from utils.document_design import _cv_education_lines
from utils.profile import canonical_profile_path


def test_preview_generation_validation_and_every_page_rasterization(tmp_path):
    before = canonical_profile_path().read_bytes()
    cases = render_previews.generate_cases(tmp_path, all_families=False)
    case = cases["master"]
    pdf = Path(case["paths"]["pdf"])
    metrics = render_previews.inspect_pdf(pdf, case["model"])
    paths = render_previews.render_pdf(pdf, tmp_path / "images", dpi=72)
    with pdfplumber.open(pdf) as document:
        assert len(paths) == len(metrics["pages"]) == len(document.pages) == 2
    assert all(path.read_bytes().startswith(b"\x89PNG") for path in paths)
    assert canonical_profile_path().read_bytes() == before
    assert (tmp_path / "review-warnings.json").is_file()


def test_word_extraction_normalization_preserves_hyphens_and_all_source_words():
    assert render_previews.normalized("BPHS/EPHS-\nrelated services") == "BPHS/EPHS-related services"
    assert render_previews.normalized("2013–\n2020") == "2013–2020"
    assert render_previews.normalized("health\nnutrition") == "health nutrition"
    assert render_previews.normalized("Doctor — Curative Medicine") == "Doctor Curative Medicine"


@pytest.mark.parametrize("value", [
    "Doctor of Medicine", "Doctor of Medicine — University",
    "Doctor of Medicine — Curative Medicine — University",
    "Doctor of Medicine — Curative Medicine — University — 2013–2020",
])
def test_education_hierarchy_preserves_every_source_component(value):
    lines = _cv_education_lines(value)
    assert " — ".join(lines) == value
    assert all(lines)

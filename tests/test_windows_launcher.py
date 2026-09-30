from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_jobs_finder.bat"


def _launcher_text() -> str:
    assert LAUNCHER.exists(), "Windows one-click launcher is missing"
    return LAUNCHER.read_text(encoding="utf-8")


def test_windows_launcher_uses_existing_project_and_venv():
    text = _launcher_text()
    lowered = text.lower()

    assert "%~dp0" in text
    assert 'pushd "%PROJECT_DIR%"' in text
    assert ".venv\\Scripts\\python.exe" in text
    assert "main.py" in text
    assert " server " in lowered
    assert "--port" in text
    assert "requirements.txt" in text


def test_windows_launcher_does_not_create_parallel_runtime_or_run_watcher():
    lowered = _launcher_text().lower()

    forbidden_fragments = [
        "python -m venv",
        "py -m venv",
        "pip install -r requirements.txt &&",
        "main.py watch",
        "main.py discover",
        "run_job_watch_scan",
        "apply-batch",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in lowered

    assert "will not create a second environment" in lowered
    assert "not launched by this launcher" in lowered


def test_windows_launcher_supports_double_click_paths_and_browser_open():
    text = _launcher_text()
    lowered = text.lower()

    assert '"%PROJECT_DIR%"' in text
    assert '"%VENV_PYTHON%" "%MAIN_PY%" server' in text
    assert "dashboard_url=http://localhost:%port%" in lowered
    assert "start-process '%dashboard_url%'" in lowered
    assert "pause" in lowered


def test_windows_launcher_has_clear_failure_paths():
    lowered = _launcher_text().lower()

    assert "startup status: failed" in lowered
    assert "virtual environment was not found" in lowered
    assert "required dashboard dependencies are missing" in lowered
    assert "port %port% is already in use" in lowered
    assert "will not start a duplicate dashboard server" in lowered

from pathlib import Path

from lib.remotion_runtime import probe_remotion_runtime


def test_existing_chromium_is_preferred_without_download(tmp_path: Path):
    browser = tmp_path / "chromium"
    browser.write_bytes(b"#!/bin/sh\n")
    browser.chmod(0o755)
    result = probe_remotion_runtime(explicit_chromium=str(browser), chromium_paths=["/does/not/exist"])
    assert result["chromium_executable"] == str(browser)
    assert all("download" not in warning.lower() for warning in result["warnings"])


def test_missing_chromium_reports_warning_only(tmp_path: Path):
    result = probe_remotion_runtime(chromium_paths=[tmp_path / "missing"])
    assert "chromium_executable" in result
    assert isinstance(result["warnings"], list)

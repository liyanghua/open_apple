import hashlib
import json
import shutil
import subprocess

import pytest

from lib.media_fingerprint import compare_media, fingerprint_media
from tools.video.production_audit import ProductionAudit


def test_audit_collect_is_read_only_and_missing_checks_stay_missing(tmp_path):
    (tmp_path / "film.mp4").write_bytes(b"historical")
    record = {"content_slot_id": "A01", "render": {"path": "film.mp4", "sha256": hashlib.sha256(b"historical").hexdigest()}}
    (tmp_path / "record.json").write_text(json.dumps(record))
    result = ProductionAudit().execute({"operation": "collect", "project_dir": str(tmp_path), "record_path": "record.json"})
    assert result.success
    assert not result.data["quality_report"]["certification_eligible"]
    assert next(c for c in result.data["quality_report"]["checks"] if c["id"] == "narration_content")["status"] == "not_run"
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires ffmpeg")
def test_fingerprint_uses_decoded_media_and_comparison_stays_advisory(tmp_path):
    movie = tmp_path / "test.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=10", "-t", "2", str(movie)], check=True)
    a = fingerprint_media(movie)
    same = tmp_path / "renamed.mp4"
    shutil.copyfile(movie, same)
    result = compare_media(a, fingerprint_media(same))
    assert result["exact_same_media"]
    assert result["first_three_seconds_repeated"]
    assert result["human_review_required"]

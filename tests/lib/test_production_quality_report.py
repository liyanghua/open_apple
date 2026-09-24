import hashlib
import json

from lib.production_quality import collect_production_quality


def test_legacy_qa_import_keeps_missing_voice_font_and_identity_unknown(tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"film")
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    qa = {"status": "pass", "output_path": str(video), "checks": {
        "media_integrity": {"decode_ok": True, "profile_ok": True},
        "technical_probe": {"duration_seconds": 8, "has_audio": True}}}
    (tmp_path / "qa.json").write_text(json.dumps(qa))
    record = {"provenance": "legacy_import", "render": {"path": "final.mp4", "sha256": sha, "seconds": 8}, "canonical_artifacts": {}}
    report = collect_production_quality(tmp_path, record, {"technical": "qa.json"})
    checks = {c["id"]: c for c in report["checks"]}
    assert checks["decode"]["status"] == "not_run"
    assert checks["decode"]["issues"] == ["historical_report_not_bound_to_current_media"]
    assert checks["font_identity"]["status"] == "not_run"
    assert checks["narration_content"]["status"] == "not_run"
    assert checks["product_identity"]["status"] == "not_run"
    assert not report["certification_eligible"]


def test_new_qa_requires_bound_media_hash_and_does_not_inherit_legacy_pass(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"video")
    sha = hashlib.sha256(b"video").hexdigest()
    (tmp_path / "qa.json").write_text(json.dumps({"status": "pass", "checks": {"media_integrity": {"decode_ok": True}}}))
    record = {"render": {"path": "video.mp4", "sha256": sha}, "canonical_artifacts": {}}
    checks = {c["id"]: c for c in collect_production_quality(tmp_path, record, {"technical": "qa.json"})["checks"]}
    assert checks["file_integrity"]["status"] == "pass"
    assert checks["decode"]["status"] == "not_run"


def test_legacy_matching_path_never_overrides_mismatching_media_hash(tmp_path):
    (tmp_path / "final.mp4").write_bytes(b"replacement film")
    sha = hashlib.sha256(b"replacement film").hexdigest()
    (tmp_path / "qa.json").write_text(json.dumps({"output_path": "final.mp4",
        "metadata": {"media_sha256": "a" * 64}, "checks": {
            "media_integrity": {"decode_ok": True, "profile_ok": True},
            "technical_probe": {"duration_seconds": 8, "has_audio": True}}}))
    record = {"provenance": "legacy_import", "render": {"path": "final.mp4", "sha256": sha, "seconds": 8}}
    report = collect_production_quality(tmp_path, record, {"technical": "qa.json"})
    checks = {c["id"]: c for c in report["checks"]}
    assert all(checks[name]["status"] == "not_run" for name in ("decode", "video_profile", "duration", "audio_track"))
    assert not report["certification_eligible"]

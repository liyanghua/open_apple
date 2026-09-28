"""Local immutable-media evidence tests; no provider invocation."""
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

PROJECT = Path("/Users/yichen/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1")
CONTRACT = PROJECT / "analysis/masked-temporal-caption-v2/prepared/repair_contract.json"
CANDIDATE = PROJECT / "analysis/masked-temporal-caption-v2/provider/candidate.mp4"


def module():
    try:
        return importlib.import_module("tools.video.caption_structure_review")
    except ModuleNotFoundError:
        pytest.fail("local structure review tool is not implemented")


def test_registry_discovers_local_diagnostic_without_network_dependencies():
    from tools.tool_registry import ToolRegistry
    registry = ToolRegistry()
    registry.register_module(module())
    tool = registry.get("caption_structure_review")
    assert tool is not None and tool.version == "0.1.0"
    assert tool.provider == "local" and tool.capability == "video_post"
    assert not tool.resource_profile.network_required
    assert not any(x.startswith("env:") for x in tool.dependencies)
    assert tool.estimate_cost({}) == 0


@pytest.mark.parametrize("flag", [None, False, 1, "true"])
def test_requires_literal_diagnostic_flag_before_output(tmp_path, flag):
    output = tmp_path / "review"
    result = module().CaptionStructureReview().execute({"diagnostic_only": flag, "output_dir": str(output)})
    assert not result.success and "diagnostic_only" in result.error
    assert not output.exists()


@pytest.mark.parametrize("case", ["missing", "hash", "legacy", "existing"])
def test_rejects_unapproved_requests_before_output(tmp_path, case):
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"version": 1 if case == "legacy" else 2, "input_preprocessing": "vace_gray127"}))
    candidate = tmp_path / "candidate.mp4"
    if case != "missing": candidate.write_bytes(b"not the exact approved candidate")
    output = tmp_path / "review"
    if case == "existing":
        output.mkdir()
        (output / "sentinel").write_text("keep")
    result = module().CaptionStructureReview().execute(dict(contract_path=str(contract),
        candidate_path=str(candidate), output_dir=str(output), diagnostic_only=True))
    assert not result.success
    expected = {"missing": "regular file", "hash": "hash", "legacy": "version 2", "existing": "exists"}[case]
    assert expected in result.error
    if case == "existing": assert list(output.iterdir()) == [output / "sentinel"]
    else: assert not output.exists()


def test_bad_candidate_geometry_rejected_before_output(tmp_path, monkeypatch):
    from lib.masked_caption_media import encode_rgb
    review = module()
    contract = tmp_path / "contract.json"
    contract.write_text('{"version":2,"input_preprocessing":"vace_gray127"}')
    candidate = tmp_path / "wrong-geometry.mp4"
    encode_rgb(candidate, [np.zeros((16, 16, 3), np.uint8)], 16, 16, 30, codec="h264rgb")
    # Isolate the geometry gate after exact-hash gate; real FFprobe still runs.
    monkeypatch.setattr(review, "_source_hash", lambda _: review.CANDIDATE_SHA256)
    output = tmp_path / "review"
    result = review.CaptionStructureReview().execute(dict(contract_path=str(contract),
        candidate_path=str(candidate), output_dir=str(output), diagnostic_only=True))
    assert not result.success and "geometry" in result.error
    assert not output.exists()


def test_real_immutable_pilot_outputs_unapproved_overlay_evidence(tmp_path):
    if not CONTRACT.is_file() or not CANDIDATE.is_file():
        pytest.skip("immutable approved pilot fixture is not installed")
    review = module()
    contract = json.loads(CONTRACT.read_text())
    originals = [CONTRACT, CANDIDATE, Path(contract["source"]["path"]), Path(contract["mask"]["path"])]
    before = [review._source_hash(p) for p in originals]
    result = review.CaptionStructureReview().execute(dict(contract_path=str(CONTRACT),
        candidate_path=str(CANDIDATE), output_dir=str(tmp_path / "evidence"), diagnostic_only=True))
    assert result.success, result.error
    report = json.loads(Path(result.data["report_path"]).read_text())
    assert report["proposal_only"] is True
    assert report["approved_for_restore"] is False and report["accepted_for_production"] is False
    assert report["overlay_only"] is True and report["evidence_frames"] == 38
    assert report["acceptance"] == {"text": "unknown", "temporal": "unknown", "geometry": "unknown"}
    assert len(report["frame_strips"]) == 38 and len(report["contact_sheets"]) == 8
    video_info = json.loads(review._capture(["ffprobe", "-v", "error", "-show_entries",
        "stream=pix_fmt,codec_name", "-of", "json", report["overlay_diagnostic_video"]], limit=4096, timeout=30))
    assert video_info["streams"][0] == {"codec_name": "h264", "pix_fmt": "yuv420p"}
    for ref in report["outputs"]:
        assert Path(ref["path"]).is_file()
        assert review._source_hash(Path(ref["path"])) == ref["sha256"]
    with np.load(report["label_proposals"], allow_pickle=False) as proposals:
        labels, mask = proposals["labels"], proposals["allowed_mask"]
        assert labels.shape[0] == 38 and labels.dtype == np.uint8
        assert np.all(labels[:, ~mask] == 0)
        assert np.all((labels[:, mask] >= 1) & (labels[:, mask] <= 3))
    assert [review._source_hash(p) for p in originals] == before
    assert not any("master" in p.name or "repaired" in p.name for p in (tmp_path / "evidence").iterdir())

from __future__ import annotations

from pathlib import Path

from lib.template_render import build_edit_decisions, build_final_props
from lib.media_profiles import get_profile
from lib.template_assets import build_production_lock
from lib.artifact_hashing import attach_hashes
from schemas.artifacts import validate_artifact


def test_template_render_supports_canonical_taobao_3_4_profile(tmp_path: Path) -> None:
    props = build_final_props(
        tmp_path,
        {"sections": []},
        [{"id": "shot-01", "duration_seconds": 2.0, "screen_copy": "吸水", "scene_id": "scene-001"}],
        profile="social_vertical_3_4_1080p30",
    )
    assert (props["width"], props["height"]) == (1080, 1440)

    edit = build_edit_decisions(
        tmp_path,
        [{"id": "shot-01", "duration_seconds": 2.0, "scene_id": "scene-001"}],
        safe_zone_profile="taobao_detail_3_4",
    )
    assert edit["safe_zone_profile"] == "taobao_detail_3_4"
    validate_artifact("edit_decisions", attach_hashes(edit))
    assert (get_profile("social_vertical_3_4_sample_540p30").width,
            get_profile("social_vertical_3_4_sample_540p30").height) == (540, 720)
    assert (get_profile("social_vertical_3_4_2160p30").width,
            get_profile("social_vertical_3_4_2160p30").height) == (2160, 2880)
    lock = build_production_lock(
        tmp_path, {"template_id": "towel"}, {}, {},
        output_profile="social_vertical_3_4_2160p30",
    )
    assert lock["locked_values"]["output"]["resolution"] == "2160x2880"

from __future__ import annotations

from pathlib import Path


def test_rebuild_final_props_reuses_audio_and_compacts_selling_point_copy(tmp_path: Path) -> None:
    from lib.template_caption_refresh import build_refreshed_final_props

    existing = {
        "audio": {
            "mix": {
                "narration": {"path": "assets/audio/narration-mix.mp3"},
                "music": {"path": "assets/music/bgm-29s.mp3"},
            }
        }
    }
    props = build_refreshed_final_props(
        tmp_path / "run",
        existing_final_props=existing,
        script={"semantic_sha256": "a" * 64},
        shot_plan={"semantic_sha256": "b" * 64, "shots": [{
            "id": "shot-01",
            "duration_seconds": 2.5,
            "screen_copy": "商品页参数标注吸水性等级5s-10s",
        }]},
        profile="social_vertical_3_4_2160p30",
    )

    assert props["captions"] == [{"startMs": 0, "endMs": 2500, "text": "吸水实测"}]
    assert props["audio"]["mix"]["narration"]["path"] == "assets/audio/narration-mix.mp3"
    assert props["audio"]["mix"]["music"]["path"] == "assets/music/bgm-29s.mp3"
    assert (props["width"], props["height"]) == (2160, 2880)

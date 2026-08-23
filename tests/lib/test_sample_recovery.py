from __future__ import annotations

from lib.sample_recovery import repair_source_windows


def test_repair_source_windows_extends_only_short_metadata_window() -> None:
    repaired, changes = repair_source_windows({
        "fps": 30,
        "scenes": [
            {"id": "shot-01", "fromFrame": 0, "toFrameExclusive": 69,
             "sourceInSeconds": 0, "sourceOutSeconds": 2.2},
            {"id": "shot-02", "fromFrame": 69, "toFrameExclusive": 141,
             "sourceInSeconds": 1.2, "sourceOutSeconds": 3.6},
        ],
    })

    assert changes == [{"scene_id": "shot-01", "source_out_seconds": 2.3}]
    assert repaired["scenes"][0]["sourceOutSeconds"] == 2.3
    assert repaired["scenes"][1]["sourceOutSeconds"] == 3.6

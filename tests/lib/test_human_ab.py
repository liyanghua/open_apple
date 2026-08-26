"""Unit tests for lib.human_ab (人工门 + A/B 对比工具)."""

from __future__ import annotations

import json
from pathlib import Path

from lib.human_ab import (
    HUMAN_AB_DIMS,
    build_human_ab_template,
    print_summary,
    record_human_ab,
    summarize_human_ab,
)


def test_build_template_has_eight_dims():
    t = build_human_ab_template("table-mat-batch-002-c1", "template-run-sheet-01", old_path="a.mp4", new_path="b.mp4")
    assert len(t["dims"]) == 8
    assert t["comparison"]["old_label"] == "table-mat-batch-002-c1"
    assert {d["dim"] for d in t["dims"]} == {
        "creative_direction", "hook", "proof", "pacing", "readability",
        "story_structure", "caption_huazi", "transition_rhythm",
    }


def _filled(new="pass", vs_old="better", overall="new_better"):
    t = build_human_ab_template("old", "new")
    for d in t["dims"]:
        d["new"] = new
        d["vs_old"] = vs_old
    t["overall"] = overall
    return t


def test_record_human_ab_validates_and_writes(tmp_path: Path):
    sealed = record_human_ab(_filled(), tmp_path)
    assert sealed["artifact_sha256"]
    assert (tmp_path / "artifacts" / "human_ab_review.json").is_file()
    # 未填齐 dims 的记录应被拒
    try:
        record_human_ab(build_human_ab_template("old", "new"), tmp_path)
        assert False, "should raise"
    except ValueError:
        pass


def test_summarize_counts_better_and_new():
    reviews = [_filled(vs_old="better", overall="new_better"),
               _filled(vs_old="equal", new="adjust", overall="comparable")]
    s = summarize_human_ab(reviews)
    assert s["total"] == 2
    assert s["overall"] == {"new_better": 1, "comparable": 1, "new_worse": 0}
    hook_row = s["dims"]["hook"]
    assert hook_row["better"] == 1 and hook_row["equal"] == 1
    assert hook_row["pass"] == 1 and hook_row["adjust"] == 1
    assert "更好" in print_summary(reviews)

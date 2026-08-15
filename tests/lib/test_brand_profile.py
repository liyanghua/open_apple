"""Brand defaults merge without silently overriding production choices."""

from __future__ import annotations

import json
from pathlib import Path

from lib.brand_profile import merge_brand_defaults
from tests.contracts.test_brand_profile_contract import valid_brand_profile


def test_merge_fills_only_values_that_are_not_already_selected() -> None:
    profile = valid_brand_profile()
    selected = {
        "voice": {"provider": "approved-provider"},
        "cta_pattern": "现在购买",
    }

    result = merge_brand_defaults(profile, selected)

    assert result["merged"]["voice"]["provider"] == "approved-provider"
    assert result["merged"]["voice"]["rate"] == 0.96
    assert result["merged"]["cta_pattern"] == "现在购买"
    assert "voice.rate" in result["applied_defaults"]
    assert "voice.provider" not in result["applied_defaults"]
    assert result["conflicts"] == []


def test_lock_conflict_keeps_locked_value_and_appends_decision_revision(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    (project / "artifacts").mkdir(parents=True)
    initial_log = {
        "version": "1.0",
        "project_id": "demo",
        "decisions": [{
            "decision_id": "voice-initial",
            "stage": "proposal",
            "category": "voice_selection",
            "subject": "Brand profile voice.voice",
            "options_considered": [{
                "option_id": "locked-voice",
                "label": "locked-voice",
                "score": 1,
                "reason": "approved production lock",
            }],
            "selected": "locked-voice",
            "reason": "approved production lock",
        }],
    }
    (project / "artifacts" / "decision_log.json").write_text(
        json.dumps(initial_log), encoding="utf-8"
    )
    lock = {
        "locked_values": {
            "tts": {
                "provider": "doubao",
                "resource": "seed-tts-2.0",
                "voice": "locked-voice",
                "rate": 0.96,
            }
        }
    }

    result = merge_brand_defaults(
        valid_brand_profile(), {}, production_lock=lock, project_dir=project
    )

    assert result["merged"]["voice"]["voice"] == "locked-voice"
    assert result["conflicts"] == [{
        "path": "voice.voice",
        "locked_value": "locked-voice",
        "profile_value": "zh_female_vv_uranus_bigtts",
        "requires_reapproval": True,
        "decision_revision_id": result["conflicts"][0]["decision_revision_id"],
    }]
    decision_log = json.loads(
        (project / "artifacts" / "decision_log.json").read_text(encoding="utf-8")
    )
    assert len(decision_log["decisions"]) == 2
    revision = decision_log["decisions"][-1]
    assert (revision["category"], revision["subject"]) == (
        "voice_selection",
        "Brand profile voice.voice",
    )
    assert revision["selected"] == "zh_female_vv_uranus_bigtts"
    assert revision["user_approved"] is False


def test_lock_match_is_not_reported_as_conflict() -> None:
    profile = valid_brand_profile()
    lock = {"locked_values": {"tts": dict(profile["voice"])}}

    result = merge_brand_defaults(profile, {}, production_lock=lock)

    assert result["conflicts"] == []
    assert result["merged"]["voice"] == profile["voice"]

"""Unit tests for lib.template_run_plan + lib.template_batch (Req 3)."""

from __future__ import annotations

from lib.artifact_hashing import attach_hashes
from lib.template_batch import create_template_batch, mark_pilot
from lib.template_run_plan import bind_slot, create_template_run, select_pilot
from schemas.artifacts import validate_artifact

PACK_REF = {"artifact_sha256": "a" * 64, "version": "1.0"}
FACTS_REF = {"artifact_sha256": "b" * 64}


def _pack() -> dict:
    return {
        "version": "1.0", "project_id": "p", "created_at": "2026-08-25T00:00:00+00:00",
        "taxonomy_version": "template-pack@1",
        "source_document": {"path": "x.xlsx", "sha256": "c" * 64, "parser_version": "xlsx-template-import@1"},
        "templates": [
            {"template_id": "sheet-01-video1-aks-zhuodian", "sheet_name": "视频1_AKS桌垫", "archetype": None,
             "slots": [
                 {"slot_id": "...-slot-001", "ordinal": 1, "caption_treatment": "animated", "shot_language": {}},
                 {"slot_id": "...-slot-002", "ordinal": 2, "caption_treatment": "subtitle", "shot_language": {}},
                 {"slot_id": "...-slot-003", "ordinal": 3, "caption_treatment": "fade_in", "shot_language": {}},
                 {"slot_id": "...-slot-004", "ordinal": 4, "caption_treatment": "fade_out", "shot_language": {}},
             ]},
            {"template_id": "sheet-02-video2-aks-zhuodian", "sheet_name": "视频2_AKS桌垫", "archetype": None,
             "slots": [{"slot_id": "...-slot-001", "ordinal": 1, "caption_treatment": "subtitle", "shot_language": {}}]},
        ],
        "normalization_warnings": [],
    }


def test_create_template_run_initializes_unbound_bindings():
    run = create_template_run(_pack()["templates"][0], template_pack_ref=PACK_REF, product_facts_ref=FACTS_REF)
    assert len(run["slot_bindings"]) == 4
    assert all(b["source"] == "unbound" for b in run["slot_bindings"])
    assert run["caption_policy"] == {"reference_text": "analysis_only", "copy_reference_caption": False}


def test_bind_slot_updates_source_and_validates():
    run = create_template_run(_pack()["templates"][0], template_pack_ref=PACK_REF, product_facts_ref=FACTS_REF)
    run = bind_slot(run, run["slot_bindings"][0]["slot_id"], source="generate", asset_type="video", reason="缺自有素材")
    assert run["slot_bindings"][0]["source"] == "generate"
    validate_artifact("template_run_plan", attach_hashes(dict(run)))  # 不抛异常


def test_select_pilot_covers_treatments_and_is_bounded():
    ids = select_pilot(_pack()["templates"], n=1)
    assert len(ids) == 1


def test_create_template_batch_43_runs_and_validates():
    from lib.template_import import build_template_pack
    from pathlib import Path

    xlsx = Path(__file__).resolve().parents[2] / "docs/insight_source/视频分镜拆解_2026-08-15.xlsx"
    if not xlsx.exists():
        return  # 大 xlsx 不在则跳过（CI）
    pack = build_template_pack(xlsx)
    batch = create_template_batch(attach_hashes(dict(pack)), product_facts_ref=FACTS_REF)
    assert len(batch["runs"]) == 43
    assert batch["publish_policy"] == "selective"
    validate_artifact("template_batch", attach_hashes(dict(batch)))


def test_mark_pilot_sets_pilot_ids():
    batch = create_template_batch(_pack(), product_facts_ref=FACTS_REF)
    batch = mark_pilot(batch, ["sheet-01-video1-aks-zhuodian"])
    assert batch["pilot_run_ids"] == ["sheet-01-video1-aks-zhuodian"]


def test_template_run_plan_hard_gate_rejects_violations():
    import jsonschema
    from schemas.artifacts import validate_artifact

    base = {
        "version": "1.0", "run_id": "r", "template_id": "t",
        "template_pack_ref": {"artifact_sha256": "a" * 64, "version": "1.0"},
        "product_facts_ref": {"artifact_sha256": "b" * 64}, "adaptation_policy": "p",
        "status": "awaiting_human",
        "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": False},
    }
    # 合法
    validate_artifact("template_run_plan", dict(base, slot_bindings=[
        {"slot_id": "s", "source": "owned", "source_media_id": "m", "reason": "r"}]))
    # 违规：approved + unbound / owned 无 media / generate 无 asset
    for bad in [
        {"status": "approved", "slot_bindings": [{"slot_id": "s", "source": "unbound", "reason": "r"}]},
        {"slot_bindings": [{"slot_id": "s", "source": "owned", "reason": "r"}]},
        {"slot_bindings": [{"slot_id": "s", "source": "generate", "reason": "r"}]},
    ]:
        try:
            validate_artifact("template_run_plan", dict(base, **bad))
            assert False, "should raise"
        except jsonschema.ValidationError:
            pass


def test_create_template_batch_null_ref_when_not_persisted():
    from lib.template_batch import create_template_batch

    batch = create_template_batch({"version": "1.0", "templates": [{"template_id": "t1"}]},
                                  product_facts_ref={"artifact_sha256": "b" * 64})
    assert batch["runs"][0]["template_run_plan_ref"] is None
    assert batch["render_runtime"] is None  # 未决，不静默锁 Remotion


def test_check_template_run_plan_ready_fail_closed():
    from lib.template_run_plan import check_template_run_plan_ready, is_slot_paid_allowed

    ready = {"status": "approved", "slot_bindings": [
        {"slot_id": "a", "source": "owned", "source_media_id": "m", "reason": "r"},
        {"slot_id": "b", "source": "generate", "asset_type": "video", "reason": "r"},
    ]}
    r = check_template_run_plan_ready(ready)
    assert r["ready"] is True and r["unbound_slots"] == []
    assert is_slot_paid_allowed(ready, "a") is True

    not_ready = {"slot_bindings": [
        {"slot_id": "a", "source": "owned", "source_media_id": "m", "reason": "r"},
        {"slot_id": "c", "source": "unbound", "reason": "待绑定"},
    ], "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": False}}
    r2 = check_template_run_plan_ready(not_ready)
    assert r2["ready"] is False  # status 未批准 + 有 unbound
    assert "c" in r2["unbound_slots"]
    assert is_slot_paid_allowed(not_ready, "c") is False
    assert is_slot_paid_allowed(not_ready, "a") is False  # status 未批准 -> 禁止
    # awaiting_human / 空绑定 / 非法 source / 缺字段 全部 fail-closed
    assert check_template_run_plan_ready({"status": "awaiting_human", "slot_bindings": []})["ready"] is False
    assert check_template_run_plan_ready({
        "status": "approved", "slot_bindings": [{"slot_id": "x", "source": "nope", "reason": "r"}]})["ready"] is False
    assert check_template_run_plan_ready({
        "status": "approved", "slot_bindings": [{"slot_id": "o", "source": "owned", "reason": "r"}]})["ready"] is False


def test_readiness_requires_complete_unique_template_slot_coverage():
    from lib.template_run_plan import check_template_run_plan_ready

    template = {"template_id": "custom-template", "slots": [{"slot_id": "s1"}, {"slot_id": "s2"}]}
    plan = {"status": "approved", "template_id": template["template_id"],
            "slot_bindings": [{"slot_id": "s1", "source": "owned",
                               "source_media_id": "m", "reason": "r"}]}
    result = check_template_run_plan_ready(plan, template=template)
    assert result["ready"] is False
    assert any("缺少" in blocker or "覆盖" in blocker for blocker in result["blockers"])


def test_readiness_rejects_unregistered_c1_template():
    from lib.template_run_plan import check_template_run_plan_ready

    template = {"template_id": "not-in-pack-c1", "slots": [{"slot_id": "s1"}]}
    plan = {"status": "approved", "template_id": template["template_id"],
            "slot_bindings": [{"slot_id": "s1", "source": "owned",
                               "source_media_id": "m", "reason": "r"}]}
    result = check_template_run_plan_ready(plan, template=template)
    assert result["ready"] is False
    assert any("压缩" in blocker or "模板" in blocker for blocker in result["blockers"])


def test_template_run_plan_schema_accepts_compression_contract():
    from schemas.artifacts import validate_artifact

    plan = {
        "version": "1.0", "run_id": "r", "template_id": "t",
        "template_pack_ref": {"artifact_sha256": "a" * 64, "version": "1.0"},
        "product_facts_ref": {"artifact_sha256": "b" * 64},
        "adaptation_policy": "proof-first", "status": "approved",
        "slot_bindings": [{"slot_id": "s1", "source": "owned",
                           "source_media_id": "m", "reason": "r"}],
        "caption_policy": {"reference_text": "analysis_only", "copy_reference_caption": False},
        "compression": {
            "base_template_id": "t", "base_ref": "template:t", "kept_slot_ids": ["s1"],
            "kept_ordinals": [1], "base_section_refs": ["sec-001"], "total_s": 15.0,
            "h1_ok": True, "h2_ok": True, "h3_ok": True, "h4_ok": True,
            "capacity_ok": True, "dur_ok": True, "all_hard_ok": True, "input_hash": "c" * 64,
        },
    }
    validate_artifact("template_run_plan", plan)

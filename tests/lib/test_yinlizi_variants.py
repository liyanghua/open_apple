from lib.yinlizi_variants import VARIANT_SPECS, build_variant_definition
from scripts.build_yinlizi_variants import _bind_batch_run_ids


def _base():
    return {
        "template_id": "yinlizi-aligned-A",
        "slots": [
            {"slot_id": f"slot-{i}", "ordinal": i, "duration_s": 1.0}
            for i in range(1, 10)
        ],
    }, {
        "template_id": "yinlizi-aligned-A",
        "status": "approved",
        "slot_bindings": [
            {
                "slot_id": f"slot-{i}",
                "source": "owned" if i < 9 else "generate",
                "source_media_id": f"media-{i}" if i < 9 else None,
                "asset_type": "video_proxy" if i < 9 else "generated_video",
                "evidence_row_ids": [f"evidence-coverage-{i:03d}"],
            }
            for i in range(1, 10)
        ],
    }


def test_four_approved_directions_produce_distinct_slot_orders_and_durations():
    template, run_plan = _base()
    definitions = [build_variant_definition(template, run_plan, spec) for spec in VARIANT_SPECS]

    assert [item["variant_id"] for item in definitions] == [
        "result_first", "texture_first", "daily_seed", "high_density"
    ]
    orders = [tuple(item["row_order"]) for item in definitions]
    assert len(set(orders)) == 4
    assert definitions[0]["template"]["template_id"] != template["template_id"]
    assert sum(slot["duration_s"] for slot in definitions[-1]["template"]["slots"]) == 30.1
    assert definitions[-1]["run_plan"]["status"] == "approved"


def test_variant_preserves_evidence_binding_with_slot_reorder():
    template, run_plan = _base()
    definition = build_variant_definition(template, run_plan, VARIANT_SPECS[2])
    by_slot = {row["slot_id"]: row for row in definition["run_plan"]["slot_bindings"]}
    assert [
        by_slot[slot["slot_id"]]["evidence_row_ids"][0]
        for slot in definition["template"]["slots"]
    ] == [f"evidence-coverage-{i:03d}" for i in VARIANT_SPECS[2]["row_order"]]


def test_variant_run_plan_keeps_strict_schema_surface():
    template, run_plan = _base()
    definition = build_variant_definition(template, run_plan, VARIANT_SPECS[0])

    assert "variant_id" not in definition["run_plan"]
    assert "variant_label" not in definition["run_plan"]
    assert all(
        "variant_position" not in binding
        for binding in definition["run_plan"]["slot_bindings"]
    )


def test_batch_members_are_bound_to_isolated_run_ids():
    batch = {
        "runs": [
            {"template_id": "yinlizi-result_first", "project_id": "template-run-yinlizi-result_first"}
        ],
        "pilot_run_ids": ["yinlizi-result_first"],
    }
    result = _bind_batch_run_ids(batch, "yinlizi-script-variants-20260908")
    assert result["runs"][0]["project_id"] == "yinlizi-script-variants-20260908-result_first"
    assert result["pilot_run_ids"] == ["yinlizi-script-variants-20260908-result_first"]

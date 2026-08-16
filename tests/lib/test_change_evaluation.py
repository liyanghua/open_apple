from __future__ import annotations


def test_change_evaluation_chooses_smallest_safe_render_route() -> None:
    from lib.change_evaluation import evaluate_change_impact

    base_lock = {"locked_values": {"mix": {"gain": 0, "lufs": -14}}}
    gain_lock = {"locked_values": {"mix": {"gain": -2, "lufs": -14}}}
    props = {"scenes": [{"id": "s1"}], "audio": {"track": "a"}}
    assert evaluate_change_impact(base_lock, base_lock, props, props)["render_route"] == "no_render"
    assert evaluate_change_impact(base_lock, gain_lock, props, props)["render_route"] == "mux_only"
    changed_props = {**props, "scenes": [{"id": "s2"}]}
    result = evaluate_change_impact(base_lock, gain_lock, props, changed_props)
    assert result["render_route"] == "full_render"
    assert result["affected_scene_ids"] == ["s2"]


def test_adapter_reopen_signal_is_combined_with_lock_and_props() -> None:
    from lib.change_evaluation import evaluate_change_impact

    result = evaluate_change_impact(
        {}, {}, {}, {},
        adapter_signals={"reopen_creative": True, "reopen_sample": True, "render_route": "full_render"},
    )
    assert result["reopen_creative"] is True
    assert result["reopen_sample"] is True
    assert result["render_route"] == "full_render"


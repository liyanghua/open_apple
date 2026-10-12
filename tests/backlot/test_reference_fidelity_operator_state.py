from backlot.operator_state import project_operator_state, validate_operator_state


def test_sample_editor_projects_strict_fidelity_report():
    board = {
        "project_id": "strict-demo",
        "title": "严格复刻",
        "pipeline": {"pipeline_type": "cinematic-fast"},
        "stages": [],
        "artifacts": {
            "reference_alignment_report": {
                "status": "fail",
                "hard_gate_failures": ["duration_drift"],
                "reference_fidelity": {"score": 0.67},
                "product_truth": {"score": 1.0},
            },
        },
        "media": {"renders": []},
        "cost": {},
        "fastline": {},
    }
    state = project_operator_state(board)
    sample = next(stage for stage in state["stages"] if stage["id"] == "sample")
    assert sample["editor"]["data"]["reference_fidelity"]["hard_gate_failures"] == ["duration_drift"]
    validate_operator_state(state)

"""Planning-only preview imports remain visible without a fabricated baseline."""
from backlot.operator_state import load_operator_state
from lib.opening_preview_import import import_prepared_previews
from tests.contracts.test_opening_preview_import import _packet


def test_imported_planning_previews_load_without_baseline_authority(tmp_path):
    packet = _packet(tmp_path)
    for hook in packet["hooks"].values():
        hook["shots"][0]["source_mapping"]["source_interval_seconds"] = [.25, 3.25]
    import_prepared_previews(tmp_path, packet)

    state = load_operator_state(tmp_path, permissions=("view", "review"))
    cards = next(stage for stage in state["stages"] if stage["id"] == "compose")["editor"]["data"]["production_reviews"]
    assert len(cards) == 2
    for card in cards:
        assert card["opening_group"]["baseline_record_path"] is None
        assert card["opening_group"]["scope"] == "preview"
        assert card["review_kind"] == "opening_preview"
        assert card["final_review"] is None
        assert not card["certification_eligible"]

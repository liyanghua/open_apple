"""A same-named public asset cannot substitute for the rendered source."""
import copy

import pytest

from lib.opening_experiment_evidence import _content, _plan_sources_match
from lib.opening_preview_import import import_prepared_previews
from tests.contracts.test_opening_preview_import import _packet, _put


def test_import_rejects_unrendered_public_shadow_source(tmp_path):
    packet = _packet(tmp_path)
    for hook in packet["hooks"].values():
        hook["shots"][0]["source_mapping"]["source_interval_seconds"] = [.25, 3.25]
    shadow = _put(tmp_path, "public/assets/A01-source.mp4", b"never-rendered-public-copy")
    packet["hooks"]["A01"]["shots"][0]["asset_identity"]["source"] = shadow
    packet["previews"]["A01"]["source_ref"] = shadow
    # The runtime, successful render receipt and all three actual pins stay unchanged.
    with pytest.raises(ValueError, match="Ambiguous opening source"):
        import_prepared_previews(tmp_path, packet)
    assert not (tmp_path / "artifacts/production_review_index.json").exists()
    assert not (tmp_path / "artifacts/opening-import/import_receipt.json").exists()


@pytest.mark.parametrize("location", ["root", "public", "identical_copies"])
def test_opening_source_accepts_unambiguous_rendered_bytes(tmp_path, location):
    packet = _packet(tmp_path)
    props = packet["previews"]["A01"]["canonical_props"]
    plan = copy.deepcopy(packet["hooks"]["A01"])
    plan["shots"][0]["source_mapping"]["source_interval_seconds"] = [.25, 3.25]
    relative = props["footage"]["hook"]
    original = tmp_path / relative
    if location != "root":
        _put(tmp_path, "public/" + relative, original.read_bytes())
    if location == "public":
        original.unlink()
        plan["shots"][0]["asset_identity"]["source"]["path"] = "public/" + relative
    _plan_sources_match(tmp_path, props, plan)
    assert _content(tmp_path, props)["scenes"][0]["sha256"] == plan["shots"][0]["asset_identity"]["source"]["sha256"]


@pytest.mark.parametrize("claimed_source", ["root", "public"])
def test_opening_scope_check_rejects_ambiguous_source_in_either_direction(tmp_path, claimed_source):
    packet = _packet(tmp_path)
    props = packet["previews"]["A01"]["canonical_props"]
    plan = copy.deepcopy(packet["hooks"]["A01"])
    plan["shots"][0]["source_mapping"]["source_interval_seconds"] = [.25, 3.25]
    shadow = _put(tmp_path, "public/assets/A01-source.mp4", b"different-source")
    if claimed_source == "public":
        plan["shots"][0]["asset_identity"]["source"] = shadow
    with pytest.raises(ValueError, match="Ambiguous opening source"):
        _plan_sources_match(tmp_path, props, plan)

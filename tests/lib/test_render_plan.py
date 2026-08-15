from lib.change_impact import classify_change


def _props(audio="a", caption="x"):
    return {"audio": {"mix": audio}, "scenes": [{"id": "n01", "text": caption}], "metadata": {}}


def test_audio_only_change_routes_to_mux():
    result = classify_change({}, {}, _props("a"), _props("b"))
    assert result["route"] == "mux_only"


def test_visual_and_caption_changes_route_to_full_render():
    assert classify_change({}, {}, _props(), _props(caption="changed"))["route"] == "full_render"


def test_metadata_only_change_does_not_render():
    before = _props(); after = _props(); after["notes"] = "review"
    assert classify_change({}, {}, before, after)["route"] == "no_render"

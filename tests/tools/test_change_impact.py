from lib.change_impact import classify_change


def test_change_routes_are_stable_for_audio_captions_and_scenes():
    base = {"audio": {"mix": "a"}, "scenes": [{"id": "n01"}], "captions": [{"text": "a"}]}
    assert classify_change({}, {}, base, {**base, "audio": {"mix": "b"}})["route"] == "mux_only"
    assert classify_change({}, {}, base, {**base, "captions": [{"text": "b"}]})["route"] == "full_render"

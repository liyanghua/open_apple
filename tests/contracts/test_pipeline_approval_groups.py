import pytest

from lib.pipeline_loader import PipelineManifestError, _validate_approval_groups


def _manifest():
    return {"name": "test", "stages": [
        {"name": "script", "produces": ["script"]},
        {"name": "assets", "produces": ["asset_manifest"], "approval_group_terminal": True},
    ], "approval_groups": {"creative": {"members": ["script", "assets"], "terminal_stage": "assets", "required_artifacts": ["script", "asset_manifest"]}}}


def test_valid_group_passes():
    _validate_approval_groups(_manifest())


@pytest.mark.parametrize("mutate", [
    lambda m: m["approval_groups"]["creative"].update(terminal_stage="script"),
    lambda m: m["approval_groups"]["creative"].update(members=["missing", "assets"]),
])
def test_invalid_group_fails(mutate):
    manifest = _manifest(); mutate(manifest)
    with pytest.raises(PipelineManifestError):
        _validate_approval_groups(manifest)

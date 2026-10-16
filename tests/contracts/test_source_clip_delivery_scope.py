"""A source report can never supply the film completion or batch gate."""
import json

import pytest

from lib.checkpoint import CheckpointValidationError, _validate_artifacts_for_stage
from lib.batch_reporting import _scoped_eval
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.contracts.test_shot_source_contract import source_fixture


def test_source_report_cannot_complete_publish(tmp_path):
    _, report, _, _, _ = source_fixture(tmp_path)
    with pytest.raises(CheckpointValidationError, match="source_clip"):
        _validate_artifacts_for_stage("publish", "completed", {
            "evaluation_report": report, "publish_log": sample_artifact("publish_log")
        }, None)


def test_batch_never_falls_back_to_source_as_final(tmp_path):
    _, report, _, _, _ = source_fixture(tmp_path)
    (tmp_path / "artifacts/evaluation_report.json").write_text(json.dumps(report))
    assert _scoped_eval(tmp_path) is None

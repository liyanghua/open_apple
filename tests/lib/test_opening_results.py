"""Synthetic result imports never confer production or winner authority."""
import copy
import hashlib
import json

import pytest

from backlot.operator_errors import OperatorError
from tests.backlot.test_opening_reviews import preview_project


def result_payload(root, record_path="record.json", *, import_id="synthetic-24h"):
    record = json.loads((root / record_path).read_text())
    raw = root / "assets" / "synthetic-metrics.csv"
    raw.parent.mkdir(exist_ok=True)
    raw.write_text("views,opens\n100,45\n")
    digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()
    return {
        "version": "1.0", "import_id": import_id, "result_version": 1,
        "experiment_ref": record["opening"]["experiment_ref"],
        "candidate_id": record["opening"]["candidate_id"],
        "record_ref": {"path": record_path, "sha256": digest(record_path), "version": record["version"]},
        "render_ref": record["render"],
        "platform": "synthetic-platform", "account_id": "synthetic-account",
        "publication_id": "synthetic-post", "ad_id": None,
        "audience": {"description": "synthetic audience", "allocation_id": "synthetic-split", "allocation_method": "manual synthetic fixture"},
        "window": {"start": "2026-09-28T00:00:00+08:00", "end": "2026-09-29T00:00:00+08:00", "timezone": "Asia/Shanghai", "semantics": "cumulative", "label": "24h"},
        "metrics": [{"metric_id": "open_rate", "definition": "opens / views", "kind": "rate", "numerator": 45, "numerator_unit": "open", "denominator": 100, "denominator_unit": "view", "count_unit": "event", "duration_unit": None, "support_count": None}],
        "fee": {"amount": None, "currency": None, "settlement_status": "unknown"},
        "raw_export_ref": {"path": "assets/synthetic-metrics.csv", "sha256": digest("assets/synthetic-metrics.csv")},
        "sample": {"conditions": "synthetic fixture only", "limitations": "no real delivery or randomization"},
    }


def test_import_projects_current_observation_without_a_winner(tmp_path):
    from lib.opening_results import import_result, results_for_record
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    saved = import_result(tmp_path, payload, actor_id="tester")
    assert saved["status"] == "imported"
    rows = results_for_record(tmp_path, "record.json")
    assert len(rows) == 1
    assert rows[0]["binding_status"] == "current"
    assert rows[0]["metrics"][0]["value"] == .45
    assert rows[0]["comparison_status"] == "数据不足"
    assert rows[0]["conclusion"] == "已导入，尚无结论"


def test_replay_conflict_and_stale_binding(tmp_path):
    from lib.opening_results import import_result, results_for_record
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    assert import_result(tmp_path, payload, actor_id="tester")["status"] == "imported"
    assert import_result(tmp_path, payload, actor_id="tester")["status"] == "replayed"
    changed = copy.deepcopy(payload); changed["sample"]["limitations"] = "different"
    with pytest.raises(OperatorError) as exc:
        import_result(tmp_path, changed, actor_id="tester")
    assert exc.value.status_code == 409
    (tmp_path / "final.mp4").write_bytes(b"changed")
    assert results_for_record(tmp_path, "record.json")[0]["binding_status"] == "stale"
    assert import_result(tmp_path, payload, actor_id="tester")["status"] == "replayed"


@pytest.mark.parametrize("field,value", [
    ("numerator", -1), ("numerator", 101), ("denominator", -1),
    ("numerator", float("nan")), ("denominator", float("inf")),
])
def test_invalid_metric_numbers_are_rejected(tmp_path, field, value):
    from lib.opening_results import import_result
    preview_project(tmp_path)
    payload = result_payload(tmp_path); payload["metrics"][0][field] = value
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")


@pytest.mark.parametrize("denominator", [None, 0])
def test_unknown_and_zero_denominator_yield_undefined_rate(tmp_path, denominator):
    from lib.opening_results import import_result, results_for_record
    preview_project(tmp_path)
    payload = result_payload(tmp_path); payload["metrics"][0]["denominator"] = denominator
    if denominator == 0: payload["metrics"][0]["numerator"] = 0
    import_result(tmp_path, payload, actor_id="tester")
    metric = results_for_record(tmp_path, "record.json")[0]["metrics"][0]
    assert metric["value"] is None and metric["status"] == "undefined"


@pytest.mark.parametrize("ref,field", [("raw_export_ref", "path"), ("record_ref", "sha256"), ("experiment_ref", "sha256"), ("render_ref", "sha256")])
def test_missing_or_changed_bound_evidence_is_rejected(tmp_path, ref, field):
    from lib.opening_results import import_result
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    payload[ref][field] = "../outside.csv" if field == "path" else "a" * 64
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")


def test_cumulative_overlap_is_visible_but_not_independent(tmp_path):
    from lib.opening_results import import_result, results_for_record
    preview_project(tmp_path)
    first = result_payload(tmp_path)
    import_result(tmp_path, first, actor_id="tester")
    second = copy.deepcopy(first)
    second["import_id"] = "synthetic-72h"
    second["window"].update(end="2026-10-01T00:00:00+08:00", label="72h")
    import_result(tmp_path, second, actor_id="tester")
    rows = results_for_record(tmp_path, "record.json")
    assert len(rows) == 2
    assert all(row["comparison_status"] == "数据不足" for row in rows)
    assert any("重叠" in reason for row in rows for reason in row["comparison_reasons"])


def test_comparison_explains_group_scope_window_account_allocation_and_definition(tmp_path):
    from lib.opening_results import comparison_reasons, import_result, results_for_record
    preview_project(tmp_path)
    import_result(tmp_path, result_payload(tmp_path), actor_id="tester")
    row = results_for_record(tmp_path, "record.json")[0]
    peer = copy.deepcopy(row)
    assert comparison_reasons(row, peer, group_same=True, scope_same=True, duration_same=True) == []
    peer["platform"] = "other"; peer["account_id"] = "other"
    peer["audience"]["allocation_id"] = "other"
    peer["window"]["semantics"] = "disjoint"
    peer["window"]["end"] = "2026-09-30T00:00:00+08:00"
    peer["metrics"][0]["denominator_unit"] = "impression"
    reasons = comparison_reasons(row, peer, group_same=False, scope_same=False, duration_same=False)
    assert {"不同基线组", "预览与完整成片范围不同", "成片时长不同", "平台不同", "账号不同", "受众或分配条件不同", "窗口语义不同", "观察时长不同", "指标定义或分母单位不同"} <= set(reasons)


def test_experiment_result_artifact_is_registered_and_rejects_missing_denominator_unit(tmp_path):
    from jsonschema import ValidationError
    from schemas.artifacts import ARTIFACT_NAMES, validate_artifact
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    assert "experiment_result" in ARTIFACT_NAMES
    validate_artifact("experiment_result", payload)
    del payload["metrics"][0]["denominator_unit"]
    with pytest.raises(ValidationError):
        validate_artifact("experiment_result", payload)


def test_nonfinite_fee_and_tampered_saved_result_cannot_be_projected(tmp_path):
    from lib.opening_results import import_result, results_for_record
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    payload["fee"] = {"amount": float("nan"), "currency": "CNY", "settlement_status": "estimated"}
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")
    payload = result_payload(tmp_path)
    import_result(tmp_path, payload, actor_id="tester")
    path = tmp_path / "artifacts/opening_results/synthetic-24h.json"
    saved = json.loads(path.read_text())
    saved["metrics"][0]["numerator"] = 99
    path.write_text(json.dumps(saved))
    assert results_for_record(tmp_path, "record.json") == []


@pytest.mark.parametrize("field,value", [
    ("imported_at", "2026-09-29T00:00:00Z"),
    ("source_sha256", "a" * 64),
    ("semantic_sha256", "a" * 64),
])
def test_caller_cannot_supply_persistence_metadata(tmp_path, field, value):
    from lib.opening_results import import_result
    preview_project(tmp_path)
    payload = result_payload(tmp_path); payload[field] = value
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")


def test_render_metadata_must_match_the_current_record(tmp_path):
    from lib.opening_results import import_result
    preview_project(tmp_path)
    payload = result_payload(tmp_path); payload["render_ref"]["seconds"] = 72
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")


def test_normalizing_within_project_traversal_is_rejected(tmp_path):
    from lib.opening_results import import_result
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    payload["raw_export_ref"]["path"] = "assets/../assets/synthetic-metrics.csv"
    with pytest.raises(OperatorError):
        import_result(tmp_path, payload, actor_id="tester")


def test_concurrent_identical_replay_creates_only_one_import_audit(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from lib import opening_results
    preview_project(tmp_path)
    payload = result_payload(tmp_path)
    barrier = Barrier(2)
    counts = local()
    original = opening_results._validate
    def synchronized_validate(root, data):
        result = original(root, data)
        counts.calls = getattr(counts, "calls", 0) + 1
        if counts.calls == 1:
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(opening_results, "_validate", synchronized_validate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(opening_results.import_result, tmp_path, payload, actor_id="tester") for _ in range(2)]
        outcomes = sorted(future.result(timeout=20)["status"] for future in futures)
    assert outcomes == ["imported", "replayed"]
    assert len(list((tmp_path / "artifacts/opening_results").glob("*.json"))) == 1
    manifests = [json.loads(path.read_text()) for path in
        (tmp_path / "operator/generations").glob("*/manifest.json")]
    import_generations = [row for row in manifests if row["action"].get("type") == "import_opening_result"]
    assert len(import_generations) == 1
    assert len(import_generations[0]["write_set"]) == 1
    assert import_generations[0]["result"]["status"] == "imported"
    assert import_generations[0]["audit"]["event_type"] == "opening_result_imported"

"""Immutable, evidence-bound manual observations for opening experiments."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import ValidationError

from backlot.operator_errors import OperatorError
from backlot.project_commit import ProjectCommitStore
from lib.opening_review_scope import opening_review_scope
from lib.production_evidence import file_sha256, project_file, read_object
from schemas.artifacts import validate_artifact

RESULT_DIR = "artifacts/opening_results"


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _bound_file(root: Path, ref: dict) -> Path:
    relative = ref["path"]
    if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative or any(
        part in {"", ".", ".."} for part in relative.split("/")
    ):
        raise ValueError("Unsafe project-relative path")
    path = project_file(root, relative)
    if file_sha256(path) != ref["sha256"]:
        raise ValueError("Bound file hash changed")
    return path


def _window(value: dict) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(value["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(value["end"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Observation window must have ordered offsets")
    try:
        zone = ZoneInfo(value["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown observation timezone") from exc
    if start.utcoffset() != start.astimezone(zone).utcoffset() or end.utcoffset() != end.astimezone(zone).utcoffset():
        raise ValueError("Observation offsets disagree with timezone")
    return start, end


def _validate(root: Path, data: dict) -> dict:
    try:
        validate_artifact("experiment_result", data)
        if not data["publication_id"] and not data["ad_id"]:
            raise ValueError("Publication or advertisement identity required")
        if data["fee"]["amount"] is not None and not data["fee"]["currency"]:
            raise ValueError("Known fee needs currency")
        if data["fee"]["settlement_status"] == "settled" and data["fee"]["amount"] is None:
            raise ValueError("Settled fee needs an amount")
        if data["fee"]["amount"] is not None and not math.isfinite(data["fee"]["amount"]):
            raise ValueError("Fee number must be finite")
        _window(data["window"])
        metric_ids = set()
        for metric in data["metrics"]:
            if metric["metric_id"] in metric_ids:
                raise ValueError("Duplicate metric identity")
            metric_ids.add(metric["metric_id"])
            for key in ("numerator", "denominator"):
                value = metric[key]
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("Metric number must be finite and nonnegative")
            if metric["kind"] in {"rate", "count"}:
                if metric["duration_unit"] is not None or metric["support_count"] is not None:
                    raise ValueError("Count metric cannot use duration fields")
                if any(value is not None and int(value) != value for value in (metric["numerator"], metric["denominator"])):
                    raise ValueError("Counts must be whole numbers")
            if metric["kind"] == "rate" and metric["numerator"] is not None and metric["denominator"] is not None and metric["numerator"] > metric["denominator"]:
                raise ValueError("Rate numerator exceeds denominator")
            if metric["kind"] == "duration" and (metric["duration_unit"] is None or not metric["support_count"]):
                raise ValueError("Watch duration needs unit and support count")
        record_path = _bound_file(root, data["record_ref"])
        record = read_object(root, data["record_ref"]["path"])
        if record.get("version") != data["record_ref"]["version"]:
            raise ValueError("Production record version changed")
        if record.get("opening", {}).get("candidate_id") != data["candidate_id"]:
            raise ValueError("Candidate identity differs from record")
        opening = opening_review_scope(root, record)
        if not opening or opening["experiment_ref"]["path"] != data["experiment_ref"]["path"] or opening["experiment_ref"]["sha256"] != data["experiment_ref"]["sha256"]:
            raise ValueError("Experiment identity differs from record")
        if record.get("render", {}).get("path") != data["render_ref"]["path"] or record["render"]["sha256"] != data["render_ref"]["sha256"]:
            raise ValueError("Render identity differs from record")
        if any(record["render"].get(key) != value for key, value in data["render_ref"].items()):
            raise ValueError("Render metadata differs from record")
        _bound_file(root, data["experiment_ref"])
        _bound_file(root, data["render_ref"])
        _bound_file(root, data["raw_export_ref"])
        index = read_object(root, "artifacts/production_review_index.json")
        if not any(row.get("record_path") == data["record_ref"]["path"] and row.get("id") == record.get("content_slot_id") for row in index.get("items", []) if isinstance(row, dict)):
            raise ValueError("Production record is not indexed in this project")
        return {"record": record, "opening": opening, "record_path": record_path}
    except (ValidationError, ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        raise OperatorError.validation_failed("实验结果与当前生产证据不匹配或数值无效") from exc


def import_result(root: Path, payload: dict, *, actor_id: str) -> dict:
    """Write one canonical version; same import ID and bytes replay harmlessly."""
    root = Path(root)
    if not isinstance(payload, dict):
        raise OperatorError.validation_failed("实验结果格式无效")
    if set(payload) & {"imported_at", "imported_by", "source_sha256", "semantic_sha256", "artifact_sha256"}:
        raise OperatorError.validation_failed("导入元数据由系统生成")
    try:
        validate_artifact("experiment_result", payload)
        digest = _digest(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise OperatorError.validation_failed("实验结果格式或数值无效") from exc
    relative = f"{RESULT_DIR}/{payload['import_id']}.json"
    path = root / relative
    if path.is_symlink():
        raise OperatorError("idempotency_conflict", "导入标识对应的结果文件无效", 409)
    if path.exists():
        previous = read_object(root, relative)
        if _source_matches(previous) and previous.get("source_sha256") == digest:
            return {"status": "replayed", "import_id": payload["import_id"]}
        raise OperatorError("idempotency_conflict", "导入标识已用于另一份结果", 409)
    _validate(root, payload)
    document = {**payload, "imported_at": datetime.now(timezone.utc).isoformat(),
                "imported_by": actor_id, "source_sha256": digest}
    validate_artifact("experiment_result", document)
    store = ProjectCommitStore(root)
    class _ReplayExisting(Exception):
        pass

    try:
        with store.transaction(action={"action_id": f"opening-result-{payload['import_id']}", "type": "import_opening_result"},
            result={"status": "imported", "import_id": payload["import_id"]},
            audit={"event_type": "opening_result_imported", "actor_id": actor_id}) as sink:
            existing = sink.read_json(relative)
            if existing is not None:
                if not _source_matches(existing) or existing.get("source_sha256") != digest:
                    raise OperatorError("idempotency_conflict", "导入标识已用于另一份结果", 409)
                raise _ReplayExisting()
            _validate(root, payload)
            sink.stage_json(relative, document, schema="experiment_result")
    except _ReplayExisting:
        return {"status": "replayed", "import_id": payload["import_id"]}
    return {"status": "imported", "import_id": payload["import_id"]}


def _metric_view(metric: dict) -> dict:
    numerator, denominator = metric["numerator"], metric["denominator"]
    value = (numerator / denominator if metric["kind"] == "rate" and numerator is not None and denominator
             else numerator if metric["kind"] != "rate" else None)
    return {**metric, "value": value, "status": "observed" if value is not None else "undefined"}


def _source_matches(document: dict) -> bool:
    source = {key: value for key, value in document.items() if key not in {"imported_at", "imported_by", "source_sha256"}}
    try:
        return _digest(source) == document.get("source_sha256")
    except (TypeError, ValueError):
        return False


def results_by_record(root: Path) -> dict[str, list[dict]]:
    """Read each imported file once for one request; never cache evidence state."""
    root = Path(root)
    directory = root / RESULT_DIR
    if not directory.is_dir():
        return {}
    files = list(directory.glob("*.json"))
    if len(files) > 3000:
        raise ValueError("Opening result history exceeds explicit read limit")
    grouped: dict[str, list[dict]] = {}
    for path in sorted(files):
        try:
            if path.is_symlink():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_artifact("experiment_result", data)
            if not _source_matches(data):
                continue
            record_path = data["record_ref"]["path"]
            binding = "current"
            for ref in (data["record_ref"], data["render_ref"], data["experiment_ref"], data["raw_export_ref"]):
                try:
                    _bound_file(root, ref)
                except (ValueError, OSError):
                    binding = "stale"
            if binding == "current":
                try:
                    opening = opening_review_scope(root, read_object(root, data["record_ref"]["path"]))
                    if (not opening or opening["candidate_id"] != data["candidate_id"]
                            or opening["experiment_ref"] != data["experiment_ref"]):
                        binding = "stale"
                except (ValidationError, ValueError, OSError, KeyError, TypeError):
                    binding = "stale"
            grouped.setdefault(record_path, []).append({**data, "metrics": [_metric_view(m) for m in data["metrics"]],
                "binding_status": binding, "comparison_status": "数据不足" if binding == "current" else "不可比",
                "comparison_reasons": [] if binding == "current" else ["原始导出或绑定的生产证据已变化"],
                "conclusion": "已导入，尚无结论"})
        except (OSError, ValueError, ValidationError, KeyError, TypeError):
            continue
    for rows in grouped.values():
        for row in rows:
            a, b = _window(row["window"])
            if row["window"]["semantics"] == "cumulative" and any(
                other is not row and other["window"]["semantics"] == "cumulative" and
                other["platform"] == row["platform"] and other["account_id"] == row["account_id"] and
                other["publication_id"] == row["publication_id"] and other["ad_id"] == row["ad_id"] and
                a < _window(other["window"])[1] and _window(other["window"])[0] < b for other in rows):
                row["comparison_reasons"].append("累计快照窗口重叠，不可当作独立样本相加")
    return grouped


def results_for_record(root: Path, record_path: str) -> list[dict]:
    """Compatibility read for one record, with fresh evidence checks."""
    return results_by_record(root).get(record_path, [])


def comparison_reasons(row: dict, baseline: dict, *, group_same: bool, scope_same: bool, duration_same: bool | None) -> list[str]:
    """Describe compatibility only; no rank or causal decision is calculated."""
    reasons = []
    if not group_same: reasons.append("不同基线组")
    if not scope_same: reasons.append("预览与完整成片范围不同")
    if duration_same is None: reasons.append("成片时长未知")
    elif not duration_same: reasons.append("成片时长不同")
    for key, label in (("platform", "平台"), ("account_id", "账号")):
        if row[key] != baseline[key]: reasons.append(f"{label}不同")
    if row["audience"] != baseline["audience"]: reasons.append("受众或分配条件不同")
    if row["window"]["semantics"] != baseline["window"]["semantics"]: reasons.append("窗口语义不同")
    if _window(row["window"])[1] - _window(row["window"])[0] != _window(baseline["window"])[1] - _window(baseline["window"])[0]: reasons.append("观察时长不同")
    definitions = {(m["metric_id"], m["definition"], m["kind"], m["numerator_unit"], m["denominator_unit"], m["count_unit"], m["duration_unit"]) for m in row["metrics"]}
    other_definitions = {(m["metric_id"], m["definition"], m["kind"], m["numerator_unit"], m["denominator_unit"], m["count_unit"], m["duration_unit"]) for m in baseline["metrics"]}
    if definitions != other_definitions: reasons.append("指标定义或分母单位不同")
    if row["binding_status"] != "current" or baseline["binding_status"] != "current": reasons.append("生产证据或原始导出已失效")
    return reasons

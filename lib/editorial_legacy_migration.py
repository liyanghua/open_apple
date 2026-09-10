"""Trusted migration for approved Source-led candidates created before Timeline V2.

Legacy runs predate the V2 asset and fact bindings.  This module never trusts
their proxy paths or a hand-authored migration record: every visual/audio file
is resolved inside the candidate, re-hashed, and re-bound to an approved shot
plan before the canonical timeline is materialized.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from backlot.project_commit import ProjectCommitStore
from lib.cache_keys import canonical_digest
from lib.editorial_timeline import EditorialMaterializationError, materialize_editorial_timeline


class LegacyEditorialMigrationError(ValueError):
    """Raised when an old candidate cannot satisfy the V2 proof contract."""


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyEditorialMigrationError(f"{label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise LegacyEditorialMigrationError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(project: Path, raw: Any, *, label: str) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise LegacyEditorialMigrationError(f"{label} has no file path")
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(project)
        except ValueError as exc:
            raise LegacyEditorialMigrationError(f"{label} points outside the candidate") from exc
        local = project / relative
    else:
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise LegacyEditorialMigrationError(f"{label} has an unsafe candidate-relative path")
        # Source inputs commonly remain as candidate-local symlinks to the
        # customer-owned folder.  We retain the safe local link path in the
        # catalogue but hash the file it resolves to, so an external target
        # can never be injected by a client path.
        local = project / candidate
        relative = candidate
    if not local.is_file():
        raise LegacyEditorialMigrationError(f"{label} file is missing")
    return local, relative.as_posix()


def _items(value: Any, *, key: str) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in source:
        if isinstance(item, Mapping) and isinstance(item.get(key), str) and item[key]:
            result[str(item[key])] = dict(item)
    return result


def _duration(value: Mapping[str, Any], *, fallback: float) -> float:
    for nested in (value, value.get("probe"), value.get("technical_probe")):
        if isinstance(nested, Mapping):
            raw = nested.get("duration_seconds")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) > 0:
                return float(raw)
    return fallback


def _load_generated_execution(project: Path, task_id: str, shot_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    task = _read_object(project / "operator" / "shot-generation" / "tasks" / f"{task_id}.json", label=f"generation task {task_id}")
    if task.get("status") != "completed" or str(task.get("shot_id") or "") != shot_id:
        raise LegacyEditorialMigrationError(f"generation task {task_id} is not a completed {shot_id} task")
    executions = project / "operator" / "product-image-execution"
    matches: list[dict[str, Any]] = []
    for candidate in executions.glob("*.json") if executions.is_dir() else []:
        entry = _read_object(candidate, label=f"generation execution {candidate.name}")
        if str(entry.get("idempotency_key") or "") == task_id:
            matches.append(entry)
    if len(matches) != 1:
        raise LegacyEditorialMigrationError(f"generation task {task_id} lacks one execution record")
    execution = matches[0]
    if execution.get("approved") is False:
        raise LegacyEditorialMigrationError(f"generation task {task_id} is not approved")
    if str(execution.get("shot_id") or "") != shot_id:
        raise LegacyEditorialMigrationError(f"generation task {task_id} execution shot does not match")
    return task, execution


def _find_legacy_task(project: Path, *, shot_id: str, proposal_id: str | None) -> str:
    tasks = project / "operator" / "shot-generation" / "tasks"
    candidates: list[str] = []
    for path in tasks.glob("*.json") if tasks.is_dir() else []:
        task = _read_object(path, label=f"generation task {path.name}")
        if task.get("status") != "completed" or str(task.get("shot_id") or "") != shot_id:
            continue
        if proposal_id and str(task.get("proposal_id") or "") != proposal_id:
            continue
        candidates.append(str(task.get("task_id") or ""))
    candidates = [candidate for candidate in candidates if candidate]
    if len(candidates) != 1:
        raise LegacyEditorialMigrationError(f"{shot_id} must resolve exactly one completed generation task")
    return candidates[0]


def _claim_id(claim: Mapping[str, Any]) -> str | None:
    value = claim.get("id", claim.get("claim_id"))
    return str(value) if isinstance(value, str) and value else None


def _unsealed(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a migration-derived view without stale legacy envelope hashes."""
    result = deepcopy(dict(value))
    result.pop("semantic_sha256", None)
    result.pop("artifact_sha256", None)
    return result


def _prepare_inputs(project: Path) -> dict[str, Any]:
    artifacts = project / "artifacts"
    legacy_facts = _read_object(artifacts / "product_facts.json", label="product facts")
    legacy_review = _read_object(artifacts / "source_media_review.json", label="source media review")
    legacy_index = _read_object(artifacts / "media_index.json", label="media index")
    legacy_matrix = _read_object(artifacts / "reference_source_matrix.json", label="coverage matrix")
    legacy_shots = _read_object(artifacts / "shot_execution_plan.json", label="shot execution plan")
    legacy_props = _read_object(artifacts / "final_props.json", label="final props")
    legacy_edits = _read_object(artifacts / "edit_decisions.json", label="edit decisions")
    legacy_assets = _read_object(artifacts / "asset_manifest.json", label="asset manifest")

    if legacy_edits.get("render_runtime") != "remotion":
        raise LegacyEditorialMigrationError("only remotion candidates can enter the V2 studio")
    if legacy_shots.get("status") != "approved":
        raise LegacyEditorialMigrationError("shot execution plan is not approved")
    if legacy_matrix.get("matrix_mode") not in {"source_led", "source_led_template"}:
        raise LegacyEditorialMigrationError("coverage matrix is not Source-led")

    candidate_id = project.name
    claims: list[dict[str, Any]] = []
    for legacy_claim in legacy_facts.get("claims") or []:
        if not isinstance(legacy_claim, Mapping):
            continue
        claim = dict(legacy_claim)
        claim_id = _claim_id(claim)
        if claim_id is None:
            continue
        claim["id"] = claim_id
        claim["visual_requirement_id"] = str(claim.get("visual_requirement_id") or f"legacy-visual-{claim_id}")
        claims.append(claim)
    fact_ids = {claim["id"] for claim in claims}
    if not fact_ids:
        raise LegacyEditorialMigrationError("product facts contain no claims")
    product_facts = {**_unsealed(legacy_facts), "claims": claims}

    review_by_id = _items(legacy_review.get("files"), key="media_id")
    index_by_id = _items(legacy_index.get("entries"), key="media_id")
    source_evidence: list[dict[str, Any]] = []
    source_videos: dict[str, dict[str, Any]] = {}
    visual_assets: dict[str, dict[str, Any]] = {}
    normalized_rows: list[dict[str, Any]] = []
    normalized_shots: list[dict[str, Any]] = []
    legacy_scene_by_id = {
        str(scene.get("id")): scene
        for scene in legacy_props.get("scenes") or []
        if isinstance(scene, Mapping) and isinstance(scene.get("id"), str)
    }

    for source_shot in legacy_shots.get("shots") or []:
        if not isinstance(source_shot, Mapping):
            continue
        shot = dict(source_shot)
        shot_id = str(shot.get("id") or "")
        if not shot_id:
            raise LegacyEditorialMigrationError("shot execution plan has an unnamed shot")
        row_ids = shot.get("evidence_row_ids")
        if not isinstance(row_ids, list) or len(row_ids) != 1 or not isinstance(row_ids[0], str):
            raise LegacyEditorialMigrationError(f"{shot_id} needs exactly one coverage row")
        if not isinstance(shot.get("claim_ids"), list) or not shot["claim_ids"] or any(claim not in fact_ids for claim in shot["claim_ids"]):
            raise LegacyEditorialMigrationError(f"{shot_id} has unproven fact bindings")
        normalized_shots.append(shot)

    shot_by_row = {
        str(row_id): shot
        for shot in normalized_shots
        for row_id in (shot.get("evidence_row_ids") or [])
        if isinstance(row_id, str)
    }

    for legacy_row in legacy_matrix.get("rows") or []:
        if not isinstance(legacy_row, Mapping) or legacy_row.get("resolution") != "accept":
            continue
        row = dict(legacy_row)
        row_id = str(row.get("matrix_row_id") or "")
        shot = shot_by_row.get(row_id)
        if not row_id or shot is None:
            raise LegacyEditorialMigrationError("accepted coverage row lacks approved shot binding")
        shot_id = str(shot["id"])
        claim_ids = row.get("claim_ids")
        if not isinstance(claim_ids, list) or claim_ids != shot.get("claim_ids") or any(claim not in fact_ids for claim in claim_ids):
            raise LegacyEditorialMigrationError(f"coverage row {row_id} fact scope does not match its shot")
        row["shot_id"] = shot_id
        row["visual_requirement_id"] = str(next(claim["visual_requirement_id"] for claim in claims if claim["id"] == claim_ids[0]))
        route = str(shot.get("visual_route") or row.get("visual_route") or "owned_source")
        if route == "owned_source":
            media_id = str(shot.get("source_media_id") or row.get("source_media_id") or "")
            review, index = review_by_id.get(media_id), index_by_id.get(media_id)
            if review is None or review.get("reviewed") is not True:
                raise LegacyEditorialMigrationError(f"coverage row {row_id} lacks reviewed media evidence")
            # Early media_index artifacts were keyed by path rather than media_id
            # and sometimes retained the source project's absolute path.  The
            # reviewed candidate-local path is the migration authority.
            raw_path = review.get("path") or (index or {}).get("path")
            source_path, relative_path = _inside(project, raw_path, label=f"source media {media_id}")
            source_hash = _sha256(source_path)
            duration = _duration(index or {}, fallback=_duration(review, fallback=0.0))
            if duration <= 0:
                raise LegacyEditorialMigrationError(f"source media {media_id} has no duration")
            source_evidence.append({"media_id": media_id, "reviewed": True, "media_type": "video", "sha256": source_hash, "technical_probe": {"duration_seconds": duration}})
            source_videos[media_id] = {"media_id": media_id, "sha256": source_hash, "duration_seconds": duration}
            visual_assets[media_id] = {"id": media_id, "type": "video", "path": relative_path, "sha256": source_hash, "approved": True, "duration_seconds": duration, "provenance": {"source": "source_media", "media_id": media_id}}
            row.update({"visual_route": "owned_source", "approved_asset_id": media_id, "source_media_id": media_id, "source_hash": source_hash})
            selection = shot.get("source_selection")
            if not isinstance(selection, Mapping):
                raise LegacyEditorialMigrationError(f"{shot_id} lacks source selection")
            shot["source_media_id"] = media_id
            row["source_time_range"] = {"start_seconds": selection.get("start_seconds"), "end_seconds": selection.get("end_seconds", selection.get("end_seconds_exclusive"))}
        elif route in {"generated_from_product_image", "approved_generated_asset"}:
            proposals = shot.get("generation_proposals") if isinstance(shot.get("generation_proposals"), list) else []
            proposal_id = str(proposals[0].get("id") or "") if proposals and isinstance(proposals[0], Mapping) else None
            task_id = str(shot.get("selected_generation_task_id") or "") or _find_legacy_task(project, shot_id=shot_id, proposal_id=proposal_id)
            task, execution = _load_generated_execution(project, task_id, shot_id)
            output_path, relative_path = _inside(project, execution.get("output_path") or task.get("output_path"), label=f"generation task {task_id}")
            output_hash = _sha256(output_path)
            supplied_hash = execution.get("output_sha256")
            if isinstance(supplied_hash, str) and supplied_hash and supplied_hash != output_hash:
                raise LegacyEditorialMigrationError(f"generation task {task_id} output hash mismatch")
            valid_range = row.get("source_time_range")
            if not isinstance(valid_range, Mapping):
                scene = legacy_scene_by_id.get(shot_id)
                if not isinstance(scene, Mapping):
                    raise LegacyEditorialMigrationError(f"coverage row {row_id} has no generated media range")
                valid_range = {
                    "start_seconds": scene.get("sourceInSeconds"),
                    "end_seconds": scene.get("sourceOutSeconds"),
                }
                row["source_time_range"] = valid_range
            end = valid_range.get("end_seconds_exclusive", valid_range.get("end_seconds"))
            if not isinstance(end, (int, float)) or float(end) <= 0:
                raise LegacyEditorialMigrationError(f"coverage row {row_id} has an invalid generated media range")
            asset_id = f"generated-{task_id}"
            visual_assets[asset_id] = {"id": asset_id, "type": "video", "path": relative_path, "sha256": output_hash, "approved": True, "duration_seconds": float(end), "provenance": {"source": "generation_task", "generation_task_id": task_id, "shot_id": shot_id}}
            row.update({"visual_route": "generated_from_product_image", "approved_asset_id": asset_id, "generated_asset_id": asset_id, "generation_task_id": task_id, "source_hash": output_hash})
            shot["selected_generation_task_id"] = task_id
            shot["generated_asset_id"] = asset_id
        else:
            raise LegacyEditorialMigrationError(f"{shot_id} uses an unsupported visual route")
        normalized_rows.append(row)

    if len(normalized_rows) != len(normalized_shots):
        raise LegacyEditorialMigrationError("each approved shot must have accepted coverage")
    for shot in normalized_shots:
        if str(shot["id"]) not in {str(row["shot_id"]) for row in normalized_rows}:
            raise LegacyEditorialMigrationError(f"{shot['id']} has no accepted coverage")

    by_shot = {str(shot["id"]): shot for shot in normalized_shots}
    props = _unsealed(legacy_props)
    props["project_id"] = candidate_id
    for scene in props.get("scenes") or []:
        if not isinstance(scene, dict) or str(scene.get("id") or "") not in by_shot:
            raise LegacyEditorialMigrationError("final props scene lacks approved shot binding")
        shot = by_shot[str(scene["id"])]
        scene["evidence_row_ids"] = list(shot["evidence_row_ids"])
        scene["claim_ids"] = list(shot["claim_ids"])
        scene["screen_copy"] = str(shot.get("screen_copy") or "").strip()
        if not scene["screen_copy"]:
            raise LegacyEditorialMigrationError(f"{scene['id']} has no approved selling-point text")
        if shot.get("visual_route") == "owned_source":
            selection = shot.get("source_selection")
            if not isinstance(selection, Mapping):
                raise LegacyEditorialMigrationError(f"{scene['id']} lacks the approved raw-media range")
            scene["sourceInSeconds"] = selection.get("start_seconds")
            scene["sourceOutSeconds"] = selection.get("end_seconds", selection.get("end_seconds_exclusive"))

    fps = float(props.get("fps") or 0)
    if fps <= 0:
        raise LegacyEditorialMigrationError("final props have no valid fps")
    scene_windows = [
        (float(scene["fromFrame"]) / fps, float(scene["toFrameExclusive"]) / fps)
        for scene in props.get("scenes") or []
        if isinstance(scene, Mapping)
    ]
    for caption in props.get("captions") or []:
        if not isinstance(caption, dict):
            raise LegacyEditorialMigrationError("final props caption is invalid")
        start = float(caption.get("startMs", -1)) / 1000
        end = float(caption.get("endMs", -1)) / 1000
        window = next((item for item in scene_windows if item[0] <= start and end <= item[1] + 0.001), None)
        if window is None:
            raise LegacyEditorialMigrationError("caption crosses approved scene boundaries")
        # Older props used the exact frame end.  Keep text in its fact-bound
        # scene with a 1 ms inset so float conversion cannot make it spill into
        # the next clip during V2 validation.
        if abs(end - window[1]) <= 0.001:
            caption["endMs"] = max(int(caption["startMs"]) + 1, int(window[1] * 1000) - 1)

    assets: list[dict[str, Any]] = list(visual_assets.values())
    legacy_by_id = _items(legacy_assets.get("assets"), key="id")
    narration_legacy = legacy_by_id.get("sample-mix")
    music_legacy = legacy_by_id.get("bgm-30s")
    if narration_legacy is None or music_legacy is None:
        raise LegacyEditorialMigrationError("legacy audio mix assets are incomplete")
    total_duration = max(float(scene.get("toFrameExclusive", 0)) for scene in props.get("scenes") or []) / float(props.get("fps") or 0)
    if total_duration <= 0:
        raise LegacyEditorialMigrationError("final props have no duration")
    for legacy, role in ((narration_legacy, "narration"), (music_legacy, "music")):
        path, relative = _inside(project, legacy.get("path"), label=f"{role} asset")
        assets.append({"id": str(legacy["id"]), "type": "audio", "role": role, "path": relative, "sha256": _sha256(path), "approved": True, "duration_seconds": _duration(legacy, fallback=total_duration), "provenance": {"source": "legacy_asset_manifest", "asset_id": str(legacy["id"])}})
    asset_manifest = {"version": "1.0", "metadata": {"candidate_id": candidate_id, "project_id": candidate_id, "migration": "source-led-v2"}, "assets": assets}
    coverage_matrix = {"version": "1.0", "project_id": candidate_id, "matrix_mode": "source_led_template", "rows": normalized_rows}
    generation_tasks = []
    for shot in normalized_shots:
        task_id = shot.get("selected_generation_task_id")
        if not task_id:
            continue
        asset = visual_assets[str(shot["generated_asset_id"])]
        generation_tasks.append({"task_id": task_id, "candidate_id": candidate_id, "project_id": candidate_id, "shot_id": shot["id"], "status": "completed", "approved": True, "output": {"asset_id": asset["id"], "sha256": asset["sha256"], "valid_range": next(row["source_time_range"] for row in normalized_rows if row["shot_id"] == shot["id"])}})
    narration = {"asset_id": "sample-mix", "start_seconds": 0.0, "end_seconds": total_duration, "text": " ".join(str(shot.get("narration") or shot.get("screen_copy") or "") for shot in normalized_shots).strip(), "claim_ids": [claim for shot in normalized_shots for claim in shot["claim_ids"]]}
    narration["claim_ids"] = list(dict.fromkeys(narration["claim_ids"]))
    return {"candidate_id": candidate_id, "edit_decisions": _unsealed(legacy_edits), "final_props": props, "asset_manifest": asset_manifest, "coverage_matrix": coverage_matrix, "product_facts": product_facts, "source_media_evidence": {"files": source_evidence}, "source_videos": source_videos, "shot_execution_plan": {"version": "1.0", "project_id": candidate_id, "status": "approved", "shots": normalized_shots}, "generation_tasks": generation_tasks, "narration": narration, "bgm": {"asset_id": "bgm-30s", "start_seconds": 0.0, "end_seconds": total_duration}}


def migrate_legacy_source_led_candidate(project_dir: str | Path, *, actor_id: str) -> dict[str, Any]:
    """Atomically materialize V2 artifacts for one proven legacy candidate.

    Existing V2 artifacts are immutable: rerunning returns the existing current
    migration only when its input fingerprint is identical.
    """
    project = Path(project_dir).resolve()
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise LegacyEditorialMigrationError("migration actor is required")
    inputs = _prepare_inputs(project)
    store = ProjectCommitStore(project)
    pointer = store.initialize()
    revision = "legacy-" + canonical_digest({"candidate_id": inputs["candidate_id"], "inputs": inputs})[:16]
    try:
        with store.transaction(action={"action_id": f"editorial-legacy-migrate-{revision}", "type": "editorial_legacy_migration"}, result={"status": "migrated", "candidate_id": inputs["candidate_id"]}, audit={"event_type": "editorial_legacy_migrated", "actor_id": actor_id}, expected_generation=pointer["generation_id"], business_diff=["Rebuilt Timeline V2 fact, asset, and approval bindings from approved legacy Source-led artifacts."]) as sink:
            snapshot = materialize_editorial_timeline(candidate_id=inputs["candidate_id"], project_id=store.project_id, base_generation_id=sink.generation_id, base_edit_revision=revision, edit_decisions=inputs["edit_decisions"], final_props=inputs["final_props"], asset_manifest=inputs["asset_manifest"], coverage_matrix=inputs["coverage_matrix"], product_facts=inputs["product_facts"], source_media_evidence=inputs["source_media_evidence"], source_videos=inputs["source_videos"], shot_execution_plan=inputs["shot_execution_plan"], generation_tasks=inputs["generation_tasks"], narration=inputs["narration"], bgm=inputs["bgm"])
            sink.stage_json("artifacts/editorial_timeline.json", snapshot["timeline"], schema="editorial_timeline")
            sink.stage_json("operator/editorial/asset-catalogue.json", snapshot["asset_catalogue"], schema="editorial_catalogue")
            sink.stage_json("operator/editorial/legacy-migration.json", {"version": "1.0", "candidate_id": inputs["candidate_id"], "generation_id": sink.generation_id, "base_edit_revision": revision, "input_fingerprint": canonical_digest(inputs), "actor_id": actor_id}, schema="editorial_migration")
    except EditorialMaterializationError as exc:
        raise LegacyEditorialMigrationError(str(exc)) from exc
    return {"status": "migrated", "candidate_id": inputs["candidate_id"], "generation_id": store.initialize()["generation_id"], "revision": revision}

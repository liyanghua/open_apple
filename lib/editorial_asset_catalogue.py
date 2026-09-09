"""Build the server-owned set of source-led visual assets for editorial work."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.cache_keys import canonical_digest


class EditorialMaterializationError(ValueError):
    """Raised when source-led inputs cannot prove an editorial asset is allowed."""


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EditorialMaterializationError(f"{field} must be an object")
    return value


def _identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EditorialMaterializationError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, *, field: str) -> str:
    result = _identifier(value, field=field)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise EditorialMaterializationError(f"{field} must be a sha256")
    return result


def _seconds(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise EditorialMaterializationError(f"{field} must be a non-negative number")
    return float(value)


def _range(value: Any, *, field: str) -> dict[str, float]:
    item = _mapping(value, field=field)
    start = _seconds(item.get("start_seconds"), field=f"{field}.start_seconds")
    end = _seconds(
        item.get("end_seconds_exclusive", item.get("end_seconds")),
        field=f"{field}.end_seconds",
    )
    if end <= start:
        raise EditorialMaterializationError(f"{field} must have a positive duration")
    return {"start_seconds": start, "end_seconds": end}


def _index_items(value: Any, *, field: str, key: str) -> dict[str, Mapping[str, Any]]:
    items = value.get("assets") if isinstance(value, Mapping) and field == "asset_manifest" else value
    if isinstance(items, Mapping):
        pairs = items.items()
    elif isinstance(items, list):
        pairs = ((item.get(key), item) for item in items if isinstance(item, Mapping))
    else:
        raise EditorialMaterializationError(f"{field} must contain a list or object")
    indexed: dict[str, Mapping[str, Any]] = {}
    for item_id, item in pairs:
        if isinstance(item, Mapping) and isinstance(item_id, str) and item_id:
            indexed[item_id] = item
    return indexed


def _claim_requirements(product_facts: Mapping[str, Any]) -> dict[str, str]:
    claims = product_facts.get("claims")
    if not isinstance(claims, list):
        raise EditorialMaterializationError("product_facts.claims must be a list")
    requirements: dict[str, str] = {}
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        claim_id = claim.get("id", claim.get("claim_id"))
        requirement_id = claim.get("visual_requirement_id")
        if isinstance(claim_id, str) and claim_id and isinstance(requirement_id, str) and requirement_id:
            requirements[claim_id] = requirement_id
    return requirements


def _approved_asset(
    assets: Mapping[str, Mapping[str, Any]], asset_id: str, *, field: str
) -> Mapping[str, Any]:
    asset = assets.get(asset_id)
    if asset is None:
        raise EditorialMaterializationError(f"{field} is not present in asset_manifest")
    if asset.get("approved") is not True:
        raise EditorialMaterializationError(f"{field} is not approved")
    return asset


def build_editorial_asset_catalogue(
    *,
    candidate_id: str,
    asset_manifest: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    product_facts: Mapping[str, Any],
    source_media_evidence: Mapping[str, Any],
    source_videos: Mapping[str, Any] | list[Mapping[str, Any]],
    shot_execution_plan: Mapping[str, Any] | None = None,
    generation_tasks: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return only visual assets whose evidence, scope, and media bounds are proven.

    The result deliberately derives opaque IDs instead of accepting IDs supplied by
    an editor.  It is a snapshot: later edit operations can only reference one of
    these scoped asset entries and its verified source range.
    """
    candidate_id = _identifier(candidate_id, field="candidate_id")
    coverage_matrix = _mapping(coverage_matrix, field="coverage_matrix")
    if coverage_matrix.get("matrix_mode") not in {"source_led", "source_led_template"}:
        raise EditorialMaterializationError("coverage_matrix must be source-led")
    rows = coverage_matrix.get("rows")
    if not isinstance(rows, list):
        raise EditorialMaterializationError("coverage_matrix.rows must be a list")
    accepted_rows = [
        row for row in rows
        if isinstance(row, Mapping) and row.get("resolution") == "accept"
    ]
    if not accepted_rows:
        raise EditorialMaterializationError("coverage_matrix has no accepted coverage")

    assets = _index_items(asset_manifest, field="asset_manifest", key="id")
    evidence_files = _index_items(
        _mapping(source_media_evidence, field="source_media_evidence").get("files"),
        field="source_media_evidence.files",
        key="media_id",
    )
    source_metadata = _index_items(source_videos, field="source_videos", key="media_id")
    if shot_execution_plan is None:
        raise EditorialMaterializationError("shot execution plan is required")
    shot_plan = _mapping(shot_execution_plan, field="shot execution plan")
    if shot_plan.get("status") not in {"approved", "completed"}:
        raise EditorialMaterializationError(
            "shot execution plan must be approved or completed"
        )
    shot_plan_items = _index_items(
        shot_plan.get("shots") or [],
        field="shot_execution_plan.shots", key="id",
    )
    if not shot_plan_items:
        raise EditorialMaterializationError("shot execution plan has no shots")
    task_items = _index_items(generation_tasks or [], field="generation_tasks", key="task_id")
    fact_requirements = _claim_requirements(_mapping(product_facts, field="product_facts"))
    catalogue_assets: list[dict[str, Any]] = []

    for row in accepted_rows:
        row_id = _identifier(row.get("matrix_row_id"), field="coverage_matrix row id")
        claim_ids = row.get("claim_ids")
        if (
            not isinstance(claim_ids, list)
            or not claim_ids
            or not all(isinstance(item, str) and item for item in claim_ids)
        ):
            raise EditorialMaterializationError(f"coverage row {row_id} has no valid claim_ids")
        visual_requirement_id = _identifier(
            row.get("visual_requirement_id") or fact_requirements.get(claim_ids[0]),
            field=f"coverage row {row_id}.visual_requirement_id",
        )
        if any(fact_requirements.get(claim_id) != visual_requirement_id for claim_id in claim_ids):
            raise EditorialMaterializationError(f"coverage row {row_id} lacks matching product fact evidence")

        source_class = str(row.get("visual_route") or "owned_source")
        if source_class not in {"owned_source", "generated_from_product_image", "approved_generated_asset"}:
            raise EditorialMaterializationError(f"coverage row {row_id} has unsupported source class")
        source_asset_id = _identifier(
            row.get("approved_asset_id") or row.get("generated_asset_id") or row.get("source_media_id"),
            field=f"coverage row {row_id}.asset_id",
        )
        asset = _approved_asset(assets, source_asset_id, field=f"coverage row {row_id}.asset_id")
        if asset.get("type") != "video":
            raise EditorialMaterializationError(f"coverage row {row_id}.asset_id must be a video asset")
        source_hash = _sha256(
            row.get("source_hash", asset.get("sha256")),
            field=f"coverage row {row_id}.source_hash",
        )
        asset_hash = _sha256(asset.get("sha256"), field=f"asset_manifest {source_asset_id}.sha256")
        if source_hash != asset_hash:
            raise EditorialMaterializationError(f"coverage row {row_id} source hash does not match asset")

        valid_range = _range(row.get("source_time_range"), field=f"coverage row {row_id}.source_time_range")
        shot_id_hint = row.get("shot_id") or row.get("scene_id")
        shot = shot_plan_items.get(str(shot_id_hint)) if shot_id_hint else None
        if shot is None:
            shot = next(
                (
                    item for item in shot_plan_items.values()
                    if row_id in (item.get("evidence_row_ids") or [])
                ),
                None,
            )
        if shot is None:
            raise EditorialMaterializationError(
                f"coverage row {row_id} lacks shot execution plan binding"
            )
        shot_id = _identifier(shot.get("id"), field=f"coverage row {row_id}.shot_id")
        if row_id not in (shot.get("evidence_row_ids") or []):
            raise EditorialMaterializationError(
                f"coverage row {row_id} is not bound to shot execution plan"
            )
        if shot.get("visual_route") not in {
            "owned_source", "generated_from_product_image", "approved_generated_asset",
        }:
            raise EditorialMaterializationError(
                f"coverage row {row_id} has unsupported shot execution route"
            )
        if source_class == "owned_source":
            if shot.get("visual_route") != "owned_source":
                raise EditorialMaterializationError(
                    f"coverage row {row_id} shot execution plan route mismatch"
                )
            media_id = _identifier(row.get("source_media_id"), field=f"coverage row {row_id}.source_media_id")
            if str(shot.get("source_media_id") or "") != media_id:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} shot execution plan media mismatch"
                )
            selection = shot.get("source_selection")
            if not isinstance(selection, Mapping):
                raise EditorialMaterializationError(
                    f"coverage row {row_id} shot execution plan lacks source selection"
                )
            if str(selection.get("media_id") or "") != media_id:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} shot execution plan media mismatch"
                )
            selected_range = _range(selection, field=f"shot {shot_id}.source_selection")
            if selected_range != valid_range:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} shot execution plan range mismatch"
                )
            evidence = evidence_files.get(media_id)
            metadata = source_metadata.get(media_id)
            if (
                evidence is None
                or evidence.get("reviewed") is not True
                or evidence.get("media_type") != "video"
            ):
                raise EditorialMaterializationError(f"coverage row {row_id} lacks reviewed source-media evidence")
            if metadata is None:
                raise EditorialMaterializationError(f"coverage row {row_id} lacks source video metadata")
            if _sha256(evidence.get("sha256"), field=f"source evidence {media_id}.sha256") != source_hash:
                raise EditorialMaterializationError(f"coverage row {row_id} source evidence hash mismatch")
            if _sha256(metadata.get("sha256"), field=f"source video {media_id}.sha256") != source_hash:
                raise EditorialMaterializationError(f"coverage row {row_id} source video hash mismatch")
            duration = _seconds(
                metadata.get("duration_seconds"),
                field=f"source video {media_id}.duration_seconds",
            )
            if valid_range["end_seconds"] > duration:
                raise EditorialMaterializationError(f"coverage row {row_id} exceeds source video duration")
        else:
            if shot is None or shot.get("visual_route") not in {
                "generated_from_product_image", "approved_generated_asset",
            }:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} lacks shot execution generation provenance"
                )
            if row_id not in (shot.get("evidence_row_ids") or []):
                raise EditorialMaterializationError(
                    f"coverage row {row_id} is not bound to shot execution plan"
                )
            if str(shot.get("generated_asset_id") or "") != source_asset_id:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} generation provenance asset mismatch"
                )
            task_id = shot.get("selected_generation_task_id") or row.get("generation_task_id")
            task = task_items.get(str(task_id)) if task_id else None
            if (
                task is None
                or task.get("approved") is not True
                or task.get("status") not in {"approved", "completed"}
            ):
                raise EditorialMaterializationError(
                    f"coverage row {row_id} lacks approved generation provenance"
                )
            if str(task.get("shot_id") or "") != shot_id:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} generation provenance shot mismatch"
                )
            output = task.get("output") if isinstance(task.get("output"), Mapping) else task
            if str(output.get("asset_id") or "") != source_asset_id:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} generation provenance asset mismatch"
                )
            if _sha256(
                output.get("sha256"), field=f"generation task {task_id}.sha256"
            ) != source_hash:
                raise EditorialMaterializationError(
                    f"coverage row {row_id} generation provenance hash mismatch"
                )
            task_range = output.get("valid_range") or output.get("source_time_range")
            if (
                task_range is None
                or _range(task_range, field=f"generation task {task_id}.valid_range")
                != valid_range
            ):
                raise EditorialMaterializationError(
                    f"coverage row {row_id} generation provenance range mismatch"
                )
            provenance = asset.get("provenance")
            if (
                not isinstance(provenance, Mapping)
                or str(provenance.get("generation_task_id") or "") != str(task_id)
                or str(provenance.get("shot_id") or "") != shot_id
            ):
                raise EditorialMaterializationError(
                    f"coverage row {row_id} lacks generation provenance"
                )

        fact_scope = {
            "claim_ids": list(claim_ids),
            "shot_id": shot_id,
            "visual_requirement_id": visual_requirement_id,
            "allowed_source_classes": [source_class],
        }
        issued_id = "editorial-" + canonical_digest({
            "candidate_id": candidate_id,
            "matrix_row_id": row_id,
            "shot_id": shot_id,
            "source_asset_id": source_asset_id,
            "source_sha256": source_hash,
            "valid_range": valid_range,
            "fact_scope": fact_scope,
        })[:24]
        catalogue_assets.append({
            "asset_id": issued_id,
            "candidate_id": candidate_id,
            "source_asset_id": source_asset_id,
            "source_sha256": source_hash,
            "source_class": source_class,
            "valid_range": valid_range,
            "claim_ids": list(claim_ids),
            "fact_scope": fact_scope,
            "visual_requirement_id": visual_requirement_id,
            "matrix_row_id": row_id,
            "shot_id": shot_id,
        })

    catalogue_assets.sort(key=lambda item: item["asset_id"])
    catalogue = {
        "version": "1.0",
        "candidate_id": candidate_id,
        "assets": catalogue_assets,
    }
    return {**catalogue, "catalogue_hash": canonical_digest(catalogue)}

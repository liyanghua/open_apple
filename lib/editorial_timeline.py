"""Materialize an executable, fact-bound EditorialTimeline from approved artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.cache_keys import canonical_digest
from lib.artifact_hashing import semantic_sha256, verify_hashes
from lib.editorial_asset_catalogue import (
    EditorialMaterializationError,
    build_editorial_asset_catalogue,
)
from schemas.artifacts import validate_artifact


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EditorialMaterializationError(f"{field} must be an object")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise EditorialMaterializationError(f"{field} must be a sha256")
    return value


def _number(value: Any, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EditorialMaterializationError(f"{field} must be numeric")
    return float(value)


def _artifact_hash(artifact: Mapping[str, Any], *, field: str) -> str:
    value = dict(artifact)
    if "artifact_sha256" in value:
        if not verify_hashes(value).valid:
            raise EditorialMaterializationError(f"{field} artifact hash verification failed")
    return semantic_sha256(value)


def _asset_index(asset_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    assets = asset_manifest.get("assets")
    if not isinstance(assets, list):
        raise EditorialMaterializationError("asset_manifest.assets must be a list")
    return {
        str(asset["id"]): asset for asset in assets
        if isinstance(asset, Mapping) and isinstance(asset.get("id"), str)
    }


def _approved_audio(
    assets: Mapping[str, Mapping[str, Any]], supplied: Mapping[str, Any], *, role: str
) -> tuple[str, str]:
    asset_id = supplied.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        raise EditorialMaterializationError(f"{role}.asset_id is required")
    asset = assets.get(asset_id)
    if asset is None or asset.get("approved") is not True or asset.get("type") != "audio":
        raise EditorialMaterializationError(f"{role}.asset_id must be an approved audio asset")
    if asset.get("role") != role:
        raise EditorialMaterializationError(f"{role}.asset_id has the wrong audio role")
    return asset_id, _sha256(asset.get("sha256"), field=f"{role} asset sha256")


def _scene_time(scene: Mapping[str, Any], *, fps: float, field: str) -> tuple[float, float]:
    start = _number(scene.get("fromFrame"), field=f"{field}.fromFrame") / fps
    end = _number(scene.get("toFrameExclusive"), field=f"{field}.toFrameExclusive") / fps
    if start < 0 or end <= start:
        raise EditorialMaterializationError(f"{field} has an invalid timeline range")
    return start, end


def materialize_editorial_timeline(
    *,
    candidate_id: str,
    project_id: str,
    base_generation_id: str,
    base_edit_revision: str,
    edit_decisions: Mapping[str, Any],
    final_props: Mapping[str, Any],
    asset_manifest: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    product_facts: Mapping[str, Any],
    source_media_evidence: Mapping[str, Any],
    source_videos: Mapping[str, Any] | list[Mapping[str, Any]],
    shot_execution_plan: Mapping[str, Any] | None = None,
    generation_tasks: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    narration: Mapping[str, Any],
    bgm: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a five-track snapshot, rejecting unproven material before rendering."""
    identifiers = (
        ("candidate_id", candidate_id),
        ("project_id", project_id),
        ("base_generation_id", base_generation_id),
        ("base_edit_revision", base_edit_revision),
    )
    for field, value in identifiers:
        if not isinstance(value, str) or not value:
            raise EditorialMaterializationError(f"{field} must be a non-empty string")
    edit_decisions = _mapping(edit_decisions, field="edit_decisions")
    final_props = _mapping(final_props, field="final_props")
    asset_manifest = _mapping(asset_manifest, field="asset_manifest")
    product_facts = _mapping(product_facts, field="product_facts")
    narration = _mapping(narration, field="narration")
    bgm = _mapping(bgm, field="bgm")
    if edit_decisions.get("render_runtime") != "remotion":
        raise EditorialMaterializationError("editorial timelines require the remotion runtime")

    catalogue = build_editorial_asset_catalogue(
        candidate_id=candidate_id,
        project_id=project_id,
        asset_manifest=asset_manifest,
        coverage_matrix=coverage_matrix,
        product_facts=product_facts,
        source_media_evidence=source_media_evidence,
        source_videos=source_videos,
        shot_execution_plan=shot_execution_plan,
        generation_tasks=generation_tasks,
    )
    fps = _number(final_props.get("fps"), field="final_props.fps")
    if fps <= 0:
        raise EditorialMaterializationError("final_props.fps must be positive")
    scenes = final_props.get("scenes")
    cuts = edit_decisions.get("cuts")
    if not isinstance(scenes, list) or not isinstance(cuts, list) or not cuts:
        raise EditorialMaterializationError(
            "approved final_props scenes and edit_decisions cuts are required"
        )
    scene_by_id = {
        str(scene["id"]): scene for scene in scenes
        if isinstance(scene, Mapping) and isinstance(scene.get("id"), str)
    }
    catalogue_by_row = {asset["matrix_row_id"]: asset for asset in catalogue["assets"]}
    video_clips: list[dict[str, Any]] = []
    text_clips: list[dict[str, Any]] = []
    for cut in cuts:
        if not isinstance(cut, Mapping) or not isinstance(cut.get("id"), str):
            raise EditorialMaterializationError("edit_decisions cut id is required")
        shot_id = cut["id"]
        scene = scene_by_id.get(shot_id)
        if scene is None:
            raise EditorialMaterializationError(f"cut {shot_id} has no approved final_props scene")
        row_ids = scene.get("evidence_row_ids")
        if not isinstance(row_ids, list) or len(row_ids) != 1 or not isinstance(row_ids[0], str):
            raise EditorialMaterializationError(f"scene {shot_id} requires exactly one accepted coverage row")
        approved = catalogue_by_row.get(row_ids[0])
        if approved is None:
            raise EditorialMaterializationError(f"scene {shot_id} has no accepted coverage")
        if approved.get("shot_id") != shot_id:
            raise EditorialMaterializationError(
                f"scene {shot_id} does not match shot execution plan"
            )
        scene_claims = scene.get("claim_ids")
        if not isinstance(scene_claims, list) or scene_claims != approved["claim_ids"]:
            raise EditorialMaterializationError(f"scene {shot_id} claim ids do not match accepted coverage")
        start, end = _scene_time(scene, fps=fps, field=f"scene {shot_id}")
        source_in = _number(
            scene.get("sourceInSeconds"),
            field=f"scene {shot_id}.sourceInSeconds",
        )
        source_out = _number(
            scene.get("sourceOutSeconds"),
            field=f"scene {shot_id}.sourceOutSeconds",
        )
        valid_range = approved["valid_range"]
        if (
            source_in < valid_range["start_seconds"]
            or source_out > valid_range["end_seconds"]
            or source_out <= source_in
        ):
            raise EditorialMaterializationError(f"scene {shot_id} exceeds approved source range")
        fact_scope = dict(approved["fact_scope"])
        video_clips.append({
            "id": f"video-{shot_id}", "asset_id": approved["asset_id"],
            "source_sha256": approved["source_sha256"], "source_in_seconds": source_in,
            "source_out_seconds": source_out, "start_seconds": start,
            "fact_scope": fact_scope,
        })
        screen_copy = scene.get("screen_copy")
        if not isinstance(screen_copy, str) or not screen_copy.strip():
            raise EditorialMaterializationError(f"scene {shot_id} lacks approved selling-point text")
        text_clips.append({
            "id": f"text-{shot_id}", "text": screen_copy.strip(), "start_seconds": start,
            "end_seconds": end, "style_token": "taobao_selling_point_v1",
            "position": "top_center", "claim_ids": list(scene_claims),
        })

    assets = _asset_index(asset_manifest)
    narration_id, narration_hash = _approved_audio(
        assets, narration, role="narration"
    )
    narration_start = _number(
        narration.get("start_seconds"), field="narration.start_seconds"
    )
    narration_end = _number(
        narration.get("end_seconds"), field="narration.end_seconds"
    )
    narration_text = narration.get("text")
    narration_claims = narration.get("claim_ids")
    if (
        narration_end <= narration_start
        or not isinstance(narration_text, str)
        or not narration_text.strip()
        or not isinstance(narration_claims, list)
        or not narration_claims
    ):
        raise EditorialMaterializationError("narration must have text, claims, and a positive range")
    fact_ids = {
        str(claim.get("id", claim.get("claim_id")))
        for claim in (product_facts.get("claims") or [])
        if isinstance(claim, Mapping) and claim.get("id", claim.get("claim_id"))
    }
    if any(claim not in fact_ids for claim in narration_claims):
        raise EditorialMaterializationError("narration claim is outside product facts")
    music_id, music_hash = _approved_audio(assets, bgm, role="music")
    music_start = _number(bgm.get("start_seconds"), field="bgm.start_seconds")
    music_end = _number(bgm.get("end_seconds"), field="bgm.end_seconds")
    if music_end <= music_start:
        raise EditorialMaterializationError("bgm must have a positive range")

    subtitle_clips: list[dict[str, Any]] = []
    captions = final_props.get("captions")
    if not isinstance(captions, list) or not captions:
        raise EditorialMaterializationError("final_props captions are required")
    for index, caption in enumerate(captions, start=1):
        if (
            not isinstance(caption, Mapping)
            or not isinstance(caption.get("text"), str)
            or not caption["text"].strip()
        ):
            raise EditorialMaterializationError("final_props caption text is required")
        start = _number(caption.get("startMs"), field="caption.startMs") / 1000
        end = _number(caption.get("endMs"), field="caption.endMs") / 1000
        matching_video = next(
            (
                clip for clip in video_clips
                if clip["start_seconds"] <= start
                and end <= (
                    clip["start_seconds"]
                    + clip["source_out_seconds"]
                    - clip["source_in_seconds"]
                )
            ),
            None,
        )
        if end <= start or matching_video is None:
            raise EditorialMaterializationError(
                "caption must stay within one fact-bound video clip"
            )
        claims = matching_video["fact_scope"]["claim_ids"]
        subtitle_clips.append({
            "id": f"subtitle-{index}", "text": caption["text"].strip(), "start_seconds": start,
            "end_seconds": end, "style_token": "taobao_subtitle_v1", "position": "bottom_center",
            "claim_ids": claims, "original_text_sha256": canonical_digest({"text": caption["text"].strip()}),
        })

    timeline = {
        "version": "1.0",
        "timeline_id": "editorial-" + canonical_digest({
            "candidate_id": candidate_id,
            "project_id": project_id,
            "revision": base_edit_revision,
        })[:24],
        "profile": {
            "profile_id": "taobao-detail-3-4", "aspect_ratio": "3:4",
            "width": int(_number(final_props.get("width"), field="final_props.width")),
            "height": int(_number(final_props.get("height"), field="final_props.height")),
            "fps": int(fps), "render_runtime": "remotion", "safe_zone": "taobao_detail_3_4",
        },
        "base_generation_id": base_generation_id,
        "base_edit_revision": base_edit_revision,
        "source_artifact_hashes": {
            "edit_decisions": _artifact_hash(edit_decisions, field="edit_decisions"),
            "final_props": _artifact_hash(final_props, field="final_props"),
            "asset_manifest": _artifact_hash(asset_manifest, field="asset_manifest"),
            "coverage_matrix": _artifact_hash(
                _mapping(coverage_matrix, field="coverage_matrix"),
                field="coverage_matrix",
            ),
            "product_facts": _artifact_hash(product_facts, field="product_facts"),
        },
        "tracks": [
            {"id": "video-main", "kind": "video", "clips": video_clips},
            {"id": "narration-main", "kind": "narration", "clips": [{
                "id": "narration-main-001", "asset_id": narration_id, "source_sha256": narration_hash,
                "start_seconds": narration_start, "end_seconds": narration_end,
                "claim_ids": list(narration_claims),
                "original_text_sha256": canonical_digest({"text": narration_text.strip()}),
            }]},
            {"id": "music-main", "kind": "music", "clips": [{
                "id": "music-main-001", "asset_id": music_id, "source_sha256": music_hash,
                "start_seconds": music_start, "end_seconds": music_end,
            }]},
            {"id": "text-main", "kind": "text", "clips": text_clips},
            {"id": "subtitle-main", "kind": "subtitle", "clips": subtitle_clips},
        ],
    }
    validate_artifact("editorial_timeline", timeline)
    return {"timeline": timeline, "asset_catalogue": catalogue}

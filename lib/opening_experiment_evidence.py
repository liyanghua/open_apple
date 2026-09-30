"""File-bound opening-package exception for existing diversity entrypoints."""
from __future__ import annotations

from jsonschema import ValidationError

from pathlib import Path

from lib.opening_freeze import _load, _require, _walk_refs, _reference_pool, verify_frozen_body
from lib.production_evidence import file_sha256, project_file, read_object


def _source_path(root, relative):
    """Support root/public staging without guessing between different bytes."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Expected a project-relative opening source")
    root = Path(root).resolve()
    (root / relative).resolve().relative_to(root)
    candidates = [relative, "public/" + relative]
    paths = [project_file(root, name) for name in candidates if (root / name).is_file()]
    if not paths:
        return project_file(root, relative)  # Preserve the missing-file diagnostic.
    if len(paths) == 2 and paths[0] != paths[1]:
        _require(file_sha256(paths[0]) == file_sha256(paths[1]),
                 "Ambiguous opening source: root and public files differ")
    return paths[0]


def _content(root, props):
    """Measure content inputs only; colour/fonts/framing are not new work."""
    scenes = []
    for row in props["scenes"]:
        if row["fromFrame"] >= 90:
            continue
        scenes.append({"sha256": file_sha256(_source_path(root, props["footage"][row["footageKey"]])),
            **{k: row.get(k) for k in ("sourceInSeconds", "sourceOutSeconds", "playbackRate", "playbackMode")}})
    return {"scenes": scenes, "titles": [row["text"] for row in props.get("titles", []) if row["fromFrame"] < 90],
            "captions": [row["text"] for row in props.get("captions", []) if row["startMs"] < 3000],
            "words": [row["text"] for row in props.get("words", []) if row["startMs"] < 3000]}


def _plan_sources_match(root, props, plan):
    opening = [s for s in props["scenes"] if s["fromFrame"] < 90]
    _require(len(opening) == len(plan["shots"]), "Opening props and registered shots disagree")
    for scene, shot in zip(opening, plan["shots"]):
        actual = file_sha256(_source_path(root, props["footage"][scene["footageKey"]]))
        _require(actual == shot["asset_identity"]["source"]["sha256"], "Opening source differs from registered hook plan")
        mapping = shot["source_mapping"]
        _require(mapping["source_interval_seconds"] == [scene["sourceInSeconds"], scene["sourceOutSeconds"]]
                 and mapping["playback_rate"] == scene.get("playbackRate", 1)
                 and mapping["output_interval_seconds"] == [scene["fromFrame"] / 30, scene["toFrameExclusive"] / 30],
                 "Opening source interval differs from registered hook plan")


def verify_controlled_opening(context, candidate_a, candidate_b):
    """No context/claim alone authorizes the controlled-experiment exception.

    Context: root, experiment_ref, candidate_evidence_refs keyed by candidate ID.
    Each evidence document locks current props/mix/record/render and hook refs.
    """
    result = {"status": "not_run", "issues": ["verified_opening_context_missing"],
              "human_independent_work_review_required": True, "counts_as_new_work": False}
    if not context:
        return result
    try:
        from lib.opening_contracts import verify_opening_experiment_files
        root = Path(context["root"])
        _require(candidate_a != candidate_b and "B0" in (candidate_a, candidate_b), "Direct B0 comparison required")
        experiment, _ = verify_opening_experiment_files(root, context["experiment_ref"])
        registered = {row["candidate_id"]: row["hook_plan_ref"] for row in experiment["candidates"]}
        _require(candidate_a in registered and candidate_b in registered, "Unregistered opening candidate")
        descriptor = _load(root, experiment["frozen_body_ref"])
        _require(descriptor["identity"]["sku"] == experiment["sku"], "Freeze SKU mismatch")
        for role, key in (("facts", "facts_ref"), ("brand", "brand_ref")):
            _require(all(descriptor["dependencies"][role][k] == experiment[key][k] for k in ("path", "sha256")), "Experiment freeze identity dependency mismatch")
        approval = _load(root, descriptor["baseline_approval_ref"])
        _require(approval["production_subject"]["record_path"] == experiment["baseline_ref"]["path"], "Registered baseline differs from approved B0")
        approved_images = {(ref["path"], ref["sha256"]) for ref in _reference_pool(root, descriptor)}
        contents, render_hashes = [], []
        for candidate in (candidate_a, candidate_b):
            evidence = _load(root, context["candidate_evidence_refs"][candidate])
            _walk_refs(root, evidence)
            _require(evidence.get("version") == "1.0" and evidence.get("candidate_id") == candidate, "Candidate evidence identity mismatch")
            _require(evidence["experiment_ref"] == context["experiment_ref"] and evidence["freeze_ref"] == experiment["frozen_body_ref"]
                     and evidence["hook_plan_ref"] == registered[candidate], "Candidate registration lock mismatch")
            record = _load(root, evidence["production_record_ref"])
            _require(isinstance(record.get("content_slot_id"), str) and record["content_slot_id"].strip() and record.get("sku") == experiment["sku"], "Current record identity mismatch")
            _require(record["canonical_artifacts"]["final_props"] == evidence["candidate_props_ref"]["path"]
                     and all(record["render"][k] == evidence["media_ref"][k] for k in ("path", "sha256")), "Candidate render/props binding mismatch")
            if candidate == "B0":
                _require(record["content_slot_id"] == descriptor["baseline_slot_id"]
                         and evidence["production_record_ref"]["path"] == experiment["baseline_ref"]["path"], "Registered B0 actual slot mapping mismatch")
            else:
                _require(record["content_slot_id"] != descriptor["baseline_slot_id"], "Baseline and candidate slots must be unique")
                opening = record["opening"]
                _require(opening.get("scope") == "full_variant" and opening.get("candidate_id") == candidate
                         and opening["experiment_ref"] == context["experiment_ref"] and opening["hook_plan_ref"] == registered[candidate], "Current full record registration mismatch")
            proof = verify_frozen_body(root, descriptor_ref=evidence["freeze_ref"], candidate_props_ref=evidence["candidate_props_ref"],
                                       candidate_mix_plan_ref=evidence["candidate_mix_plan_ref"])
            _require(proof["status"] == "pass", "Actual frozen body not verified: " + ";".join(proof["issues"]))
            render_hashes.append(evidence["media_ref"]["sha256"])
            props = _load(root, evidence["candidate_props_ref"])
            plan = read_object(root, registered[candidate]["path"])
            for shot in plan["shots"]:
                for image in shot["asset_identity"].get("reference_images", []):
                    _require((image["path"], image["sha256"]) in approved_images, "Hook reference outside approved SKU pool/boundaries")
            _plan_sources_match(root, props, plan)
            contents.append(_content(root, props))
        _require(render_hashes[0] != render_hashes[1], "Exact duplicate rendered media cannot use opening exception")
        _require(contents[0] != contents[1], "Cosmetic/file-only difference is not new creative content")
        return {**result, "status": "pass", "issues": [], "experiment_id": experiment["experiment_id"], "sku": experiment["sku"],
                "registration_ref": context["experiment_ref"]["path"], "opening_input_difference": True, "rendered_difference_status": "not_run", "perceptual_difference_status": "not_run",
                "semantic_uniqueness_verified": False}
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as exc:
        return {**result, "status": "error", "issues": [exc.message if isinstance(exc, ValidationError) else str(exc)]}

"""Read-only review identity resolved from the canonical opening registration."""
from lib.production_evidence import read_object


def opening_review_scope(root, record):
    artifacts = record.get("canonical_artifacts") or {}
    props_path = artifacts.get("final_props") if isinstance(artifacts, dict) else None
    props = read_object(root, props_path) if props_path else {}
    props_opening = props.get("opening") if isinstance(props, dict) else None
    record_opening = record.get("opening")
    if props_opening is not None:
        if (not isinstance(props_opening, dict) or not isinstance(record_opening, dict)
                or record_opening.get("scope") != props_opening.get("scope")):
            raise ValueError("Canonical opening props require a matching registered production opening scope")
    elif "opening" in record and props_path is not None:
        raise ValueError("Registered production opening has no canonical opening props")
    if "opening" not in record:
        return None
    from schemas.artifacts import validate_artifact
    from lib.opening_contracts import validate_opening_semantics, verify_opening_experiment_files
    opening = record["opening"]
    validate_artifact("production_record", record)
    validate_opening_semantics("production_record", {"opening": opening})
    experiment, _ = verify_opening_experiment_files(root, opening["experiment_ref"], allow_planning=True)
    registered = next((c for c in experiment["candidates"] if c["candidate_id"] == opening["candidate_id"]), None)
    if not registered or registered["hook_plan_ref"] != opening["hook_plan_ref"] or record.get("sku") != experiment["sku"]:
        raise ValueError("Opening candidate registration or SKU mismatch")
    plan = read_object(root, opening["hook_plan_ref"]["path"])
    if props_path is not None:
        from lib.opening_experiment_evidence import _plan_sources_match
        _plan_sources_match(root, props, plan)
    return {"id": experiment["experiment_id"] + "@" + opening["experiment_ref"]["sha256"],
            "experiment_id": experiment["experiment_id"], "sku": experiment["sku"],
            "candidate_id": opening["candidate_id"], "role": "baseline" if opening["candidate_id"] == "B0" else "variant",
            "scope": opening["scope"], "experiment_ref": opening["experiment_ref"],
            "hook_plan_ref": opening["hook_plan_ref"], "baseline_record_path": experiment.get("baseline_ref", {}).get("path"),
            "shots": [{"shot_id": str(shot.get("shot_id") or shot.get("id") or ""),
                       "source_kind": str((shot.get("asset_identity") or {}).get("kind") or ""),
                       "source_path": str(((shot.get("asset_identity") or {}).get("source") or {}).get("path") or ""),
                       "source_interval_seconds": (shot.get("source_mapping") or {}).get("source_interval_seconds"),
                       "motion_verb": str((shot.get("motion") or {}).get("verb") or "")}
                      for shot in plan["shots"]]}

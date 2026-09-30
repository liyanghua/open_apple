"""Resolve controlled-opening authority from canonical project files only.

artifacts/opening_batch_context.json is a version 1.0 reference manifest with
experiment_ref and candidate_evidence_refs; root is always the owning project.
Every exception is reverified against B0, current media and the approved body.
"""
from jsonschema import ValidationError
from pathlib import Path
from lib.production_evidence import (read_object, project_file, file_sha256,
                                     build_production_subject, production_subject_hash)
from lib.opening_experiment_evidence import verify_controlled_opening


def _selected_child_matches(context, candidate_id, selected_child_dir):
    """The selected child's current record and props must be the verified candidate."""
    root = Path(context["root"])
    child = Path(selected_child_dir)
    evidence = read_object(root, context["candidate_evidence_refs"][candidate_id]["path"])
    canonical_record = read_object(root, evidence["production_record_ref"]["path"])
    slot = canonical_record["content_slot_id"]
    index = read_object(child, "artifacts/production_review_index.json")
    rows = [row for row in index.get("items", []) if isinstance(row, dict) and row.get("id") == slot]
    if len(rows) != 1:
        return False
    current_record_path = rows[0]["record_path"]
    current = read_object(child, current_record_path)
    if current.get("content_slot_id") != slot or current.get("sku") != canonical_record.get("sku"):
        return False
    if current.get("render", {}).get("sha256") != evidence["media_ref"]["sha256"]:
        return False
    if file_sha256(project_file(child, "artifacts/final_props.json")) != evidence["candidate_props_ref"]["sha256"]:
        return False
    child_subject = build_production_subject(child, current_record_path)
    canonical_subject = build_production_subject(root, evidence["production_record_ref"]["path"])
    return production_subject_hash(child_subject) == production_subject_hash(canonical_subject)


def resolve_opening_context(project_dir, candidate_id, *, selected_child_dir=None):
    try:
        manifest = read_object(project_dir, "artifacts/opening_batch_context.json")
        if set(manifest) != {"version", "experiment_ref", "candidate_evidence_refs"} or manifest["version"] != "1.0":
            return None
        context = {"root": project_dir, "experiment_ref": manifest["experiment_ref"],
                   "candidate_evidence_refs": manifest["candidate_evidence_refs"]}
        variants = [candidate_id] if candidate_id != "B0" else [c for c in context["candidate_evidence_refs"] if c != "B0"]
        if (any(verify_controlled_opening(context, "B0", variant)["status"] == "pass" for variant in variants)
                and (selected_child_dir is None or _selected_child_matches(context, candidate_id, selected_child_dir))):
            return context
    except (ValueError, OSError, KeyError, TypeError, ValidationError):
        pass
    return None


def compare_batch_pairs(plans, contexts):
    """Registered siblings compare with B0; exact sibling duplicates still fail."""
    from lib.candidate_diversity import compare_candidate_pair
    results = []
    ids = sorted(plans)
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            left_context, right_context = contexts.get(left), contexts.get(right)
            context = left_context if (left_context and right_context
                and Path(left_context["root"]).resolve() == Path(right_context["root"]).resolve()
                and left_context["experiment_ref"] == right_context["experiment_ref"]) else None
            if left != "B0" and right != "B0" and context:
                a = verify_controlled_opening(context, "B0", left)
                b = verify_controlled_opening(context, "B0", right)
                if a["status"] == b["status"] == "pass":
                    refs = context["candidate_evidence_refs"]
                    ma = read_object(context["root"], refs[left]["path"])["media_ref"]["sha256"]
                    mb = read_object(context["root"], refs[right]["path"])["media_ref"]["sha256"]
                    if ma != mb:
                        continue
                    result = compare_candidate_pair(plans[left], plans[right])
                    result.update(passes=False, duplicate_media=True)
                    results.append(result)
                    continue
            results.append(compare_candidate_pair(plans[left], plans[right], opening_context=context))
    return results

"""Resolve controlled-opening authority from canonical project files only.

artifacts/opening_batch_context.json is a version 1.0 reference manifest with
experiment_ref and candidate_evidence_refs; root is always the owning project.
Every exception is reverified against B0, current media and the approved body.
"""
from jsonschema import ValidationError
from lib.production_evidence import read_object
from lib.opening_experiment_evidence import verify_controlled_opening


def resolve_opening_context(project_dir, candidate_id):
    try:
        manifest = read_object(project_dir, "artifacts/opening_batch_context.json")
        if set(manifest) != {"version", "experiment_ref", "candidate_evidence_refs"} or manifest["version"] != "1.0":
            return None
        context = {"root": project_dir, "experiment_ref": manifest["experiment_ref"],
                   "candidate_evidence_refs": manifest["candidate_evidence_refs"]}
        variants = [candidate_id] if candidate_id != "B0" else [c for c in context["candidate_evidence_refs"] if c != "B0"]
        if any(verify_controlled_opening(context, "B0", variant)["status"] == "pass" for variant in variants):
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
            context = contexts.get(left) or contexts.get(right)
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

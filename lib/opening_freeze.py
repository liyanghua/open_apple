"""File-bound frozen-body evidence; no creative decisions or approval creation.

[0, 90) is variable at 30 fps. Deterministic body inputs and pre-encode PCM
are the freeze gate. Decoded compressed output is a separate observation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import wave
from pathlib import Path
from typing import Mapping
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from lib.final_props import validate_final_props
from lib.production_evidence import (file_sha256, project_file, read_object,
    production_subject_hash, quality_summary, verify_production_subject)

BOUNDARY = 90
REQUIRED_DEPENDENCIES = {"facts", "reference", "brand", "renderer", "mix_plan"}
METADATA = {"version", "project_id", "created_at", "producer", "input_hashes", "semantic_sha256", "artifact_sha256"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ref(root, ref):
    _require(isinstance(ref, Mapping), "Expected file-bound reference")
    path = project_file(root, ref.get("path"))
    _require(file_sha256(path) == ref.get("sha256"), f"Dependency hash mismatch: {ref.get('path')}")
    return path


def _walk_refs(root, value, _visited=None):
    """Recheck declared references transitively, including dependency manifests."""
    visited = set() if _visited is None else _visited
    if isinstance(value, Mapping):
        if "path" in value and "sha256" in value:
            path = _ref(root, value)
            key = (value["path"], value["sha256"])
            if key not in visited:
                visited.add(key)
                if path.suffix.lower() == ".json":
                    _walk_refs(root, read_object(root, value["path"]), visited)
        for child in value.values():
            _walk_refs(root, child, visited)
    elif isinstance(value, list):
        for child in value:
            _walk_refs(root, child, visited)
    return visited


def _load(root, ref):
    _ref(root, ref)
    return read_object(root, ref["path"])


def _pcm(root, ref, total):
    """Read actual uncompressed integer WAV; compare native samples without resampling."""
    path = _ref(root, ref)
    try:
        with wave.open(str(path), "rb") as stream:
            _require(stream.getcomptype() == "NONE", "Lossless preencode PCM required")
            rate, count = stream.getframerate(), stream.getnframes()
            _require(rate > 0 and count * 30 == total * rate, "PCM must cover the exact full film duration")
            start = rate * 3
            _require(count > start, "PCM must cover the body after 3 seconds")
            stream.setpos(start)
            digest = hashlib.sha256()
            byte_count = 0
            while chunk := stream.readframes(65536):
                digest.update(chunk)
                byte_count += len(chunk)
            _require(byte_count == (count - start) * stream.getnchannels() * stream.getsampwidth(), "Truncated PCM")
            return {"channels": stream.getnchannels(), "sample_width": stream.getsampwidth(),
                    "sample_rate": rate, "body_samples": count - start, "body_sha256": digest.hexdigest()}
    except EOFError as exc:
        raise ValueError("Truncated preencode PCM WAV") from exc

def _timed_body(rows, start_key="startMs", end_key="endMs"):
    # Preserve the start as well: a cross-boundary overlay/word cannot be
    # changed by classifying it as an opening-only item.
    return [copy.deepcopy(row) for row in rows if row[end_key] > 3000]


def _reference_pool(root, descriptor):
    pool = _load(root, descriptor["dependencies"]["reference"])
    _require(pool.get("version") == "1.0" and pool.get("sku") == descriptor["identity"]["sku"], "Approved reference pool SKU mismatch")
    _require(pool.get("reference_boundaries") == descriptor["identity"]["reference_boundaries"], "Approved reference boundaries mismatch")
    images = pool.get("reference_images")
    _require(isinstance(images, list) and images, "Explicit approved reference pool required")
    for image in images:
        _require(isinstance(image, Mapping) and set(image) == {"path", "sha256"}, "Typed approved image reference required")
        _ref(root, image)
    return images


def _mix_body(root, mix, output_ref):
    _require(mix.get("scope") == "full_variant" and mix.get("source_kind") == "raw_plus_common_body",
             "Full film mix must be built from raw sources and common body, never a faded preview")
    _require(isinstance(mix.get("raw_refs"), list) and mix["raw_refs"], "Raw mix dependencies required")
    for ref in mix["raw_refs"]:
        _require(isinstance(ref, Mapping) and set(ref) == {"path", "sha256"}, "Raw source must be a typed current file reference")
        path = _ref(root, ref)
        if path.suffix.lower() == ".json":
            source = read_object(root, ref["path"])
            _require(source.get("scope") not in ("preview", "full_variant") and source.get("source_kind") not in ("preview_tail_fade", "raw_plus_common_body"),
                     "Derived preview/full mix cannot be a raw source")
    _walk_refs(root, mix)
    _require(mix.get("output_ref") == {k: output_ref[k] for k in ("path", "sha256")}, "Mix provenance output must bind current preencode PCM")
    if mix.get("source_provenance_ref"):
        provenance = _load(root, mix["source_provenance_ref"])
        _walk_refs(root, provenance)
        _require(provenance.get("scope") == "source" and provenance.get("source_kind") == "raw_audio", "Preview/derived or unsupported source provenance")
        media = provenance.get("media_ref")
        _require(isinstance(media, Mapping) and set(media) == {"path", "sha256"} and media in mix["raw_refs"], "Source provenance media binding mismatch")
    _require(isinstance(mix.get("bgm"), Mapping) and all(k in mix["bgm"] for k in ("track_ref", "position_seconds", "mix_rules")), "BGM track, fixed position and mix rules required")
    return {"narration_segments": _timed_body(mix["narration_segments"]), "bgm": mix["bgm"]}


def _body(root, props):
    _walk_refs(root, props)
    validate_final_props(props, project_dir=Path(root))
    _require(props.get("opening") == {"scope": "full_variant", "endFrameExclusive": 90, "transitionFrames": 5}, "Full opening scope required")
    _require(props.get("fps") == 30 and props["durationInFrames"] > 90, "Full 30fps film required")
    _require(props.get("profile", {}).get("production", {}).get("font_mode") == "strict", "Full variant needs strict brand profile")
    _require(props["profile"]["production"].get("transition") == {"frames": 5, "rule": "incoming_only"}, "Common transition must finish in [85,90)")
    scenes = [copy.deepcopy(s) for s in props["scenes"] if s["toFrameExclusive"] > 90]
    _require(scenes and scenes[0]["fromFrame"] == 90, "Canonical body must start at frame 90")
    rate = scenes[0].get("playbackRate", 1)
    prehandle = 5 * rate
    _require(float(prehandle).is_integer() and int(scenes[0]["sourceInSeconds"] * 30 + .5) >= prehandle,
             "Insufficient compatible source prehandle for [85,90)")
    footage = {}
    static_assets = {}
    if props.get("logoSrc"):
        static_assets["logo"] = file_sha256(project_file(root, "public/" + props["logoSrc"]))
    for font in props.get("profile", {}).get("font", {}).get("files", []):
        static_assets[font["src"]] = file_sha256(project_file(root, font["path"]))
        _require(static_assets[font["src"]] == font["sha256"], "Pinned font bytes mismatch")
    def sources(scene):
        key = scene["footageKey"]
        relative = props["footage"][key]
        footage[key] = file_sha256(project_file(root, "public/" + relative))
        for sub in scene.get("segments", []):
            sources(sub)
    for scene in scenes:
        sources(scene)
    titles = props.get("titles", [])
    active_index = max((index for index, row in enumerate(titles) if row["fromFrame"] <= 90), default=-1)
    # Renderer precedence follows array order, even for unsorted timestamps.
    body_titles = [copy.deepcopy(row) for index, row in enumerate(titles)
                   if index == active_index or row["fromFrame"] > 90]
    excluded = METADATA | {"scenes", "footage", "titles", "captions", "words", "opening", "finalMix"}
    # Unknown render globals are frozen conservatively, not silently ignored.
    return {"globals": {k: v for k, v in props.items() if k not in excluded}, "scenes": scenes,
            "media_sha256": footage, "static_assets": static_assets, "titles": body_titles, "captions": _timed_body(props.get("captions", [])),
            "words": _timed_body(props.get("words", []))}


def _approval(root, descriptor):
    approval = _load(root, descriptor["baseline_approval_ref"])
    schema = json.loads((Path(__file__).parents[1] / "schemas/backlot/operator_review.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(approval)
    expected = f"operator/reviews/{approval['review_id']}.json"
    _require(descriptor["baseline_approval_ref"]["path"] == expected, "Actual registered operator review required")
    _require(approval.get("decided_at") and datetime.fromisoformat(approval["decided_at"].replace("Z", "+00:00")).tzinfo is not None,
             "Identified timestamped B0 approval required")
    # A later rejection/supersession must invalidate an older approved review.
    slot = approval.get("production_subject", {}).get("content_slot_id")
    reviews = []
    for path in (Path(root) / "operator/reviews").glob("*.json"):
        try:
            item = json.loads(path.read_text())
            if item.get("kind") == "final_review" and item.get("subject_id") == slot:
                reviews.append(item)
        except (ValueError, OSError, AttributeError):
            continue
    latest = max(reviews, key=lambda r: (r.get("subject_version", 0), r.get("created_at", "")), default={})
    _require(latest == approval, "B0 final review superseded")
    subject = approval.get("production_subject", {})
    _require(approval.get("kind") == "final_review" and approval.get("status") == "approved"
             and isinstance(approval.get("decided_by"), str) and approval["decided_by"].strip(), "Approved operator final review required")
    _require(approval.get("subject_id") == subject.get("content_slot_id") == descriptor.get("baseline_slot_id")
             and descriptor.get("baseline_candidate_id") == "B0", "Approved B0 slot mapping mismatch")
    _require(approval.get("subject_hash") == production_subject_hash(subject) and verify_production_subject(root, subject), "Stale B0 approval")
    record = read_object(root, subject["record_path"])
    opening = record.get("opening", {})
    _require(opening.get("scope") == "full_variant" and opening.get("candidate_id") == "B0", "Actual B0 full preparation record required")
    from lib.opening_contracts import verify_opening_experiment_files
    preparation, _ = verify_opening_experiment_files(root, opening["experiment_ref"])
    registered = next((row for row in preparation["candidates"] if row["candidate_id"] == "B0"), None)
    _require(registered and registered["hook_plan_ref"] == opening["hook_plan_ref"], "Actual B0 preparation registration mismatch")
    identity = _load(root, preparation["baseline_ref"])
    _require(set(identity) == {"version", "role", "sku", "candidate_id", "content_slot_id"}
             and identity.get("version") == "1.0" and identity.get("role") == "baseline_preparation"
             and identity.get("sku") == record.get("sku") == preparation["sku"]
             and identity.get("candidate_id") == "B0" and identity.get("content_slot_id") == slot == record.get("content_slot_id"),
             "File-bound B0 preparation identity mismatch")
    _require(quality_summary(root, record)["eligible"], "B0 quality checks incomplete")
    bound = {(v["path"], v["sha256"]) for v in subject["dependencies"].values()}
    preparation_inputs = [opening["experiment_ref"], opening["hook_plan_ref"]]
    def add_refs(value):
        if isinstance(value, Mapping):
            if "path" in value and "sha256" in value:
                preparation_inputs.append(value)
            for child in value.values():
                add_refs(child)
        elif isinstance(value, list):
            for child in value:
                add_refs(child)
    add_refs(preparation)
    add_refs(_load(root, opening["hook_plan_ref"]))
    transitive = [{"path": path, "sha256": sha} for path, sha in _walk_refs(root, descriptor["dependencies"])]
    for ref in [descriptor["baseline_props_ref"], *descriptor["dependencies"].values(), *preparation_inputs, *transitive]:
        _require((ref["path"], ref["sha256"]) in bound, "B0 approval missing freeze dependency")
    _require(record.get("sku") == descriptor["identity"]["sku"], "B0 SKU mismatch")
    facts = _load(root, descriptor["dependencies"]["facts"])
    _require(facts.get("sku") == descriptor["identity"]["sku"], "Frozen facts SKU mismatch")
    if "version" in facts:
        _require(facts["version"] == descriptor["identity"]["fact_version"], "Frozen fact version mismatch")
    brand = _load(root, descriptor["dependencies"]["brand"])
    if "profile_id" in brand:
        _require(brand["profile_id"] == descriptor["identity"]["brand_profile"], "Frozen brand profile mismatch")
    props = _load(root, descriptor["baseline_props_ref"])
    # Every concrete render input must occur in the approved production graph.
    sources = [props["finalMix"], *_reference_pool(root, descriptor)]
    sources += [{"path": "public/" + name, "sha256": file_sha256(project_file(root, "public/" + name))}
                for name in props["footage"].values()]
    if props.get("logoSrc"):
        name = "public/" + props["logoSrc"]
        sources.append({"path": name, "sha256": file_sha256(project_file(root, name))})
    for font in props.get("profile", {}).get("font", {}).get("files", []):
        sources.append({"path": font["path"], "sha256": font["sha256"]})
    for source in sources:
        _require((source["path"], source["sha256"]) in bound, "B0 approval missing actual render input")
    return record


def create_pending_freeze_descriptor(root, *, identity, dependencies):
    """Preview registration before B0 exists; this document grants no exception."""
    _require({"facts", "reference", "brand", "renderer"} <= dependencies.keys(), "Missing pending identity dependencies")
    _require(set(identity) == {"sku", "fact_version", "reference_boundaries", "brand_profile"}, "Complete frozen identity required")
    _walk_refs(root, dependencies)
    _reference_pool(root, {"identity": identity, "dependencies": dependencies})
    return {"version": "1.0", "state": "pending", "identity": copy.deepcopy(identity), "dependencies": copy.deepcopy(dependencies)}


def create_freeze_descriptor(root, *, baseline_props_ref, identity, dependencies, baseline_approval_ref=None):
    """Return a descriptor for persistence; missing B0 approval means pending.

    Never rewrite B0 preparation documents to point to this new descriptor.
    Publish a new experiment version only after B0 review is complete.
    """
    _require(REQUIRED_DEPENDENCIES <= dependencies.keys(), "Missing freeze dependencies")
    _require(set(identity) == {"sku", "fact_version", "reference_boundaries", "brand_profile"}, "Complete frozen identity required")
    props = _load(root, baseline_props_ref)
    _reference_pool(root, {"identity": identity, "dependencies": dependencies})
    _walk_refs(root, dependencies)
    descriptor = {"version": "1.0", "state": "approved" if baseline_approval_ref else "pending",
        "identity": copy.deepcopy(identity), "baseline_props_ref": dict(baseline_props_ref),
        "dependencies": copy.deepcopy(dependencies), "body": _body(root, props),
        "mix_body": _mix_body(root, _load(root, dependencies["mix_plan"]), props["finalMix"]),
        "pcm": _pcm(root, props["finalMix"], props["durationInFrames"])}
    if baseline_approval_ref:
        descriptor["baseline_approval_ref"] = dict(baseline_approval_ref)
        approved = _load(root, baseline_approval_ref)
        descriptor["baseline_candidate_id"] = "B0"
        descriptor["baseline_slot_id"] = approved.get("production_subject", {}).get("content_slot_id")
        _approval(root, descriptor)
    return descriptor


def verify_frozen_body(root, *, descriptor_ref, candidate_props_ref, candidate_mix_plan_ref):
    """Recompute everything from current files; no persisted pass is trusted."""
    evidence = [descriptor_ref.get("path"), candidate_props_ref.get("path"), candidate_mix_plan_ref.get("path")]
    try:
        descriptor = _load(root, descriptor_ref)
        _require(descriptor.get("version") == "1.0", "Unsupported freeze descriptor")
        _walk_refs(root, descriptor)
        if descriptor.get("state") == "pending" or not descriptor.get("baseline_approval_ref"):
            return {"status": "not_run", "issues": ["approved_B0_missing"], "evidence_refs": evidence}
        _require(descriptor.get("state") == "approved", "Unknown freeze state")
        _approval(root, descriptor)
        baseline = _load(root, descriptor["baseline_props_ref"])
        actual_body = _body(root, baseline)
        actual_pcm = _pcm(root, baseline["finalMix"], baseline["durationInFrames"])
        actual_mix = _mix_body(root, _load(root, descriptor["dependencies"]["mix_plan"]), baseline["finalMix"])
        _require(descriptor["body"] == actual_body and descriptor["pcm"] == actual_pcm and descriptor["mix_body"] == actual_mix,
                 "Freeze descriptor does not match approved B0")
        candidate = _load(root, candidate_props_ref)
        try:
            body = _body(root, candidate)
            mix = _mix_body(root, _load(root, candidate_mix_plan_ref), candidate["finalMix"])
            pcm = _pcm(root, candidate["finalMix"], candidate["durationInFrames"])
        except (ValueError, wave.Error) as exc:
            return {"status": "fail", "issues": [str(exc)], "evidence_refs": evidence}
        issues = []
        if body != actual_body: issues.append("frozen_body_render_inputs_changed")
        if mix != actual_mix: issues.append("frozen_body_audio_rules_changed")
        if pcm != actual_pcm: issues.append("frozen_body_PCM_changed")
        return {"status": "fail" if issues else "pass", "issues": issues, "evidence_refs": sorted(set(evidence)),
            "method": "deterministic_body_inputs_and_preencode_PCM", "body_interval_frames": [90, candidate["durationInFrames"]],
            "pcm": pcm, "semantic_continuity_verified": False, "source_provenance_status": "not_run"}
    except (ValidationError, ValueError, OSError, KeyError, TypeError, wave.Error) as exc:
        return {"status": "error", "issues": [exc.message if isinstance(exc, ValidationError) else str(exc)], "evidence_refs": evidence}


def verify_opening_join(root, *, media_ref, duration_frames):
    """Produce actual [2.5,3.5] decode evidence. Persist the returned document.

    This is the explicit heavyweight producer. Read-side adapters only check
    this file's measured structure, dependency bindings and current hashes.
    """
    from lib.media_fingerprint import decoded_interval_evidence
    try:
        path = _ref(root, media_ref)
        _require(isinstance(duration_frames, int) and 105 <= duration_frames <= 18000, "Full film must cover join interval")
        try:
            measurement = decoded_interval_evidence(path, start_frame=75, end_frame=105, audio=True)
            _require(measurement["total_video_frames"] == duration_frames, "Full duration frame count mismatch")
            _require(abs(measurement["duration_seconds"] - duration_frames / 30) <= 1 / 30, "Full media duration mismatch")
        except (ValueError, KeyError, StopIteration) as exc:
            return {"status": "fail", "issues": [str(exc)], "media_ref": dict(media_ref), "semantic_continuity_status": "not_run"}
        return {"version": "1.0", "status": "pass", "method": "actual_opening_join_decode", "issues": [],
            "media_ref": dict(media_ref), "duration_frames": duration_frames, "measurement": measurement,
            "semantic_continuity_status": "not_run", "continuous_audibility_verified": False}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"status": "error", "issues": [str(exc)], "semantic_continuity_status": "not_run"}


def evaluate_freeze_checks(root, record):
    """Read-side adapter; see opening_freeze_checks for manifest binding."""
    from lib.opening_freeze_checks import evaluate_freeze_checks as evaluate
    return evaluate(root, record)

"""Read-only checks for an approved, paid dynamic-opening first article.

The agent chooses the visual idea and edit. This module checks that the paid
request, returned source, three-second preview, and technical report still
belong to the same approved version. It never submits a task or grants review.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Mapping

from lib.production_evidence import file_sha256, project_file, read_object


class PilotEvidenceError(ValueError):
    """A pilot cannot be linked to its approved inputs or current output."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PilotEvidenceError(message)


def _bound_json(root: Path, ref: Mapping[str, str]) -> dict[str, Any]:
    path = project_file(root, ref["path"])
    _require(file_sha256(path) == ref["sha256"], f"Changed pilot evidence: {ref['path']}")
    return read_object(root, ref["path"])


def _bound_file(root: Path, ref: Mapping[str, str]) -> Path:
    path = project_file(root, ref["path"])
    _require(file_sha256(path) == ref["sha256"], f"Changed pilot media: {ref['path']}")
    return path


def _absolute_project_file(root: Path, value: str) -> Path:
    path = Path(value).resolve()
    _require(path.is_file() and path.is_relative_to(root.resolve()), "Pilot path is missing or outside project")
    return path


def validate_generation_gate(root: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    """Check approved scope and exact paid-call inputs before submitting a task.

    ``packet`` contains ``approval_ref``, ``lock_ref`` and ``items``. Each item
    has a ``slot_id`` and ``generation_inputs_ref``. Paths in refs are project
    relative and SHA-256 bound; generation input paths remain the exact paths
    passed to the tool. The caller is responsible for tool preflight, budget
    reservation and provider availability.
    """
    root = Path(root).resolve()
    approval = _bound_json(root, packet["approval_ref"])
    lock = _bound_json(root, packet["lock_ref"])
    items = packet["items"]
    _require(isinstance(items, list) and bool(items), "Pilot has no generation items")
    _require(approval.get("approved_by") and str(approval.get("status", "")).startswith("approved"),
             "Pilot has no explicit creative approval")
    _require(approval.get("final_film_approval") is not True,
             "Pilot approval cannot also claim final-film approval")
    _require(lock.get("status") == "locked_for_pilot_source_generation", "Pilot production lock is not active")
    _require(lock.get("tool") and lock.get("provider") and lock.get("model"),
             "Pilot tool, provider and model are not pinned")
    _require(lock.get("approval_ref") == packet["approval_ref"]["path"]
             and lock.get("approval_sha256") == packet["approval_ref"]["sha256"],
             "Pilot lock does not bind the current approval")
    allowed = set(approval.get("scope") or [])
    slots = [row["slot_id"] for row in items]
    _require(len(slots) == len(set(slots)) and set(slots) <= allowed, "Pilot slots exceed approved scope")
    cap = min(int(approval.get("max_paid_submissions") or 0), int(lock.get("max_paid_submissions") or 0))
    _require(cap >= len(items), "Pilot exceeds approved paid-submission count")
    _require(set(lock.get("scope") or []) == allowed, "Pilot lock and approval scope differ")
    references = {(_bound_file(root, ref).resolve(), ref["sha256"])
                  for ref in lock.get("reference_images") or []}
    _require(bool(references), "Pilot has no pinned product reference")
    seen_keys: set[str] = set()
    seen_outputs: set[str] = set()
    ledger_path: Path | None = None
    native_mode: bool | None = None
    seen_reservations: set[str] = set()
    verified = []
    for row in items:
        inputs = _bound_json(root, row["generation_inputs_ref"])
        for name, locked in (("model", "model"), ("model_variant", "model_variant"),
                             ("operation", "operation"), ("duration", "source_duration_seconds"),
                             ("resolution", "source_resolution"), ("aspect_ratio", "source_ratio"),
                             ("generate_audio", "generate_audio")):
            _require(inputs.get(name) == lock.get(locked), f"{row['slot_id']}: {name} differs from lock")
        _require(inputs.get("task_action") == "generate", "Pilot input is not a generation request")
        native = bool(inputs.get("parent_budget_id") or str(inputs.get("reservation_id", "")).startswith("native_"))
        _require(native_mode is None or native == native_mode, "Pilot cannot mix native and legacy ledgers")
        native_mode = native
        _require(inputs.get("idempotency_key") and inputs.get("reservation_id")
                 and (native or inputs.get("cost_log_path")) and inputs.get("task_journal_path"),
                 "Pilot lacks reservation, journal or idempotency key")
        if native:
            _require(all(inputs.get(key) for key in ("project_dir", "parent_budget_id", "shot_id", "lineage_id")),
                     "Pilot native budget lacks parent, shot or lineage identity")
            _require(Path(inputs["project_dir"]).resolve() == root, "Pilot native parent budget project differs")
            for name in ("parent_budget_id", "shot_id", "lineage_id"):
                plan = inputs.get("shot_source_plan")
                locked_identity = (inputs.get(name) == lock[name] if name in lock else (
                    isinstance(plan, Mapping) and plan.get(name) == inputs.get(name)
                    and (plan.get('dependencies') or {}).get('production_lock') == packet['lock_ref']))
                _require(locked_identity,
                    f"Pilot native {name} differs from production lock or source plan")
            canonical = root / "artifacts/budgets/generation.json"
            declared = Path(inputs.get("cost_log_path") or canonical)
            _require(declared.resolve() == canonical, "Pilot native budget requires the canonical ledger")
            current_ledger = _absolute_project_file(root, str(canonical))
        else:
            current_ledger = _absolute_project_file(root, inputs["cost_log_path"])
        _require(ledger_path is None or current_ledger == ledger_path,
                 "Pilot items use different cost ledgers")
        ledger_path = current_ledger
        key = str(inputs["idempotency_key"])
        output = str(inputs.get("output_path") or "")
        _require(bool(output) and Path(output).resolve().is_relative_to(root),
                 "Pilot output path is outside project")
        _require(key not in seen_keys and output and output not in seen_outputs,
                 "Pilot would duplicate a paid attempt or overwrite another source")
        seen_keys.add(key)
        seen_outputs.add(output)
        _require(inputs["reservation_id"] not in seen_reservations, "Pilot would duplicate a paid reservation")
        seen_reservations.add(inputs["reservation_id"])
        selected = {(_absolute_project_file(root, path), file_sha256(Path(path)))
                    for path in inputs.get("reference_image_paths") or []}
        _require(selected == references, f"{row['slot_id']}: product references differ from lock")
        from lib.generation_references import preflight_generation_references
        reference_preflight = preflight_generation_references(root, inputs,
            reference_media=inputs.get("reference_media", lock.get("reference_media")),
            remote_availability=bool(inputs.get("require_remote_availability", False)),
            tool=lock["tool"], provider=lock["provider"])
        _require(reference_preflight["valid"],
                 f"{row['slot_id']}: reference provenance or authorization failed: "
                 + ', '.join(issue['code'] for issue in reference_preflight['issues']))
        verified.append({"slot_id": row["slot_id"], "model": inputs["model"],
                         "idempotency_key": key, "reservation_id": inputs["reservation_id"],
                         "source_output_path": output, "native_budget": native,
                         **{name: inputs.get(name) for name in ("parent_budget_id", "shot_id", "lineage_id",
                                                               "request_id", "revision_id")}})
    ledger = read_object(root, ledger_path.relative_to(root).as_posix())
    _require(ledger.get('ledger_kind') != 'native_generation' or native_mode,
             "Pilot native generation ledger requires explicit parent budget identity")
    entries = ledger.get("entries") or []
    _require(isinstance(entries, list) and (native_mode or len(entries) <= cap),
             "Pilot ledger exceeds approved paid-submission count")
    if native_mode:
        _require(ledger.get("ledger_kind") == "native_generation", "Pilot native ledger kind differs")
        try:
            from lib.generation_budget import GenerationBudgetLedger
            from lib.cost_persistence import ledger_lock
            # Validate one coherent read without opening the write transaction
            # used by CostTracker.snapshot_parent_budget.
            with ledger_lock(ledger_path), localcontext() as context:
                context.prec = 256
                ledger = read_object(root, ledger_path.relative_to(root).as_posix())
                store = GenerationBudgetLedger(root, declared_path=ledger_path)
                store.validate(ledger)
                entries = ledger['entries']
                for parent_id in {item['parent_budget_id'] for item in verified}:
                    parent = store.parent(ledger, parent_id)
                    snapshot = store.summary(ledger, parent)
                    _require(snapshot['paid_calls'] <= snapshot['max_paid_calls']
                             and Decimal(snapshot['remaining_amount']) >= 0,
                             "Pilot native parent budget exceeds its global amount or call limit")
        except (ValueError, KeyError, TypeError) as exc:
            raise PilotEvidenceError(f"Pilot native parent budget is invalid: {exc}") from exc
    for item in verified:
        matching = [entry for entry in entries if entry.get("id") == item["reservation_id"]]
        _require(len(matching) == 1, f"{item['slot_id']}: paid reservation differs from locked request")
        entry = matching[0]
        if native_mode:
            for name in ("parent_budget_id", "shot_id", "lineage_id", "request_id", "revision_id"):
                _require(item.get(name) is None or item[name] == entry.get(name),
                         f"{item['slot_id']}: native reservation {name} differs from locked request")
            item['provider_task_id'] = entry.get('provider_task_id')
        _require(entry.get("tool") == lock["tool"] and entry.get("operation") == lock["operation"],
                 f"{item['slot_id']}: paid reservation differs from locked request")
        bound_key = entry.get("idempotency_key")
        if bound_key is None:
            # The provider attempt is bound immediately before POST. A true
            # pre-payment gate must accept a reserved, unsubmitted entry.
            _require(entry.get("status") == "reserved"
                     and entry.get("submission_status") in (None, "not_submitted")
                     and not entry.get("provider_task_id"),
                     f"{item['slot_id']}: paid reservation differs from locked request")
        else:
            _require(bound_key == item["idempotency_key"],
                     f"{item['slot_id']}: paid reservation differs from locked request")
    return {"status": "ready", "provider": lock["provider"],
            "max_paid_submissions": cap, "items": verified}


def validate_preview_evidence(root: Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    """Bind completed sources, actual render and raw technical status.

    This validates identity and completeness, not visual appeal, product truth
    or final-film certification. An L1a ``revise`` remains ``revise``.
    """
    root = Path(root).resolve()
    gate = validate_generation_gate(root, packet)
    verified = []
    for row in packet["items"]:
        slot = row["slot_id"]
        inputs = _bound_json(root, row["generation_inputs_ref"])
        generation = _bound_json(root, row["generation_result_ref"])
        source = _bound_file(root, row["source_ref"])
        _require(generation.get("success") is True, f"{slot}: generation did not succeed")
        data = generation.get("data") or {}
        budget_item = next(item for item in gate['items'] if item['slot_id'] == slot)
        if budget_item.get('native_budget'):
            _require(budget_item.get('provider_task_id') == data.get('task_id'),
                     f"{slot}: native reservation task differs from generation receipt")
        _require(data.get("task_id") and data.get("model") == inputs["model"]
                 and data.get("operation") == inputs["operation"]
                 and str(data.get("provider", "")).casefold() == str(gate["provider"]).casefold(),
                 f"{slot}: task identity or model differs from request")
        _require(_absolute_project_file(root, data.get("output_path", "")) == source
                 and _absolute_project_file(root, inputs["output_path"]) == source,
                 f"{slot}: returned source differs from requested output")

        props = _bound_json(root, row["preview_props_ref"])
        render_inputs = _bound_json(root, row["render_inputs_ref"])
        _require(render_inputs.get("edit_decisions") == props,
                 f"{slot}: preview props differ from render submission")
        _require((props.get("opening") or {}).get("scope") == "preview"
                 and props.get("durationInFrames") == 90 and props.get("fps") == 30
                 and (props.get("width"), props.get("height")) == (1080, 1920),
                 f"{slot}: preview is not the registered three-second vertical opening")
        source_rel = source.relative_to(root).as_posix()
        _require(source_rel in (props.get("footage") or {}).values(),
                 f"{slot}: generated source is not in the rendered preview")
        for scene in props.get("scenes") or []:
            footage = (props.get("footage") or {}).get(scene.get("footageKey"))
            _require(footage is not None and file_sha256(project_file(root, footage)) == scene.get("asset_sha256"),
                     f"{slot}: preview scene source changed")

        preview = _bound_file(root, row["preview_ref"])
        render = _bound_json(root, row["render_result_ref"])
        _require(render.get("success") is True
                 and _absolute_project_file(root, (render.get("data") or {}).get("output", "")) == preview,
                 f"{slot}: render receipt differs from preview")
        renderer_ref = (render.get("data") or {}).get("renderer_props_ref")
        _require(isinstance(renderer_ref, dict), f"{slot}: actual renderer props are missing")
        rendered_props = _bound_json(root, renderer_ref)
        for key in ("profile", "scenes", "footage", "titles", "words", "captions",
                    "durationInFrames", "finalMix", "logoSrc", "opening", "fps", "width", "height"):
            _require(rendered_props.get(key) == props.get(key),
                     f"{slot}: actual renderer changed {key}")
        pins = rendered_props.get("render_input_refs") or []
        _require(isinstance(pins, list) and bool(pins), f"{slot}: renderer inputs are not pinned")
        pinned = {ref["path"] for ref in pins}
        required = set((props.get("footage") or {}).values())
        if props.get("logoSrc"):
            required.add(props["logoSrc"])
        if (props.get("finalMix") or {}).get("path"):
            required.add(props["finalMix"]["path"])
        _require(required <= pinned, f"{slot}: actual renderer pins omit media inputs")
        for ref in pins:
            _bound_file(root, ref)
        technical = _bound_json(root, row["technical_ref"])
        _require(technical.get("scope") == "preview"
                 and technical.get("subject_hash") == file_sha256(preview)
                 and technical.get("media_sha256") == file_sha256(preview),
                 f"{slot}: technical report is stale or for a different scope")
        verified.append({"slot_id": slot, "task_id": data["task_id"],
                         "source_sha256": file_sha256(source),
                         "preview_sha256": file_sha256(preview),
                         "technical_status": technical.get("status", "not_run"),
                         "catalog_estimate_cny": (data.get("catalog_estimate") or {}).get("amount"),
                         "actual_settlement": data.get("actual_cost")})
    return {"status": "ready_for_preview_review", "gate": gate, "items": verified,
            "final_film_approved": False}

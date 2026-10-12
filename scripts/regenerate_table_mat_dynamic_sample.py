#!/usr/bin/env python3
"""Generate an approved Seedance 2.0 dynamic candidate for table-mat-mix-v1.

This production runner keeps provider routing, cost reservation, prompt audit,
and output provenance together. It is intentionally project-scoped and does
not alter the approved narration or reference timeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.config_model import BudgetMode
from tools.cost_tracker import CostTracker
from tools.tool_registry import registry


PROJECT = ROOT / "projects" / "table-mat-mix-v1"
OUT_DIR = PROJECT / "assets" / "video" / "dynamic-candidates"
AUDIT_DIR = PROJECT / "analysis" / "dynamic-remake"
COST_LOG = PROJECT / "cost_log.json"

PRODUCT_REFS = [
    PROJECT / "inputs/reference/dynamic_anchors/product-clean-03.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/product-clean-04.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/product-clean-05.jpg",
]

MOTION_REFS = [
    PROJECT / "inputs/reference/dynamic_anchors/benchmark-flex.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/benchmark-wide.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/benchmark-pour.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/benchmark-wipe.jpg",
    PROJECT / "inputs/reference/dynamic_anchors/benchmark-edge.jpg",
]


BASE_PROMPT = """Montage, multi-shot premium e-commerce product demonstration, do not use one camera angle or a single continuous take. Photorealistic commercial footage, natural warm daylight, clean light-oak dining room, real human hands, accurate physics, subtle handheld micro-movement, shallow depth of field only in macro shots, crisp product detail, natural motion blur, soft highlight rolloff, no 3D, no cartoon, no surrealism, no generated text, no logo, no watermark.

[identity_lock]
@Image1, @Image2 and @Image3 are clean product source-of-truth crops. @Image4, @Image5, @Image6, @Image7 and @Image8 are clean benchmark frames used only for action, framing and lighting. The product in every shot is the exact same colorless, crystal-clear, thick soft transparent table protector shown in @Image1-@Image3. Preserve its smooth glossy surface, faint cool-blue visible edge, rounded corners, consistent thickness, transparency and flexible-but-substantial behavior. The light-oak wood grain must remain clearly visible through the mat. Never turn it into fabric, glass, plastic film, an orange sheet, an opaque board, or a different SKU. Keep one consistent dining table, room, hands and wardrobe across all shots.

Recreate this exact 12-second action arc with decisive hard cuts and no title cards:
Shot 1, 0.0-1.3s, extreme close-up at the rounded table corner: one hand lifts and bends the thick clear mat edge toward camera, showing real thickness and elastic resistance; the edge returns cleanly, no kinks.
Shot 2, 1.3-2.3s, top-down close-up: fingertips slide along and press the cool-blue edge; rack focus from edge to the oak grain visible through the transparent mat.
Shot 3, 2.3-3.4s, low oblique macro: a fingertip rubs and lightly scrapes the rounded edge, which stays smooth and undamaged; no tool, no spark, no cut skin.
Shot 4, 3.4-5.4s, medium-to-wide reveal: the camera pulls back to show the full elegant light-oak dining table covered by one seamless transparent protector, flat and aligned, warm modern room in background.
Shot 5, 5.4-7.5s, tight overhead proof shot: a hand pours dark soy sauce onto the clear mat; the liquid forms a glossy contained pool on top and does not penetrate or discolor the wood below.
Shot 6, 7.5-8.7s, matching angle: a clean white cloth wipes the entire pool away in one firm pass, revealing a dry, unstained, unchanged transparent surface and visible oak grain.
Shot 7, 8.7-10.9s, tactile macro sequence with two quick cuts: fingertip presses the thick edge and it rebounds; hand bends a rounded corner upward then releases it, and the mat lies flat without curling.
Shot 8, 10.9-12.0s, polished final wide shot: spotless table, full transparent mat lying perfectly flat, only forearms in simple cream knitwear briefly straighten the edge and leave frame, calm domestic warmth, gentle camera push-in, no visible face.

Composition: vertical 9:16, hands and the product stay inside the central 3:4 safe crop. Product actions must finish within their stated time windows. Do not render any readable writing, numbers, badges, brand marks, UI, captions or packaging; all copy is added later in Remotion. No extra utensils during proof shots, no duplicated fingers, no hand deformation, no product morphing, no liquid under the mat, no orange stains, no abrupt location change.
"""


VARIATIONS = {
    "a": "Camera treatment: restrained premium product-film realism, 35mm-equivalent medium shots and 70mm-equivalent macros, exact visual continuity, confident hard cuts, actions clearly readable on a phone screen.",
    "b": "Camera treatment: slightly more energetic social-commerce pacing, stronger macro-to-wide contrast, faster rack focus and cloth wipe, but stable product geometry and the same clean warm room throughout.",
    "repair": "",
}

REPAIR_PROMPT = """Single continuous 4-second premium e-commerce proof shot, no cuts, no zoom, photorealistic, natural warm daylight, exact camera angle and table from @Image1, accurate liquid and cloth physics, crisp transparent table protector detail, realistic hands, no 3D, no cartoon, no generated text, no logo, no watermark.

@Image1 is the exact starting frame and product identity lock. Continue from that frame: during 0.0-0.7s the hand finishes pouring the dark soy sauce and removes the cup; during 0.7-3.2s a clean white microfiber cloth enters from frame right and wipes the entire dark pool away in one firm continuous pass; during 3.2-4.0s the cloth exits and the camera holds on a completely clean, dry, unstained, crystal-clear table mat with the light-oak grain visible underneath. The liquid must remain above the transparent mat and must not penetrate or stain the wood. Keep the same table, room, mat thickness, lighting and hands. No duplicated fingers, no hand deformation, no residue, no liquid under the mat, no subtitles, no numbers, no badges, no labels, no UI."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=sorted(VARIATIONS), required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    output = OUT_DIR / f"seedance-candidate-{args.candidate}.mp4"
    audit_path = AUDIT_DIR / f"seedance-candidate-{args.candidate}.json"
    if output.exists() and not args.force:
        print(json.dumps({"status": "reused", "output": str(output)}, ensure_ascii=False))
        return 0

    is_repair = args.candidate == "repair"
    references = [PROJECT / "inputs/reference/dynamic_anchors/candidate-a-pour-clean.jpg"] if is_repair else PRODUCT_REFS + MOTION_REFS
    missing = [str(path) for path in references if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing reference inputs: {missing}")

    prompt = REPAIR_PROMPT if is_repair else f"{BASE_PROMPT}\n{VARIATIONS[args.candidate]}"
    seed = {"a": 26091301, "b": 26091302, "repair": 26091303}[args.candidate]
    duration = "4" if is_repair else "12"
    operation = "image_to_video" if is_repair else "reference_to_video"
    inputs = {
        "prompt": prompt,
        "preferred_provider": "seedance",
        "allowed_providers": ["seedance"],
        "operation": operation,
        "model_variant": "standard",
        "duration": duration,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generate_audio": False,
        "seed": seed,
        "output_path": str(output),
        "task_context": {
            "quality_priority": 1.0,
            "cost_sensitivity": 0.25,
            "latency_sensitivity": 0.15,
            "motion_required": True,
            "reference_fidelity": True,
        },
    }
    if is_repair:
        inputs["reference_image_path"] = str(references[0])
    else:
        inputs["reference_image_paths"] = [str(path) for path in references]

    registry.ensure_discovered()
    selector = registry.get("video_selector")
    if selector is None:
        raise RuntimeError("video_selector is not registered")

    estimate = selector.estimate_cost(inputs)
    tracker = CostTracker(
        budget_total_usd=8.5,
        reserve_pct=0.0,
        single_action_approval_usd=8.5,
        require_approval_for_new_paid_tool=True,
        mode=BudgetMode.CAP,
        cost_log_path=COST_LOG,
    )
    # The user explicitly approved Seedance 2.0 Standard up to $8.50.
    tracker.budget_total_usd = 8.5
    tracker.approve_tool("video_selector")
    entry_id = tracker.estimate("video_selector", f"seedance_candidate_{args.candidate}", estimate)
    tracker.reserve(entry_id)

    audit = {
        "version": "1.0",
        "project_id": "table-mat-mix-v1",
        "candidate": args.candidate,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cost_cap_usd": 8.5,
        "estimated_cost_usd": estimate,
        "cost_entry_id": entry_id,
        "provider_route": {
            "tool": "video_selector",
            "preferred_provider": "seedance",
            "model_variant": "standard",
            "operation": operation,
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "duration_seconds": int(duration),
            "generate_audio": False,
            "seed": seed,
        },
        "prompt_review": {
            "pre_caption": (
                "4-second pour-to-clean repair insert matching the accepted candidate."
                if is_repair
                else "12-second vertical table-mat demonstration matching the reference action order."
            ),
            "critique": {
                "subject": "Specified and identity-locked from supplied product references.",
                "subject_motion": (
                    "One timed pour-to-wipe action completes with a visible clean result."
                    if is_repair
                    else "Eight timed action beats specify hand, mat, liquid and wipe behavior."
                ),
                "scene": "One consistent warm light-oak dining room is required.",
                "spatial_framing": "Vertical 9:16 with central 3:4 action-safe crop is explicit.",
                "camera": "Macro/overhead/wide framing and hard cuts are disambiguated; no zoom-only motion.",
            },
            "post_caption": prompt,
        },
        "reference_images": [str(path.relative_to(PROJECT)) for path in references],
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        result = selector.execute(inputs)
    except Exception as exc:
        tracker.reconcile(entry_id, 0.0, success=False)
        audit["completed_at"] = datetime.now(timezone.utc).isoformat()
        audit["success"] = False
        audit["actual_cost_usd"] = 0.0
        audit["result"] = {"error": f"{type(exc).__name__}: {exc}"}
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "success": False,
                    "candidate": args.candidate,
                    "output": None,
                    "audit": str(audit_path),
                    "estimated_cost_usd": estimate,
                    "actual_cost_usd": 0.0,
                    "budget": tracker.cost_snapshot(),
                    "error": audit["result"]["error"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    tracker.reconcile(entry_id, float(result.cost_usd or 0.0), success=result.success)
    audit["completed_at"] = datetime.now(timezone.utc).isoformat()
    audit["success"] = result.success
    audit["actual_cost_usd"] = float(result.cost_usd or 0.0)
    audit["result"] = result.data if result.success else {"error": result.error}
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "success": result.success,
        "candidate": args.candidate,
        "output": str(output) if result.success else None,
        "audit": str(audit_path),
        "estimated_cost_usd": estimate,
        "actual_cost_usd": float(result.cost_usd or 0.0),
        "budget": tracker.cost_snapshot(),
        "error": result.error if not result.success else None,
        "selected_tool": result.data.get("selected_tool") if result.success else None,
        "selected_provider": result.data.get("selected_provider") if result.success else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

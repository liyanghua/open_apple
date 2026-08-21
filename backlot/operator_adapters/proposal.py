from __future__ import annotations

from typing import Any

from .base import BaseAdapter


class ProposalAdapter(BaseAdapter):
    stage = "proposal"
    adapter_id = "proposal-v1"
    artifact_name = "proposal_packet"
    operation_fields = {
        "select_concept": frozenset({"op", "concept_id"}),
        "replace_hook": frozenset({"op", "text"}),
        "reorder_selling_points": frozenset({"op", "selling_point_ids"}),
        "replace_narrative_structure": frozenset({"op", "text"}),
        "set_duration": frozenset({"op", "seconds"}),
        "replace_cta": frozenset({"op", "text"}),
        "set_reference_treatment": frozenset({"op", "retained", "changed"}),
        "set_gap_strategy": frozenset({"op", "strategy"}),
        "review_control_section": frozenset({"op", "section_id", "decision", "feedback"}),
        "approve_control_plan": frozenset({"op"}),
    }
    field_labels = {
        "selected_concept_id": "创意方案",
        "hook": "开头钩子",
        "selling_point_order": "卖点顺序",
        "narrative_structure": "叙事结构",
        "target_duration_seconds": "预计时长",
        "cta": "结尾行动引导",
        "reference_treatment": "参考方法",
        "gap_strategy": "素材缺口处理",
    }

    def load_snapshot(self, project_dir):
        snapshot = super().load_snapshot(project_dir)
        plan_path = project_dir / "artifacts" / "creative_control_plan.json"
        if plan_path.exists():
            import json
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                plan = None
            if isinstance(plan, dict) and plan.get("sections"):
                snapshot.setdefault("creative_control_plan", plan)
        return snapshot

    def _apply_one(self, snapshot: dict[str, Any], name: str, operation: dict[str, Any]) -> None:
        if name in {"review_control_section", "approve_control_plan"}:
            plan = snapshot.setdefault("creative_control_plan", {})
            reviews = plan.setdefault("section_reviews", {})
            feedback = plan.setdefault("feedback", {})
            if name == "review_control_section":
                section_id = operation["section_id"]
                reviews[section_id] = operation["decision"]
                if operation["feedback"]:
                    feedback[section_id] = operation["feedback"]
                elif section_id in feedback:
                    del feedback[section_id]
            else:
                plan["status"] = "approved"
                for section_id in ("content_direction", "story_pacing", "visual_rules", "fact_continuity", "originality_boundary"):
                    reviews[section_id] = "approved"
                plan["feedback"] = {}
            return
        mapping = {
            "select_concept": ("selected_concept_id", "concept_id"),
            "replace_hook": ("hook", "text"),
            "reorder_selling_points": ("selling_point_order", "selling_point_ids"),
            "replace_narrative_structure": ("narrative_structure", "text"),
            "set_duration": ("target_duration_seconds", "seconds"),
            "replace_cta": ("cta", "text"),
            "set_gap_strategy": ("gap_strategy", "strategy"),
        }
        if name == "set_reference_treatment":
            snapshot["reference_treatment"] = {
                "retained": operation["retained"],
                "changed": operation["changed"],
            }
        else:
            field, source = mapping[name]
            snapshot[field] = operation[source]
            if name == "select_concept" and isinstance(snapshot.get("creative_control_plan"), dict):
                snapshot["creative_control_plan"]["status"] = "needs_revision"

    def _touched_field(self, name: str, operation: dict[str, Any]) -> str:
        return {
            "select_concept": "selected_concept_id",
            "replace_hook": "hook",
            "reorder_selling_points": "selling_point_order",
            "replace_narrative_structure": "narrative_structure",
            "set_duration": "target_duration_seconds",
            "replace_cta": "cta",
            "set_reference_treatment": "reference_treatment",
            "set_gap_strategy": "gap_strategy",
            "review_control_section": "creative_control_plan.section_reviews",
            "approve_control_plan": "creative_control_plan.status",
        }[name]

    def change_signals(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        names = {self._check_operation(item) for item in operations}
        creative = bool(names & {"select_concept", "replace_hook", "replace_cta", "replace_narrative_structure", "review_control_section", "approve_control_plan"})
        return {
            "reopen_creative": creative,
            "reopen_sample": creative,
            "render_route": "full_render" if creative else "no_render",
        }

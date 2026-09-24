"""Cost tracker core: estimate, reserve, reconcile, and persist to cost_log.json.

Implements the budget governance rules from the spec:
- Every paid operation produces a preflight estimate
- The orchestrator reserves estimated budget before execution
- Budget overruns trigger pauses (in warn/cap mode)
- Actual spend is reconciled when the tool finishes or fails
"""

from __future__ import annotations

import json
import math
import threading
from functools import wraps
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from lib.config_model import BudgetMode
from lib.cache_io import atomic_write_json
from lib.cost_persistence import ledger_lock


class EntryStatus(str, Enum):
    ESTIMATED = "estimated"
    RESERVED = "reserved"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class BudgetExceededError(Exception):
    """Raised when an operation would exceed the budget in cap mode."""
    pass


class ApprovalRequiredError(Exception):
    """Raised when an operation needs user approval before proceeding."""
    pass


def _transaction(method):
    """Reload inside the lock: a stale instance must never overwrite new spend."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._memory_lock:
            if self.cost_log_path is None:
                return method(self, *args, **kwargs)
            with ledger_lock(self.cost_log_path):
                if self.cost_log_path.exists():
                    self._load()
                return method(self, *args, **kwargs)
    return wrapped


class CostTracker:
    """Tracks estimated, reserved, and actual costs for a pipeline project."""

    def __init__(
        self,
        budget_total_usd: float = 10.0,
        reserve_pct: float = 0.10,
        single_action_approval_usd: float = 0.50,
        require_approval_for_new_paid_tool: bool = True,
        mode: BudgetMode = BudgetMode.WARN,
        cost_log_path: Optional[Path] = None,
    ) -> None:
        self.budget_total_usd = budget_total_usd
        self.reserve_pct = reserve_pct
        self.single_action_approval_usd = single_action_approval_usd
        self.require_approval_for_new_paid_tool = require_approval_for_new_paid_tool
        self.mode = mode
        self.cost_log_path = Path(cost_log_path) if cost_log_path else None
        self._memory_lock = threading.RLock()
        self.entries: list[dict[str, Any]] = []
        self._approved_tools: set[str] = set()

        if self.cost_log_path and self.cost_log_path.exists():
            self._load()

    # ---- Budget calculations ----

    @property
    def budget_reserved_usd(self) -> float:
        return sum(
            e.get("reserved_usd", 0.0)
            for e in self.entries
            if e["status"] == EntryStatus.RESERVED.value
        )

    @property
    def budget_spent_usd(self) -> float:
        return sum(
            (e.get("actual_usd") or 0.0)
            for e in self.entries
            if e["status"] in (EntryStatus.COMPLETED.value, EntryStatus.FAILED.value)
        )

    @property
    def budget_remaining_usd(self) -> float:
        return (self.budget_total_usd - self.budget_spent_usd - self.budget_reserved_usd
                - sum(e.get("budget_commitment_usd", 0.0) for e in self.entries))

    @property
    def usable_budget_usd(self) -> float:
        """Budget minus the reserve holdback."""
        holdback = self.budget_total_usd * self.reserve_pct
        return max(0.0, self.budget_remaining_usd - holdback)

    @_transaction
    def cost_snapshot(self) -> dict[str, Any]:
        settlement = self._settlement_summary()
        return {
            # Legacy aggregate is the sum of known USD charges, never a complete bill.
            "total_spent_usd": round(self.budget_spent_usd, 4),
            "total_reserved_usd": round(self.budget_reserved_usd, 4),
            "total_commitment_usd": round(sum(e.get("budget_commitment_usd", 0) for e in self.entries), 4),
            "budget_remaining_usd": round(self.budget_remaining_usd, 4),
            **settlement,
        }

    def _settlement_summary(self) -> dict[str, Any]:
        known_actuals: dict[str, float] = {}
        unknown_currencies: set[str] = set()
        estimates: dict[str, float] = {}
        unknown = 0
        unassigned = False
        for entry in self.entries:
            estimate = entry.get("catalog_estimate")
            if estimate:
                currency = estimate["currency"]
                estimates[currency] = round(estimates.get(currency, 0) + estimate["amount"], 6)
            if entry["status"] not in {"completed", "failed"}:
                continue
            actual = entry.get("actual_cost")
            if actual is None and entry.get("actual_usd") is not None:
                actual = {"amount": entry["actual_usd"], "currency": "USD"}
            if actual is None:
                unknown += 1
                if estimate:
                    unknown_currencies.add(estimate["currency"])
                else:
                    unassigned = True
            else:
                currency = actual["currency"]
                known_actuals[currency] = round(known_actuals.get(currency, 0) + actual["amount"], 6)
        totals = {currency: (None if unassigned or currency in unknown_currencies else amount)
                  for currency, amount in known_actuals.items()}
        totals.update({currency: None for currency in unknown_currencies})
        return {"actual_spend_by_currency": totals,
                "known_actual_spend_by_currency": known_actuals,
                "catalog_estimate_by_currency": estimates,
                "unknown_settlement_count": unknown,
                "unknown_settlement_currency": unassigned}

    # ---- Core operations ----

    @_transaction
    def estimate(self, tool: str, operation: str, estimated_usd: float, *,
                 budget_equivalent_cny: float | None = None,
                 budget_equivalence_provenance: dict[str, Any] | None = None) -> str:
        """Record a USD commitment and optional explicitly authorized CNY ceiling."""
        self._amount(estimated_usd)
        equivalence = {}
        if budget_equivalent_cny is not None:
            amount = self._amount(budget_equivalent_cny)
            if amount <= 0 or estimated_usd <= 0 or not (budget_equivalence_provenance or {}).get("approval_ref"):
                raise ValueError("CNY budget equivalence needs a positive USD commitment and approval reference")
            equivalence = {"budget_equivalent_cny": amount,
                           "budget_equivalence_provenance": budget_equivalence_provenance}
        entry_id = self._new_id()
        self.entries.append({
            "id": entry_id,
            "tool": tool,
            "operation": operation,
            "status": EntryStatus.ESTIMATED.value,
            "estimated_usd": round(estimated_usd, 4),
            "reserved_usd": 0.0,
            "actual_usd": None,
            "actual_cost": None,
            "budget_currency": "USD",
            "budget_commitment_usd": 0.0,
            "provider_billing_status": "not_submitted",
            **equivalence,
            "timestamp": self._now(),
        })
        self._save()
        return entry_id

    @_transaction
    def reserve(self, entry_id: str) -> None:
        """Reserve budget for an estimated entry.

        Raises BudgetExceededError in cap mode, or ApprovalRequiredError
        when the action exceeds the single-action approval threshold.
        """
        entry = self._find(entry_id)
        if entry["status"] == "reserved":
            return
        if entry["status"] != "estimated":
            raise ValueError("only an estimated entry may be reserved")
        estimated = entry["estimated_usd"]

        # Check single-action approval threshold
        if estimated > self.single_action_approval_usd:
            if self.mode != BudgetMode.OBSERVE:
                raise ApprovalRequiredError(
                    f"Action costs ${estimated:.2f}, exceeds "
                    f"single-action threshold ${self.single_action_approval_usd:.2f}"
                )

        # Check new paid tool approval
        if self.require_approval_for_new_paid_tool and estimated > 0:
            if entry["tool"] not in self._approved_tools:
                if self.mode != BudgetMode.OBSERVE:
                    raise ApprovalRequiredError(
                        f"First paid use of tool {entry['tool']!r} requires approval"
                    )

        # Check budget
        if estimated > self.usable_budget_usd:
            message = (
                f"Reservation of ${estimated:.2f} exceeds usable budget "
                f"${self.usable_budget_usd:.2f}"
            )
            if self.mode == BudgetMode.CAP:
                raise BudgetExceededError(message)
            if self.mode == BudgetMode.WARN:
                entry["budget_warning"] = True
                entry["budget_warning_message"] = message

        entry["status"] = EntryStatus.RESERVED.value
        entry["reserved_usd"] = estimated
        entry["timestamp"] = self._now()
        self._save()

    @_transaction
    def assert_reserved(
        self, entry_id: str, tool: str, operation: str, estimated_usd: float
    ) -> None:
        """Verify a reservation still authorizes the exact paid operation."""
        entry = self._find(entry_id)
        if entry.get("status") != EntryStatus.RESERVED.value:
            raise ValueError("cost reservation is not active")
        if entry.get("tool") != tool or entry.get("operation") != operation:
            raise ValueError("cost reservation does not match tool or operation")
        if abs(float(entry.get("estimated_usd", 0.0)) - float(estimated_usd)) > 1e-9:
            raise ValueError("cost reservation amount does not match estimate")

    @_transaction
    def record_reuse(
        self, tool: str, cache_key: str, reused_from: str, saved_seconds: float
    ) -> str:
        """Record a zero-cost cache reuse without reserving paid budget."""
        entry_id = self._new_id()
        self.entries.append({
            "id": entry_id,
            "tool": tool,
            "operation": "reuse",
            "status": EntryStatus.COMPLETED.value,
            "estimated_usd": 0.0,
            "reserved_usd": 0.0,
            "actual_usd": 0.0,
            "cache_key": cache_key,
            "reused_from": reused_from,
            "saved_seconds": round(float(saved_seconds), 3),
            "timestamp": self._now(),
        })
        self._save()
        return entry_id

    @_transaction
    def approve_tool(self, tool: str) -> None:
        """Mark a tool as approved for paid operations."""
        self._approved_tools.add(tool)
        self._save()

    @_transaction
    def reconcile(
        self, entry_id: str, actual_usd: float | None = None, success: bool = True,
        *, usage: dict[str, Any] | None = None,
        catalog_estimate: dict[str, Any] | None = None,
        actual_cost: dict[str, Any] | None = None,
        provider_status: str | None = None, provider_task_id: str | None = None,
        settlement_provenance: dict[str, Any] | None = None,
    ) -> None:
        """Release reservation; retain its USD commitment until USD settlement.

        Usage times a tariff belongs in catalog_estimate, never actual_usd.
        CNY settlement cannot release a USD commitment without explicit FX evidence.
        Legacy numeric actual_usd calls remain supported as caller-reported charges.
        """
        entry = self._find(entry_id)
        if entry["status"] == "refunded":
            raise ValueError("cannot reconcile a refunded preflight entry")
        if actual_usd is not None:
            actual_usd = self._amount(actual_usd)
            if actual_cost is not None and actual_cost != {"amount": actual_usd, "currency": "USD"}:
                raise ValueError("conflicting settlement currencies")
            actual_cost = {"amount": actual_usd, "currency": "USD"}
        for money in (catalog_estimate, actual_cost):
            if money is not None:
                self._amount(money["amount"])
                if not isinstance(money.get("currency"), str) or len(money["currency"]) != 3:
                    raise ValueError("money requires an ISO currency")
        old_actual = entry.get("actual_cost")
        if old_actual is None and entry["status"] in {"completed", "failed"} and entry.get("actual_usd") is not None:
            old_actual = {"amount": entry["actual_usd"], "currency": "USD"}
        if old_actual is not None and actual_cost is not None and old_actual != actual_cost:
            raise ValueError("settlement already recorded with a different amount")
        if old_actual is not None and actual_cost is None:
            settlement_provenance = None  # A usage re-query cannot rewrite a bill's source.
        actual_cost = old_actual if actual_cost is None else actual_cost
        if provider_task_id and (entry.get("provider_task_id") not in {None, provider_task_id}
                or any(other["id"] != entry_id and other.get("provider_task_id") == provider_task_id
                       for other in self.entries)):
            raise ValueError("provider task or reservation already belongs to a different entry")
        entry["status"] = "completed" if success else "failed"
        entry["actual_cost"] = actual_cost
        entry["actual_usd"] = actual_cost["amount"] if actual_cost and actual_cost["currency"] == "USD" else None
        entry["budget_commitment_usd"] = 0.0 if entry["actual_usd"] is not None else entry["estimated_usd"]
        entry["reserved_usd"] = 0.0
        entry["provider_billing_status"] = "settled" if actual_cost is not None else "unconfirmed"
        for key, value in (("usage", usage), ("catalog_estimate", catalog_estimate),
                           ("provider_status", provider_status), ("provider_task_id", provider_task_id),
                           ("settlement_provenance", settlement_provenance)):
            if value is not None:
                entry[key] = value
        if actual_cost is not None and not entry.get("settlement_provenance"):
            entry["settlement_provenance"] = {"source": "legacy_caller_reported"}
        entry["timestamp"] = self._now()
        self._save()

    @_transaction
    def bind_submission(self, entry_id: str, *, tool: str, attempt_id: str,
                        idempotency_key: str, task_id: str | None = None,
                        operation: str | None = None, minimum_usd: float | None = None,
                        minimum_cny: float | None = None) -> None:
        """Attach durable submission identity before the POST can leave the process."""
        entry = self._find(entry_id)
        if entry.get("tool") != tool or entry["status"] != "reserved":
            raise ValueError("submission requires an active reservation for this tool")
        if operation is not None and entry.get("operation") != operation:
            raise ValueError("reservation operation does not match the paid generation operation")
        if minimum_usd is not None or minimum_cny is not None:
            reserved = self._amount(entry.get("reserved_usd", 0))
            if reserved <= 0:
                raise ValueError("paid generation requires a positive budget reservation")
            if minimum_usd is not None and reserved + 1e-9 < self._amount(minimum_usd):
                raise ValueError("reserved USD budget does not cover the generation estimate")
            if minimum_usd is None:
                ceiling = entry.get("budget_equivalent_cny")
                provenance = entry.get("budget_equivalence_provenance") or {}
                if ceiling is None or not provenance.get("approval_ref") or self._amount(ceiling) + 1e-9 < self._amount(minimum_cny):
                    raise ValueError("missing FX requires an approved CNY budget equivalent covering this estimate")
        if entry.get("attempt_id") not in {None, attempt_id}:
            raise ValueError("reservation already bound to a different attempt")
        if task_id and entry.get("provider_task_id") not in {None, task_id}:
            raise ValueError("reservation already bound to a different task")
        entry.update(attempt_id=attempt_id, idempotency_key=idempotency_key,
                     submission_status="submitted" if task_id else "submitting",
                     provider_billing_status="unconfirmed")
        if task_id:
            entry["provider_task_id"] = task_id
        entry["timestamp"] = self._now()
        self._save()

    @_transaction
    def record_creative_outcome(self, entry_id: str, *, accepted: bool) -> None:
        entry = self._find(entry_id)
        if entry["status"] != "completed":
            raise ValueError("creative outcome requires provider success")
        entry["outcome"] = "creative_accepted" if accepted else "provider_success_then_creative_reject"
        entry["timestamp"] = self._now()
        self._save()

    @_transaction
    def refund(self, entry_id: str) -> None:
        """Release only an unexecuted reservation; a creative reject still costs."""
        entry = self._find(entry_id)
        if entry["status"] == "refunded":
            return
        if entry["status"] in {"completed", "failed"} or entry.get("provider_task_id") or entry.get("submission_status"):
            raise ValueError("cannot refund an executed task without a billing credit")
        entry["status"] = "refunded"
        entry["reserved_usd"] = 0.0
        entry["actual_usd"] = 0.0
        entry["actual_cost"] = {"amount": 0.0, "currency": "USD"}
        entry["outcome"] = "preflight_rejected"
        entry["provider_billing_status"] = "not_submitted"
        entry["timestamp"] = self._now()
        self._save()

    @staticmethod
    def _amount(value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError("cost must be finite and nonnegative")
        return round(float(value), 6)

    # ---- Reference-driven estimation ----

    def estimate_from_reference(
        self,
        video_analysis_brief: dict,
        target_duration_seconds: int,
        tool_plan: dict,
    ) -> dict:
        """Estimate production cost based on reference analysis + target duration.

        Args:
            video_analysis_brief: The VideoAnalysisBrief artifact from video analysis
            target_duration_seconds: How long the output video should be
            tool_plan: Which tools will be used for each asset type, e.g.:
                {
                    "image_generation": {"tool": "flux_fal", "cost_per_unit": 0.05},
                    "video_generation": {"tool": "kling_fal", "cost_per_unit": 0.30,
                                         "clip_duration_seconds": 5},
                    "tts": {"tool": "elevenlabs_tts", "cost_per_word": 0.00003},
                    "music": {"tool": "music_gen", "cost_per_track": 0.10},
                }

        Returns:
            Itemized cost breakdown with line items, total, sample cost, and assumptions.
        """
        structure = video_analysis_brief.get("structure_analysis", {})
        pacing = structure.get("pacing_profile", {})
        narration = video_analysis_brief.get("narration_transcript", {})
        ref_duration = video_analysis_brief.get("source", {}).get("duration_seconds", 60)
        pacing_style = pacing.get("pacing_style", "steady_educational")

        # ── Scene count estimation ──
        # Don't just scale linearly — use the PACING DENSITY from the reference.
        # A music video with 8 scenes in 162s has ~3 cuts/min.
        # Scaling to 60s should PRESERVE that cut rate, not reduce scene count.
        ref_scenes = structure.get("total_scenes", 8)
        if ref_duration > 0:
            cuts_per_minute = ref_scenes / (ref_duration / 60)
        else:
            cuts_per_minute = 4.0  # default: moderate pacing

        # Apply pacing-aware minimums (a fast-cut video doesn't become a slideshow)
        min_scenes_by_pacing = {
            "rapid_fire": 10,
            "dynamic_social": 8,
            "steady_educational": 5,
            "slow_contemplative": 3,
            "variable": 6,
        }
        min_scenes = min_scenes_by_pacing.get(pacing_style, 5)

        # Scene count = max(pacing-density-based, minimum for style)
        density_based_scenes = round(cuts_per_minute * (target_duration_seconds / 60))
        estimated_scenes = max(min_scenes, density_based_scenes)

        # ── Narration word count ──
        ref_word_count = narration.get("word_count", 0)
        if ref_duration > 0 and ref_word_count > 0:
            actual_wpm = (ref_word_count / ref_duration) * 60
        else:
            actual_wpm = 150  # default conversational pace
        estimated_words = round(actual_wpm * (target_duration_seconds / 60))

        # ── Motion ratio from reference ──
        scenes_list = structure.get("scenes", [])
        motion_ratio, motion_basis = self._estimate_motion_ratio(
            video_analysis_brief=video_analysis_brief,
            scenes_list=scenes_list,
            pacing_style=pacing_style,
        )

        estimated_motion_scenes = (
            max(1, round(estimated_scenes * motion_ratio))
            if motion_ratio > 0
            else 0
        )
        estimated_still_scenes = estimated_scenes - estimated_motion_scenes

        # ── Video clip coverage ──
        # Video gen tools produce clips of limited duration (typically 5-10s).
        # A 60s video with motion needs enough clips to COVER the duration,
        # not just 1 per scene.
        vid_plan = tool_plan.get("video_generation", {})
        clip_duration = vid_plan.get("clip_duration_seconds", 5) if vid_plan else 5
        motion_seconds = target_duration_seconds * motion_ratio
        clips_needed_for_coverage = max(
            estimated_motion_scenes,
            round(motion_seconds / clip_duration)
        ) if vid_plan else 0

        # ── Retry/waste buffer ──
        # Not every generation succeeds or looks good. Add a buffer.
        retry_multiplier = 1.3  # ~30% extra for retries and rejected outputs

        # ── Image count ──
        # Images per scene depends on visual variety needs:
        # - Explainer: 1-2 images per scene
        # - Music video / cinematic: 2-3 images per scene (mood shifts, variety)
        images_per_scene = 2.0 if pacing_style in ("dynamic_social", "rapid_fire") else 1.5
        estimated_images = max(
            estimated_scenes,
            round(estimated_scenes * images_per_scene)
        )

        # Build line items
        line_items = []
        assumptions = []

        assumptions.append(
            f"{estimated_scenes} scenes (reference has {cuts_per_minute:.1f} cuts/min, "
            f"pacing: {pacing_style})"
        )
        assumptions.append(motion_basis)

        # Image generation
        img_plan = tool_plan.get("image_generation", {})
        if img_plan:
            img_count = round(estimated_images * retry_multiplier)
            unit_cost = img_plan.get("cost_per_unit", 0.05)
            line_items.append({
                "category": "image_generation",
                "provider": img_plan.get("tool", "unknown"),
                "quantity": img_count,
                "unit_cost_usd": unit_cost,
                "total_usd": round(img_count * unit_cost, 4),
                "basis": (
                    f"~{images_per_scene:.0f} images/scene x {estimated_scenes} scenes "
                    f"+ {round((retry_multiplier - 1) * 100)}% retry buffer"
                ),
            })

        # Video generation
        if vid_plan and clips_needed_for_coverage > 0:
            clip_count = round(clips_needed_for_coverage * retry_multiplier)
            unit_cost = vid_plan.get("cost_per_unit", 0.30)
            line_items.append({
                "category": "video_generation",
                "provider": vid_plan.get("tool", "unknown"),
                "quantity": clip_count,
                "unit_cost_usd": unit_cost,
                "total_usd": round(clip_count * unit_cost, 4),
                "basis": (
                    f"{motion_seconds:.0f}s of motion / {clip_duration}s clips = "
                    f"{clips_needed_for_coverage} clips + retry buffer"
                ),
            })
            assumptions.append(
                f"{round(motion_ratio * 100)}% motion ratio → "
                f"{motion_seconds:.0f}s needs {clips_needed_for_coverage} clips "
                f"({clip_duration}s each)"
            )

        # TTS narration
        tts_plan = tool_plan.get("tts", {})
        if tts_plan and estimated_words > 10:
            cost_per_word = tts_plan.get("cost_per_word", 0.00003)
            tts_cost = round(estimated_words * cost_per_word, 4)
            line_items.append({
                "category": "tts_narration",
                "provider": tts_plan.get("tool", "unknown"),
                "quantity": estimated_words,
                "unit_cost_usd": cost_per_word,
                "total_usd": tts_cost,
                "basis": f"Narration at {round(actual_wpm)} WPM = ~{estimated_words} words",
            })
            assumptions.append(
                f"Narration at {round(actual_wpm)} WPM = ~{estimated_words} words "
                f"for {target_duration_seconds} seconds"
            )

        # Music
        music_plan = tool_plan.get("music", {})
        if music_plan:
            music_cost = music_plan.get("cost_per_track", 0.0)
            line_items.append({
                "category": "music",
                "provider": music_plan.get("tool", "unknown"),
                "quantity": 1,
                "unit_cost_usd": music_cost,
                "total_usd": music_cost,
                "basis": "1 background music track",
            })

        subtotal = round(sum(item["total_usd"] for item in line_items), 4)

        # ── Cost range instead of single number ──
        # Low: everything works first try. High: retry buffer fully consumed.
        low_total = round(subtotal / retry_multiplier, 4)
        high_total = round(subtotal * 1.15, 4)  # 15% above retry-buffered estimate

        # Sample cost: 2 scenes worth of assets (hook + 1 middle)
        sample_scenes = 2
        sample_fraction = sample_scenes / max(estimated_scenes, 1)
        sample_cost = round(subtotal * sample_fraction, 4)

        # Confidence based on how much data we have
        if scenes_list and narration.get("word_count", 0) > 0:
            confidence = "high"
        elif scenes_list or narration.get("word_count", 0) > 0:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "line_items": line_items,
            "total_usd": subtotal,
            "total_range_usd": {"low": low_total, "high": high_total},
            "sample_cost_usd": sample_cost,
            "confidence": confidence,
            "assumptions": assumptions,
            "estimated_scenes": estimated_scenes,
            "estimated_images": estimated_images,
            "estimated_clips": clips_needed_for_coverage,
            "estimated_words": estimated_words,
            "motion_ratio": round(motion_ratio, 2),
            "cuts_per_minute": round(cuts_per_minute, 1),
            "target_duration_seconds": target_duration_seconds,
        }

    def _estimate_motion_ratio(
        self,
        *,
        video_analysis_brief: dict,
        scenes_list: list[dict[str, Any]],
        pacing_style: str,
    ) -> tuple[float, str]:
        """Estimate how much of the target treatment truly needs motion."""
        motion_weights = {
            "animation": 1.0,
            "b_roll": 1.0,
            "stock_footage": 1.0,
            "product_shot": 0.9,
            "transition": 0.6,
            "screen_recording": 0.45,
            "talking_head": 0.35,
            "diagram": 0.25,
            "chart": 0.25,
            "text_card": 0.2,
        }
        classified_weights = [
            motion_weights[visual_type]
            for scene in scenes_list
            if (visual_type := scene.get("visual_type")) in motion_weights
        ]
        if classified_weights:
            ratio = sum(classified_weights) / len(classified_weights)
            unknown_count = max(0, len(scenes_list) - len(classified_weights))
            if unknown_count:
                fallback_ratio, _ = self._fallback_motion_ratio(
                    video_analysis_brief=video_analysis_brief,
                    pacing_style=pacing_style,
                )
                ratio = (
                    (sum(classified_weights) + fallback_ratio * unknown_count)
                    / len(scenes_list)
                )
                basis = (
                    "motion ratio blended from classified scene types and "
                    "reference-style fallback for unclassified scenes"
                )
            else:
                basis = "motion ratio derived from classified scene types"
            return round(min(max(ratio, 0.0), 0.95), 2), basis

        return self._fallback_motion_ratio(
            video_analysis_brief=video_analysis_brief,
            pacing_style=pacing_style,
        )

    def _fallback_motion_ratio(
        self,
        *,
        video_analysis_brief: dict,
        pacing_style: str,
    ) -> tuple[float, str]:
        """Fallback heuristic for motion ratio before scene vision enrichment."""
        source_type = video_analysis_brief.get("source", {}).get("type", "")
        replication = video_analysis_brief.get("replication_guidance", {})
        motion_required = bool(replication.get("motion_required"))
        suggested_pipeline = replication.get("suggested_pipeline", "")

        base_by_pacing = {
            "rapid_fire": 0.8,
            "dynamic_social": 0.65,
            "steady_educational": 0.35,
            "slow_contemplative": 0.2,
            "variable": 0.5,
        }
        ratio = base_by_pacing.get(pacing_style, 0.5)

        if source_type in ("shorts", "instagram", "tiktok"):
            ratio = max(ratio, 0.7)
        if motion_required:
            ratio = max(ratio, 0.6)
        if suggested_pipeline == "cinematic":
            ratio = max(ratio, 0.55)

        ratio = round(min(max(ratio, 0.1), 0.95), 2)
        basis = (
            "motion ratio inferred from pacing/style because scene visual types "
            "have not been enriched yet"
        )
        return ratio, basis

    # ---- Persistence ----

    def _save(self) -> None:
        if self.cost_log_path is None:
            return
        data = {
            "version": "1.1",
            "budget_currency": "USD",
            "policy": {"mode": self.mode.value, "reserve_pct": self.reserve_pct,
                       "single_action_approval_usd": self.single_action_approval_usd,
                       "require_approval_for_new_paid_tool": self.require_approval_for_new_paid_tool},
            "budget_total_usd": self.budget_total_usd,
            "budget_reserved_usd": round(self.budget_reserved_usd, 4),
            "budget_spent_usd": round(self.budget_spent_usd, 4),
            "budget_commitment_usd": round(sum(e.get("budget_commitment_usd", 0) for e in self.entries), 4),
            "budget_spent_basis": "known_USD_settlements_only",
            **self._settlement_summary(),
            "approved_tools": sorted(self._approved_tools),
            "entries": self.entries,
        }
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.cost_log_path, data)

    def _load(self) -> None:
        with open(self.cost_log_path) as f:  # type: ignore[arg-type]
            data = json.load(f)
        self.entries = data.get("entries", [])
        self.budget_total_usd = data.get("budget_total_usd", self.budget_total_usd)
        self._approved_tools = set(data.get("approved_tools", []))
        policy = data.get("policy", {})
        self.mode = BudgetMode(policy.get("mode", self.mode.value))
        self.reserve_pct = policy.get("reserve_pct", self.reserve_pct)
        self.single_action_approval_usd = policy.get("single_action_approval_usd", self.single_action_approval_usd)
        self.require_approval_for_new_paid_tool = policy.get("require_approval_for_new_paid_tool", self.require_approval_for_new_paid_tool)

    # ---- Helpers ----

    def _find(self, entry_id: str) -> dict[str, Any]:
        for entry in self.entries:
            if entry["id"] == entry_id:
                return entry
        raise KeyError(f"Cost entry {entry_id!r} not found")

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

"""Capability-level text-to-speech selector that chooses among provider tools.

Provider discovery is automatic — any BaseTool with capability="tts"
is picked up from the registry.  Adding a new TTS provider requires only creating
the tool file in tools/audio/; no changes to this selector are needed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from lib.artifact_cache import ArtifactCache
from lib.cache_io import link_or_copy_atomic
from tools.base_tool import (
    BaseTool, CacheArtifactSpec, ToolResult, ToolRuntime, ToolStability, ToolTier, ToolStatus,
)


class TTSSelector(BaseTool):
    name = "tts_selector"
    version = "0.2.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "selector"
    stability = ToolStability.BETA
    runtime = ToolRuntime.HYBRID
    agent_skills = ["text-to-speech", "elevenlabs", "openai-docs"]

    capabilities = [
        "text_to_speech",
        "provider_selection",
    ]
    supports = {
        "user_preference_routing": True,
        "offline_fallback": True,
        "multilingual": True,
    }
    best_for = [
        "preflight tool selection",
        "user-facing recommendation flows",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "voice_id": {
                "type": "string",
                "description": "Provider-specific voice ID. Passed through to the selected TTS provider.",
            },
            "voice_language": {
                "type": "string",
                "enum": ["zh", "en"],
                "description": "Kling official voice language. Passed through when selected provider supports it.",
            },
            "voice_speed": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 2.0,
                "description": "Kling official voice speed. Use speed for OpenAI/ElevenLabs-style controls.",
            },
            "model_id": {
                "type": "string",
                "description": "TTS model to use (e.g. eleven_multilingual_v2). Passed through to provider.",
            },
            "stability": {
                "type": "number", "minimum": 0, "maximum": 1,
                "description": "Voice stability (ElevenLabs). Lower = more expressive.",
            },
            "similarity_boost": {
                "type": "number", "minimum": 0, "maximum": 1,
                "description": "Voice similarity boost (ElevenLabs).",
            },
            "style": {
                "type": "number", "minimum": 0, "maximum": 1,
                "description": "Style exaggeration (ElevenLabs). Higher = more expressive.",
            },
            "instructions": {
                "type": "string",
                "description": "Provider-level delivery instructions for expressive narration when supported.",
            },
            "speaking_rate": {
                "type": "number",
                "minimum": 0.25,
                "maximum": 2.0,
                "description": "Google-style speakingRate control. Use speed for OpenAI/ElevenLabs-style controls.",
            },
            "speed": {
                "type": "number",
                "minimum": 0.25,
                "maximum": 4.0,
                "description": "Alias for speaking speed used by some providers.",
            },
            "pitch": {
                "type": "number",
                "minimum": -50,
                "maximum": 50,
                "description": "Provider-specific pitch control. Google TTS accepts -20..20; HeyGen-style providers may accept wider ranges.",
            },
            "input_type": {
                "type": "string",
                "enum": ["text", "ssml"],
                "default": "text",
                "description": "Use 'ssml' only when the selected provider supports tags such as <break>.",
            },
            "voice_performance": {
                "type": "object",
                "description": "Structured voice-performance plan or section delivery cues from the script artifact.",
            },
            "sample_mode": {
                "type": "boolean",
                "default": False,
                "description": "True when generating an approval sample before batch narration.",
            },
            "output_format": {
                "type": "string",
                "description": "Audio output format (e.g. mp3_44100_128). Passed through to provider.",
            },
            "preferred_provider": {
                "type": "string",
                "description": "Provider name or 'auto'. Valid values are discovered at runtime from the registry.",
                "default": "auto",
            },
            "allowed_providers": {
                "type": "array",
                "items": {"type": "string"},
            },
            "operation": {
                "type": "string",
                "enum": ["generate", "rank", "prepare", "materialize"],
                "default": "generate",
                "description": "rank selects providers; prepare checks cache; materialize reuses cache; generate may call the provider.",
            },
            "output_path": {"type": "string"},
            "metadata_path": {"type": "string"},
            "project_dir": {"type": "string"},
            "cache_dir": {"type": "string"},
            "cache_key": {"type": "string"},
            "cost_log_path": {"type": "string"},
            "reservation_id": {"type": "string"},
        },
    }

    def _providers(self) -> list[BaseTool]:
        """Auto-discover TTS providers from the registry."""
        from tools.tool_registry import registry
        registry.ensure_discovered()
        return [t for t in registry.get_by_capability("tts")
                if t.name != self.name]

    @property
    def fallback_tools(self) -> list[str]:
        """Dynamically built from discovered providers."""
        return [t.name for t in self._providers()]

    @property
    def provider_matrix(self) -> dict[str, dict[str, str]]:
        """Built at runtime from each provider's best_for field."""
        matrix = {}
        for tool in self._providers():
            strength = ", ".join(tool.best_for) if tool.best_for else tool.name
            matrix[tool.provider] = {"tool": tool.name, "strength": strength}
        return matrix

    def get_status(self) -> ToolStatus:
        if any(tool.get_status() == ToolStatus.AVAILABLE for tool in self._providers()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        candidates = self._providers()
        if not candidates:
            return 0.0
        tool, _ = self._select_best_tool(inputs, candidates, self._prepare_task_context(inputs))
        return tool.estimate_cost(inputs) if tool else 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.scoring import rank_providers

        task_context = self._prepare_task_context(inputs)
        candidates = self._providers()

        # Rank mode — return scored provider rankings without generating
        if inputs.get("operation") == "rank":
            rankings = rank_providers(candidates, task_context)
            return ToolResult(
                success=True,
                data={
                    "rankings": self._serialize_rankings(candidates, rankings),
                    "explanation": "\n".join(r.explain() for r in rankings[:5]),
                    "normalized_task_context": task_context,
                },
            )

        # Normal generation — use scored selection
        tool, score = self._select_best_tool(inputs, candidates, task_context)
        if tool is None:
            return ToolResult(success=False, error="No TTS provider available.")

        plan = self._cache_plan(inputs, tool)
        operation = inputs.get("operation", "generate")
        if operation == "prepare":
            return ToolResult(success=True, data={
                "provider": tool.provider,
                "selected_tool": tool.name,
                "cache_enabled": plan["enabled"],
                "cache_status": "hit" if plan["lookup"] is not None and plan["lookup"].hit else "miss",
                "cache_hit": bool(plan["lookup"] is not None and plan["lookup"].hit),
                "cache_key": plan["key"],
                "estimated_cost_usd": tool.estimate_cost(inputs),
                "provider_called": False,
            })
        if operation == "materialize":
            return self._materialize(inputs, tool, plan)

        estimated = float(tool.estimate_cost(inputs))
        if estimated > 0:
            cost_path = inputs.get("cost_log_path")
            reservation_id = inputs.get("reservation_id")
            if not cost_path or not reservation_id:
                return ToolResult(
                    success=False,
                    data={"cache_status": "miss", "cache_hit": False, "provider_called": False},
                    error="Paid TTS generation requires cost_log_path and reservation_id",
                )
            try:
                from tools.cost_tracker import CostTracker
                CostTracker(cost_log_path=Path(cost_path)).assert_reserved(
                    reservation_id, tool.name, "generate", estimated
                )
            except (KeyError, ValueError, OSError) as exc:
                return ToolResult(
                    success=False,
                    data={"cache_status": "miss", "cache_hit": False, "provider_called": False},
                    error=f"Invalid TTS cost reservation: {exc}",
                )

        result = tool.execute(inputs)
        if result.success:
            if plan["enabled"]:
                try:
                    self._store_cache(plan, tool, result)
                except (OSError, ValueError) as exc:
                    return ToolResult(
                        success=False,
                        data={"cache_status": "miss", "cache_hit": False, "provider_called": True},
                        error=f"TTS cache store failed: {exc}",
                    )
            result.data.setdefault("selected_tool", tool.name)
            result.data["selected_provider"] = tool.provider
            result.data["selection_reason"] = score.explain() if score else f"Selected {tool.provider} ({tool.name})"
            if score:
                result.data["provider_score"] = score.to_dict()
            result.data.update(self._tool_context_payload(tool))
            result.data["alternatives_considered"] = [
                t.name for t in candidates
                if t.name != tool.name and t.get_status().value == "available"
            ]
            result.data.update({
                "cache_status": "miss",
                "cache_hit": False,
                "cache_key": plan["key"],
                "provider_called": True,
            })
        return result

    def _cache_plan(self, inputs: dict[str, Any], tool: BaseTool) -> dict[str, Any]:
        from lib.cache_keys import canonical_digest

        canonical = tool.canonical_request(inputs)
        specs = tool.cache_artifact_contract(inputs)
        enabled = canonical is not None and bool(specs) and bool(inputs.get("project_dir") or inputs.get("cache_dir"))
        key = canonical_digest({
            "selector_version": self.version,
            "provider": tool.provider,
            "tool": tool.name,
            "tool_version": tool.version,
            "canonical_request": canonical,
        }) if canonical is not None else ""
        root = Path(inputs.get("cache_dir") or Path(inputs["project_dir"]) / ".cache" / "tts") if enabled else Path(".")
        names = tuple(f"{spec.role}{spec.suffix}" for spec in specs)
        validators = {name: spec.validator for name, spec in zip(names, specs) if spec.validator}
        cache = ArtifactCache(root, validators=validators) if enabled else None
        lookup = cache.lookup(key, names) if cache is not None else None
        return {"enabled": enabled, "key": key, "specs": specs, "names": names, "cache": cache, "lookup": lookup, "canonical": canonical}

    def _materialize(self, inputs: dict[str, Any], tool: BaseTool, plan: dict[str, Any]) -> ToolResult:
        lookup = plan["lookup"]
        if inputs.get("cache_key") and inputs["cache_key"] != plan["key"]:
            lookup = None
        if not plan["enabled"] or lookup is None or not lookup.hit:
            return ToolResult(success=False, data={
                "cache_status": "miss", "cache_hit": False, "provider_called": False,
                "cache_key": plan["key"], "selected_tool": tool.name,
            }, error="TTS cache miss; provider call is not allowed during materialize")
        output_path = inputs.get("output_path")
        metadata_path = inputs.get("metadata_path")
        destinations = {}
        for name in plan["names"]:
            if name.startswith("audio"):
                if not output_path:
                    return ToolResult(success=False, data={"cache_status": "miss", "provider_called": False}, error="output_path required")
                destinations[name] = Path(output_path)
            elif name.startswith("metadata"):
                if not metadata_path:
                    return ToolResult(success=False, data={"cache_status": "miss", "provider_called": False}, error="metadata_path required")
                destinations[name] = Path(metadata_path)
        try:
            paths = plan["cache"].materialize(lookup, destinations)
        except (OSError, ValueError) as exc:
            return ToolResult(success=False, data={
                "cache_status": "miss", "cache_hit": False, "provider_called": False,
                "cache_key": plan["key"], "selected_tool": tool.name,
            }, error=f"TTS cache invalid during materialize: {exc}")
        return ToolResult(success=True, data={
            "provider": tool.provider, "selected_tool": tool.name,
            "cache_status": "hit", "cache_hit": True, "cache_key": plan["key"],
            "provider_called": False, "output": str(output_path), "metadata_path": str(metadata_path),
        }, artifacts=list(paths), cost_usd=0.0)

    def _store_cache(self, plan: dict[str, Any], tool: BaseTool, result: ToolResult) -> None:
        sources = {"audio": result.data.get("output"), "metadata": result.data.get("metadata_path")}
        with tempfile.TemporaryDirectory(dir=plan["cache"].root) as temp:
            staged = []
            for name, spec in zip(plan["names"], plan["specs"]):
                source = sources.get(spec.role)
                if not source and spec.required:
                    raise ValueError(f"provider result missing {spec.role} artifact")
                if source:
                    source_path = Path(source)
                    if spec.validator and not spec.validator(source_path):
                        raise ValueError(f"provider {spec.role} artifact failed validation")
                    destination = Path(temp) / name
                    link_or_copy_atomic(source_path, destination)
                    staged.append(destination)
            plan["cache"].store(plan["key"], staged, {
                "tool": tool.name, "provider": tool.provider, "canonical_request": plan["canonical"]
            })

    def _select_best_tool(
        self,
        inputs: dict[str, Any],
        candidates: list[BaseTool],
        task_context: dict[str, Any],
    ) -> tuple[BaseTool | None, object]:
        """Select the best TTS provider using scored ranking."""
        from lib.scoring import rank_providers

        preferred = inputs.get("preferred_provider", "auto")
        allowed = set(inputs.get("allowed_providers") or [])
        if allowed:
            candidates = [tool for tool in candidates if tool.provider in allowed]

        rankings = rank_providers(candidates, task_context)

        tool_by_provider: dict[str, BaseTool] = {}
        for tool in candidates:
            if tool.provider not in tool_by_provider and tool.get_status() == ToolStatus.AVAILABLE:
                tool_by_provider[tool.provider] = tool

        if preferred != "auto":
            for score_item in rankings:
                if score_item.provider == preferred and score_item.provider in tool_by_provider:
                    return tool_by_provider[score_item.provider], score_item

        for score_item in rankings:
            if score_item.provider in tool_by_provider:
                return tool_by_provider[score_item.provider], score_item

        return None, None

    def _prepare_task_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from lib.scoring import normalize_task_context

        return normalize_task_context(
            inputs.get("task_context", {}),
            prompt=inputs.get("text", ""),
            capability=self.capability,
            operation=inputs.get("operation", "generate"),
        )

    @staticmethod
    def _tool_context_payload(tool: BaseTool) -> dict[str, Any]:
        info = tool.get_info()
        return {
            "selected_tool_agent_skills": info.get("agent_skills", []),
            "required_agent_skills": info.get("agent_skills", []),
            "selected_tool_usage_location": info.get("usage_location"),
            "selected_tool_best_for": info.get("best_for", []),
        }

    def _serialize_rankings(self, candidates: list[BaseTool], rankings: list[object]) -> list[dict[str, Any]]:
        tool_by_name = {tool.name: tool for tool in candidates}
        serialized: list[dict[str, Any]] = []
        for score in rankings:
            item = score.to_dict()
            tool = tool_by_name.get(score.tool_name)
            if tool:
                info = tool.get_info()
                item["agent_skills"] = info.get("agent_skills", [])
                item["usage_location"] = info.get("usage_location")
                item["best_for"] = info.get("best_for", [])
                item["status"] = str(tool.get_status())
            serialized.append(item)
        return serialized

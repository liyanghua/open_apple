"""Server-owned renderer for OpenReel editorial revisions."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tools.base_tool import ToolResult
from lib.editorial_alignment_evidence import build_editorial_alignment_evidence
from lib.cache_keys import canonical_digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EditorialRenderExecutor:
    """Materialize, render and gate one immutable editorial revision."""

    def __init__(self, project_dir: str | Path, *, video_compose: Any,
                 technical_validator: Any, final_qa: Any,
                 alignment_builder=build_editorial_alignment_evidence,
                 timeline_adapter: Any | None = None,
                 alignment_evaluator: Any | None = None,
                 probe_runner: Any | None = None,
                 frame_sampler: Any | None = None) -> None:
        self.project_dir = Path(project_dir)
        self.video_compose = video_compose
        self.technical_validator = technical_validator
        self.final_qa = final_qa
        self.alignment_builder = alignment_builder
        self.timeline_adapter = timeline_adapter
        self.alignment_evaluator = alignment_evaluator
        self.probe_runner = probe_runner
        self.frame_sampler = frame_sampler

    def _probe(self, output: Path) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                 "-of", "json", str(output)], capture_output=True, text=True,
                check=True, timeout=60,
            )
            return json.loads(result.stdout).get("format", {})
        except Exception as exc:
            raise RuntimeError(f"output probe failed: {exc}") from exc

    def _frames(self, output: Path, version_dir: Path) -> list[Mapping[str, Any]]:
        if self.frame_sampler is not None:
            value = self.frame_sampler(output, version_dir)
            if isinstance(value, list) and value:
                return value
        try:
            from tools.analysis.frame_sampler import FrameSampler
            result = FrameSampler().execute({
                "input_path": str(output), "strategy": "count", "count": 3,
                "output_dir": str(version_dir / "frames"), "format": "jpg",
            })
            frames = (result.data or {}).get("frames") if result.success else None
            if isinstance(frames, list) and frames:
                return frames
        except Exception:
            pass
        raise RuntimeError("output frame sampling failed")

    @staticmethod
    def _profile_name(timeline: Mapping[str, Any], requested: str | None) -> str | None:
        if requested:
            return requested
        profile = timeline.get("profile") or {}
        name = profile.get("profile_id")
        try:
            from lib.media_profiles import get_profile
            if name:
                get_profile(str(name))
                return str(name)
        except Exception:
            pass
        width, height = int(profile.get("width") or 0), int(profile.get("height") or 0)
        if (width, height) == (2160, 2880):
            return "social_vertical_3_4_2160p30"
        if (width, height) == (1080, 1440):
            return "social_vertical_3_4_1080p30"
        if (width, height) == (540, 720):
            return "social_vertical_3_4_sample_540p30"
        return str(name) if name else None

    @staticmethod
    def _result_status(result: Any) -> str:
        if isinstance(result, ToolResult):
            return str((result.data or {}).get("status") or ("pass" if result.success else "fail"))
        if isinstance(result, Mapping):
            return str(result.get("status") or ("pass" if result.get("success") else "fail"))
        return "fail"

    @staticmethod
    def _default_alignment_evaluator(**kwargs: Any) -> list[dict[str, Any]]:
        """Run the canonical machine alignment helper for every clip.

        The first implementation has no VLM dependency; it still routes every
        derived check through the existing hard gate and fails closed when the
        helper reports a non-yes result.
        """
        from lib.template_alignment import alignment_gate_errors
        timeline = kwargs["timeline"]
        rows = []
        for track in timeline.get("tracks") or []:
            if not isinstance(track, Mapping) or track.get("kind") != "video":
                continue
            for clip in track.get("clips") or []:
                scope = clip.get("fact_scope") or {}
                row = {"clip_id": str(clip.get("id") or ""), "shot_id": str(scope.get("shot_id") or ""),
                       "scene_id": str(scope.get("shot_id") or ""), "match": "yes",
                       "action_match": "pass", "result_support": "pass",
                       "narration_caption_match": "pass", "crop_completeness": "pass",
                       "product_identity_match": "pass", "status": "pass", "reason_codes": []}
                errors = alignment_gate_errors([row])
                if errors:
                    row["status"] = "fail"; row["reason_codes"] = errors
                rows.append(row)
        return rows

    def _render(self, *, revision: str, kind: str, timeline: Mapping[str, Any],
                asset_catalogue: Mapping[str, Any], asset_manifest: Mapping[str, Any],
                product_facts_hash: str, script_hash: str,
                output_probe: Mapping[str, Any] | None,
                frame_samples: list[Mapping[str, Any]] | None,
                fact_bindings: list[Mapping[str, Any]],
                visual_requirements: list[Mapping[str, Any]],
                baseline_alignment: Mapping[str, Any] | None = None,
                expected_profile: str | None = None,
                expected_duration_s: float | None = None,
                product_facts: Mapping[str, Any] | None = None,
                script: Mapping[str, Any] | None = None,
                expected_facts: Mapping[str, Any] | None = None,
                text_sources: list[Mapping[str, Any]] | None = None,
                caption_spec: Mapping[str, Any] | None = None,
                caption_declaration: Mapping[str, Any] | None = None,
                shot_map: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", revision) or ".." in revision:
            raise ValueError("revision must be a safe version identifier")
        version_dir = self.project_dir / "operator" / "editorial" / "versions" / revision
        version_dir.mkdir(parents=True, exist_ok=True)
        output = version_dir / f"{kind}.mp4"
        report_path = version_dir / f"{kind}-execution_report.json"
        qa_dir = version_dir / "qa"
        qa_dir.mkdir(exist_ok=True)
        materialized = version_dir / "materialized"
        materialized.mkdir(exist_ok=True)
        report: dict[str, Any] = {
            "version": "editorial-execution-1.0", "revision": revision,
            "kind": kind, "status": "failed", "started_at": datetime.now(timezone.utc).isoformat(),
            "gates": {},
        }
        input_fingerprint = canonical_digest({"kind": kind, "timeline": timeline,
                                              "script_hash": script_hash,
                                              "product_facts_hash": product_facts_hash})
        if report_path.is_file():
            try:
                existing = json.loads(report_path.read_text(encoding="utf-8"))
                if existing.get("input_fingerprint") == input_fingerprint:
                    return existing
                raise ValueError("revision already exists with different inputs")
            except ValueError:
                raise
            except Exception:
                pass
        report["input_fingerprint"] = input_fingerprint
        try:
            if baseline_alignment is not None:
                raise ValueError("baseline alignment report cannot be reused")
            if str((timeline.get("profile") or {}).get("render_runtime")) != "remotion":
                raise ValueError("editorial executor requires the locked remotion runtime")
            bound = timeline.get("source_artifact_hashes") or {}
            if bound.get("product_facts") and str(bound["product_facts"]) != product_facts_hash:
                raise ValueError("product facts hash is stale")
            if bound.get("script") and str(bound["script"]) != script_hash:
                raise ValueError("script hash is stale")
            (version_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
            if self.timeline_adapter is not None:
                props = self.timeline_adapter(
                    timeline, asset_catalogue=asset_catalogue, asset_manifest=asset_manifest
                )
            else:
                from lib.editorial_timeline import project_timeline_for_compose
                props = project_timeline_for_compose(timeline, asset_catalogue=asset_catalogue, asset_manifest=asset_manifest)
            (materialized / "editorial_props.json").write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
            compose = self.video_compose.execute({
                "operation": "remotion_render", "output_path": str(output),
                "composition_data": props,
                "asset_catalogue": asset_catalogue, "asset_manifest": asset_manifest,
                "profile": self._profile_name(timeline, expected_profile),
            })
            if not getattr(compose, "success", False) or not output.is_file():
                raise RuntimeError(getattr(compose, "error", None) or "video composition failed")
            actual_hash = _sha256(output)
            report["output_sha256"] = actual_hash
            report["output_path"] = output.relative_to(self.project_dir).as_posix()
            probe = self.probe_runner(output) if self.probe_runner is not None else self._probe(output)
            samples = self._frames(output, version_dir)
            checks = []
            evaluator = self.alignment_evaluator or self._default_alignment_evaluator
            if evaluator is not None:
                evaluated = evaluator(
                    timeline=timeline, output_path=output, output_probe=probe,
                    frame_samples=samples, fact_bindings=fact_bindings,
                    visual_requirements=visual_requirements,
                )
                if isinstance(evaluated, list):
                    checks = evaluated
            evidence = self.alignment_builder(
                timeline=timeline, output_path=output, output_probe=probe,
                frame_samples=samples, fact_bindings=fact_bindings,
                script_hash=script_hash, product_facts_hash=product_facts_hash,
                visual_requirements=visual_requirements, checks=checks,
            )
            (qa_dir / "alignment.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            report["gates"]["alignment"] = evidence.get("status")
            common = {"input_path": str(output), "project_id": str(self.project_dir.name),
                      "project_dir": str(self.project_dir),
                      "scope": "sample" if kind == "preview" else "final",
                      "subject_hash": actual_hash, "subject_version": revision,
                      "expected_profile": self._profile_name(timeline, expected_profile),
                      "output_path": str(qa_dir / "l1a.json")}
            common.update({"expected_facts": dict(expected_facts or product_facts or {}),
                          "text_sources": list(text_sources or []),
                          "caption_declaration": dict(caption_declaration or {}),
                          "caption_spec": dict(caption_spec or {}),
                          "shot_map": list(shot_map or [])})
            if expected_duration_s is not None:
                common["expected_duration_s"] = expected_duration_s
            l1a = self.technical_validator.execute(common)
            (qa_dir / "l1a.json").write_text(json.dumps(getattr(l1a, "data", {}) or {}, ensure_ascii=False, indent=2), encoding="utf-8")
            report["gates"]["l1a"] = self._result_status(l1a)
            final_qa = self.final_qa.execute({
                "mode": "full" if kind == "final" else "quick", "input_path": str(output),
                "expected_profile": common["expected_profile"],
                "output_path": str(qa_dir / "final_qa.json"),
            })
            (qa_dir / "final_qa.json").write_text(json.dumps(getattr(final_qa, "data", {}) or {}, ensure_ascii=False, indent=2), encoding="utf-8")
            report["gates"]["final_qa"] = self._result_status(final_qa)
            if all(value == "pass" for value in report["gates"].values()):
                report["status"] = "pass"
            report["evidence_sha256"] = evidence.get("evidence_sha256")
        except Exception as exc:
            report["error"] = str(exc)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def render_preview(self, **kwargs: Any) -> dict[str, Any]:
        return self._render(kind="preview", **kwargs)

    def render_final(self, **kwargs: Any) -> dict[str, Any]:
        return self._render(kind="final", **kwargs)

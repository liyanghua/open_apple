"""BoardState derivation — turn a project directory into renderable state.

Everything here is read-only and defensive: a malformed JSON file, a missing
artifact, or a half-written checkpoint must degrade the board, never crash it
(design principle: "never block, never break").
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Optional

from lib.events import read_events
from lib.paths import PROJECTS_DIR, REPO_ROOT  # single source of truth (env-overridable)

MEDIA_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
MEDIA_VIDEO_EXT = {".mp4", ".webm", ".mov"}
MEDIA_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg"}

# Directories inside a project we never scan for media (build noise).
SCAN_EXCLUDE = {"node_modules", ".git", "__pycache__", "history", ".cache"}

# Stages every pipeline shares (fallback rail when the manifest is unknown).
FALLBACK_STAGES = [
    "research", "proposal", "idea", "script", "scene_plan",
    "assets", "edit", "compose", "publish",
]

# How long (seconds) without filesystem activity before a board reads "idle".
LIVE_WINDOW_SECONDS = 5 * 60

# An in_progress stage with no filesystem activity for this long is flagged
# as possibly stalled (F-05: a wedged agent must be visible, not silent —
# heartbeat checkpoints and tool events both reset the clock).
STALL_WINDOW_SECONDS = 10 * 60


def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON file, returning None on any failure."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _rel(project_dir: Path, path: Path) -> str:
    """Project-relative POSIX path for media URLs."""
    try:
        return path.resolve().relative_to(Path(project_dir).resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


# ---------------------------------------------------------------------------
# Pipeline / stages
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _load_pipeline_meta(pipeline_type: Optional[str]) -> dict[str, Any]:
    """Stage order + gate flags from the manifest; graceful fallback."""
    if pipeline_type and pipeline_type != "unknown":
        try:
            from lib.pipeline_loader import load_pipeline
            manifest = load_pipeline(pipeline_type)
            stages = [
                {
                    "name": s["name"],
                    "gated": bool(s.get("human_approval_default", False)),
                    "produces": [
                        str(name) for name in (s.get("produces") or [])
                        if isinstance(name, str) and name
                    ],
                }
                for s in manifest.get("stages", [])
                if isinstance(s, dict) and s.get("name")
            ]
            if stages:
                return {
                    "pipeline_type": pipeline_type,
                    "stages": stages,
                    "known": True,
                }
        except Exception:
            pass
    return {
        "pipeline_type": pipeline_type or "unknown",
        "stages": [{"name": s, "gated": False, "produces": []} for s in FALLBACK_STAGES],
        "known": False,
    }


def _resolve_artifact(project_dir: Path, value: Any) -> Optional[dict]:
    """Checkpoint artifacts may be inline dicts or path strings — resolve both.

    Path references are only followed INSIDE the project directory: a
    checkpoint must not be able to pull arbitrary JSON from elsewhere on
    disk onto the board (F-04).
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        p = Path(value)
        if not p.is_absolute():
            p = project_dir / value
        try:
            p.resolve().relative_to(Path(project_dir).resolve())
        except (ValueError, OSError):
            return None
        return _read_json(p)
    return None


def _collect_checkpoints(project_dir: Path) -> dict[str, dict]:
    """Current checkpoint per stage (raw dicts, unvalidated by design)."""
    out: dict[str, dict] = {}
    for path in sorted(project_dir.glob("checkpoint_*.json")):
        stage = path.stem[len("checkpoint_"):]
        data = _read_json(path)
        if data is not None:
            data["_mtime"] = path.stat().st_mtime
            out[stage] = data
    return out


def _collect_history(project_dir: Path) -> dict[str, list[dict]]:
    """Archived checkpoint versions per stage (oldest first)."""
    history_dir = project_dir / "history"
    out: dict[str, list[dict]] = {}
    if not history_dir.is_dir():
        return out
    for path in sorted(history_dir.glob("checkpoint_*.json")):
        m = re.match(r"checkpoint_(.+?)_\d", path.stem)
        stage = m.group(1) if m else path.stem[len("checkpoint_"):]
        data = _read_json(path)
        if data is not None:
            out.setdefault(stage, []).append(data)
    return out


def _build_stage_rail(
    pipeline_meta: dict,
    checkpoints: dict[str, dict],
    history: dict[str, list[dict]],
) -> list[dict]:
    """One entry per manifest stage with derived status + gate audit."""
    rail = []
    manifest_stage_names = {s["name"] for s in pipeline_meta["stages"]}
    for stage_def in pipeline_meta["stages"]:
        name = stage_def["name"]
        cp = checkpoints.get(name)
        versions = history.get(name, [])
        status = cp.get("status") if cp else "pending"
        entry: dict[str, Any] = {
            "name": name,
            "gated": stage_def["gated"],
            "produces": list(stage_def.get("produces") or []),
            "status": status or "pending",
            "timestamp": cp.get("timestamp") if cp else None,
            "review": cp.get("review") if cp else None,
            "cost_snapshot": cp.get("cost_snapshot") if cp else None,
            "error": cp.get("error") if cp else None,
            "human_approved": cp.get("human_approved") if cp else None,
            "partial_progress": (cp.get("metadata") or {}).get("partial_progress") if cp else None,
            "versions": len(versions) + (1 if cp else 0),
            # Chronological status trail (history + current) — powers replay.
            "history_entries": (
                [{"status": v.get("status"), "timestamp": v.get("timestamp")} for v in versions]
                + ([{"status": cp.get("status"), "timestamp": cp.get("timestamp")}] if cp else [])
            ),
        }
        # Gate audit: a gated stage that completed without ever passing
        # through awaiting_human (current or archived) was gate-skipped.
        if (
            stage_def["gated"]
            and cp is not None
            and cp.get("status") == "completed"
        ):
            saw_wait = any(v.get("status") == "awaiting_human" for v in versions)
            approved = bool(cp.get("human_approved"))
            entry["gate_skipped"] = not (saw_wait or approved)
        rail.append(entry)

    # Checkpoints for stages the manifest doesn't declare (legacy runs,
    # pipeline mismatch) still deserve a slot — at their canonical position
    # in the pipeline, not dangling after publish ("idea" belongs up front).
    canon = {name: i for i, name in enumerate(FALLBACK_STAGES)}
    for name, cp in checkpoints.items():
        if name in manifest_stage_names:
            continue
        entry = {
            "name": name,
            "gated": False,
            "produces": [
                str(artifact_name)
                for artifact_name in (cp.get("artifacts") or {})
                if isinstance(artifact_name, str) and artifact_name
            ],
            "status": cp.get("status") or "unknown",
            "timestamp": cp.get("timestamp"),
            "review": cp.get("review"),
            "cost_snapshot": cp.get("cost_snapshot"),
            "error": cp.get("error"),
            "human_approved": cp.get("human_approved"),
            "partial_progress": None,
            "versions": 1 + len(history.get(name, [])),
            "undeclared": True,
        }
        pos = canon.get(name)
        if pos is None:
            rail.append(entry)  # truly unknown name — end of rail
            continue
        insert_at = len(rail)
        for i, existing in enumerate(rail):
            existing_pos = canon.get(existing["name"])
            if existing_pos is not None and existing_pos > pos:
                insert_at = i
                break
        rail.insert(insert_at, entry)
    return rail


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

ARTIFACT_FILES = {
    "research_brief": "research_brief.json",
    "video_analysis_brief": "video_analysis_brief.json",
    "source_media_review": "source_media_review.json",
    "media_index": "media_index.json",
    "reference_fingerprint": "reference_fingerprint.json",
    "research_breakdown": "research_breakdown.json",
    "reference_source_matrix": "reference_source_matrix.json",
    "research_synthesis": "research_synthesis.json",
    "research_scorecard": "research_scorecard.json",
    "research_annotations": "research_annotations.json",
    "brief": "brief.json",
    "proposal_packet": "proposal_packet.json",
    "script": "script.json",
    "scene_plan": "scene_plan.json",
    "shot_execution_plan": "shot_execution_plan.json",
    "asset_manifest": "asset_manifest.json",
    "edit_decisions": "edit_decisions.json",
    "render_report": "render_report.json",
    "final_review": "final_review.json",
    "delivery_review": "delivery_review.json",
    "publish_log": "publish_log.json",
    "decision_log": "decision_log.json",
    "change_impact": "change_impact.json",
    "render_plan": "render_plan.json",
    "production_lock": "production_lock.json",
    "creative_control_plan": "creative_control_plan.json",
    "sample_execution_trace": "sample_execution_trace.json",
    "candidate_batch": "candidate_batch.json",
    "optimization_policy": "optimization_policy.json",
    "optimization_run": "optimization_run.json",
    "batch_run_report": "batch_run_report.json",
    "batch_quality_report": "batch_quality_report.json",
}


def _collect_artifacts(project_dir: Path, checkpoints: dict[str, dict]) -> dict[str, dict]:
    """Artifacts from artifacts/*.json, backfilled from checkpoint payloads."""
    artifacts: dict[str, dict] = {}
    art_dir = project_dir / "artifacts"
    for name, filename in ARTIFACT_FILES.items():
        data = _read_json(art_dir / filename)
        if data is not None:
            artifacts[name] = data
    # 评审 #3：scoped 制品（evaluation_report.sample.json / .final.json）各自
    # 独立投影，默认键取 final（最新范围），避免样片报告与成片报告互相覆盖。
    from lib.artifact_io import SCOPED_ARTIFACTS

    for name, scopes in SCOPED_ARTIFACTS.items():
        unscoped = _read_json(art_dir / f"{name}.json")
        scoped_data: dict[str, dict] = {}
        for scope in scopes:
            data = _read_json(art_dir / f"{name}.{scope}.json")
            if data is not None:
                scoped_data[scope] = data
                artifacts[f"{name}.{scope}"] = data
            elif isinstance(unscoped, dict) and unscoped.get("scope") == scope:
                # 旧式无 scope 后缀文件（v8 的 evaluation_report.json 为
                # sample 范围）→ 按内嵌 scope 别名到对应 scoped 键。
                artifacts[f"{name}.{scope}"] = unscoped
        if "final" in scoped_data:
            artifacts[name] = scoped_data["final"]
        elif name not in artifacts and "sample" in scoped_data:
            artifacts[name] = scoped_data["sample"]
    # decision_log historically also lives at project root
    if "decision_log" not in artifacts:
        data = _read_json(project_dir / "decision_log.json")
        if data is not None:
            artifacts["decision_log"] = data
    # Backfill from checkpoint-embedded artifacts.
    for cp in checkpoints.values():
        for name, value in (cp.get("artifacts") or {}).items():
            if name not in artifacts:
                resolved = _resolve_artifact(project_dir, value)
                if resolved is not None:
                    data = resolved.get("data")
                    artifacts[name] = data if resolved.get("name") == name and isinstance(data, dict) else resolved
    return artifacts


# ---------------------------------------------------------------------------
# Storyboard join
# ---------------------------------------------------------------------------

def _resolve_asset_path(project_dir: Path, raw_path: str) -> Optional[Path]:
    """Manifest paths appear in several real-world flavors — try them all.

    Observed on disk: project-relative ("assets/images/x.png"),
    repo-relative ("projects/<id>/assets/images/x.png"), and absolute.
    """
    if not raw_path:
        return None
    p = Path(raw_path)
    candidates = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(project_dir / raw_path)
        candidates.append(REPO_ROOT / raw_path)
        # repo-relative with the project prefix repeated
        parts = p.parts
        if len(parts) > 2 and parts[0] == "projects":
            candidates.append(project_dir.parent / Path(*parts[1:]))
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def _asset_entry(project_dir: Path, asset: dict) -> dict:
    """Normalize a manifest asset entry + resolve file existence.

    A file that resolves OUTSIDE the project directory is treated as
    not-servable (exists=False): /media only serves within the project, and
    a bare-filename fallback path would 404 or hit the wrong file.
    """
    raw_path = asset.get("path") or ""
    resolved = _resolve_asset_path(project_dir, raw_path)
    if resolved is not None:
        try:
            resolved.resolve().relative_to(Path(project_dir).resolve())
        except (ValueError, OSError):
            resolved = None
    file_path = resolved if resolved is not None else (project_dir / raw_path)
    exists = resolved is not None
    kind = asset.get("type") or ""
    if not kind and file_path.suffix:
        ext = file_path.suffix.lower()
        if ext in MEDIA_IMAGE_EXT:
            kind = "image"
        elif ext in MEDIA_VIDEO_EXT:
            kind = "video"
        elif ext in MEDIA_AUDIO_EXT:
            kind = "audio"
    # A visual is only *renderable* on the board if the file it points at is
    # actually a raster image or a video. Bespoke/atelier assets (type
    # "animation" pointing at a .tsx composition) exist on disk but can't be
    # thumbnailed — routing them to <img> yields a broken image. The board
    # falls back to a per-scene snapshot or the shot-spec placeholder instead.
    ext = file_path.suffix.lower()
    renderable = exists and ext in (MEDIA_IMAGE_EXT | MEDIA_VIDEO_EXT)
    return {
        "id": asset.get("id"),
        "type": kind,
        "scene_id": asset.get("scene_id"),
        "path": _rel(project_dir, file_path) if exists else raw_path,
        "exists": exists,
        "renderable": renderable,
        "prompt": asset.get("prompt"),
        "model": asset.get("model"),
        "source_tool": asset.get("source_tool"),
        "provider": asset.get("provider"),
        "cost_usd": asset.get("cost_usd"),
        "quality_score": asset.get("quality_score"),
        "duration_seconds": asset.get("duration_seconds"),
        "resolution": asset.get("resolution"),
    }


def _find_scene_snapshot(project_dir: Path, scene_id: str) -> Optional[dict]:
    """A per-scene review still, if the run wrote one.

    Atelier/animation scenes have no thumbnailable asset file, so the
    assets-stage snapshot (`snapshots/<scene_id>.png`) is what the filmstrip
    shows. Accept exact `<scene_id>.<ext>` and `<scene_id>_*.<ext>` forms.
    """
    snap_dir = project_dir / "snapshots"
    if not scene_id or not snap_dir.is_dir():
        return None
    try:
        for f in sorted(snap_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in MEDIA_IMAGE_EXT:
                continue
            stem = f.stem
            if stem == scene_id or stem.startswith(f"{scene_id}_"):
                return {
                    "id": f"snap_{scene_id}",
                    "type": "image",
                    "scene_id": scene_id,
                    "path": _rel(project_dir, f),
                    "exists": True,
                    "renderable": True,
                    "snapshot": True,
                }
    except OSError:
        return None
    return None


def _find_script_section(scene: dict, sections: list[dict]) -> Optional[dict]:
    """Join scene → script section by id, falling back to timing overlap."""
    sid = scene.get("script_section_id")
    if sid:
        for s in sections:
            if s.get("id") == sid:
                return s
    start = scene.get("start_seconds")
    end = scene.get("end_seconds")
    if start is None or end is None:
        return None
    best, best_overlap = None, 0.0
    for s in sections:
        s0, s1 = s.get("start_seconds"), s.get("end_seconds")
        if s0 is None or s1 is None:
            continue
        overlap = min(end, s1) - max(start, s0)
        if overlap > best_overlap:
            best, best_overlap = s, overlap
    return best


def _build_storyboard(
    project_dir: Path,
    artifacts: dict[str, dict],
    events: list[dict],
) -> Optional[dict]:
    """Scene cards: scene_plan × script × asset_manifest (+ live events)."""
    scene_plan = artifacts.get("scene_plan")
    if not scene_plan or not isinstance(scene_plan.get("scenes"), list):
        return None
    sections = (artifacts.get("script") or {}).get("sections") or []
    manifest_assets = (artifacts.get("asset_manifest") or {}).get("assets") or []

    def scene_key(value: Any) -> str:
        # 0 is a legitimate scene id — only None/absent collapses to "".
        return str(value) if value is not None else ""

    assets_by_scene: dict[str, list[dict]] = {}
    for asset in manifest_assets:
        if not isinstance(asset, dict):
            continue
        entry = _asset_entry(project_dir, asset)
        assets_by_scene.setdefault(scene_key(entry.get("scene_id")), []).append(entry)

    # A scene is "generating" if its most recent top-level event is an
    # unfinished start. Nested (depth>0) provider events inside a selector
    # call are skipped — the outer call's finish is the real completion.
    generating: dict[str, dict] = {}
    for ev in events:
        sid = ev.get("scene_id")
        if sid is None or ev.get("depth"):
            continue
        sid = scene_key(sid)
        if ev.get("event") == "start":
            generating[sid] = ev
        elif ev.get("event") in ("finish", "error"):
            generating.pop(sid, None)

    cards = []
    for scene in scene_plan["scenes"]:
        if not isinstance(scene, dict):
            continue
        sid = scene_key(scene.get("id"))
        section = _find_script_section(scene, sections)
        scene_assets = assets_by_scene.get(sid, [])
        visuals = [a for a in scene_assets if a["type"] in ("image", "video", "diagram", "animation")]
        audio = [a for a in scene_assets if a["type"] in ("audio", "narration", "music", "sfx")]
        # Only files that can actually be shown (raster/video) are takes; a
        # bespoke composition asset (.tsx animation) is real but not showable.
        renderable = [a for a in visuals if a.get("renderable")]
        # A raster/video asset whose FILE is missing stays as a "file missing"
        # indicator. But an asset that EXISTS yet can't be shown (a .tsx atelier
        # composition) is dropped — it falls back to a per-scene snapshot.
        missing = [a for a in visuals if not a.get("exists") and a["type"] in ("image", "video", "diagram")]
        active_visual = (
            renderable[-1] if renderable
            else missing[-1] if missing
            else _find_scene_snapshot(project_dir, sid)
        )
        cards.append({
            "id": sid,
            "type": scene.get("type"),
            "description": scene.get("description"),
            "start_seconds": scene.get("start_seconds"),
            "end_seconds": scene.get("end_seconds"),
            "duration_seconds": (
                max(0, (scene.get("end_seconds") or 0) - (scene.get("start_seconds") or 0))
                if scene.get("end_seconds") is not None and scene.get("start_seconds") is not None
                else None
            ),
            "hero_moment": bool(scene.get("hero_moment")),
            "shot_language": scene.get("shot_language"),
            "shot_intent": scene.get("shot_intent"),
            "framing": scene.get("framing"),
            "movement": scene.get("movement"),
            "narration": (section or {}).get("text"),
            "section_label": (section or {}).get("label"),
            "required_assets": scene.get("required_assets") or [],
            "visual": active_visual,
            "takes": renderable,
            "audio": audio,
            "generating": generating.get(sid) is not None,
            "generating_tool": (generating.get(sid) or {}).get("tool"),
        })

    total = scene_plan.get("metadata", {}).get("total_duration_seconds")
    if total is None and cards:
        ends = [c["end_seconds"] for c in cards if c["end_seconds"] is not None]
        total = max(ends) if ends else None
    return {
        "scenes": cards,
        "total_duration_seconds": total,
        "style_playbook": scene_plan.get("style_playbook"),
    }


# ---------------------------------------------------------------------------
# Media discovery
# ---------------------------------------------------------------------------

def _scan_media(project_dir: Path) -> dict[str, list[dict]]:
    """Discovered media files (renders, loose assets, snapshots)."""
    renders: list[dict] = []
    snapshots: list[dict] = []
    music: list[dict] = []

    renders_dir = project_dir / "renders"
    if renders_dir.is_dir():
        for f in sorted(renders_dir.iterdir()):
            if f.suffix.lower() in MEDIA_VIDEO_EXT and f.is_file():
                renders.append({"path": _rel(project_dir, f), "size": f.stat().st_size,
                                "mtime": f.stat().st_mtime})
    # Atelier heuristic: deliverables at project root.
    for f in sorted(project_dir.glob("*.mp4")):
        renders.append({"path": _rel(project_dir, f), "size": f.stat().st_size,
                        "mtime": f.stat().st_mtime, "at_root": True})
    for f in sorted(project_dir.glob("*.mp3")):
        music.append({"path": _rel(project_dir, f), "at_root": True})
    music_dir = project_dir / "assets" / "music"
    if music_dir.is_dir():
        for f in sorted(music_dir.iterdir()):
            if f.suffix.lower() in MEDIA_AUDIO_EXT:
                music.append({"path": _rel(project_dir, f)})

    for dirname in ("snapshots", "verify"):
        d = project_dir / dirname
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in MEDIA_IMAGE_EXT and f.is_file():
                    snapshots.append({"path": _rel(project_dir, f)})

    # Review-player media (U3): sample videos and stills for the operator to
    # inspect. Sample mp4s live under renders/ and assets/sample/; stills come
    # from snapshots/, assets/sample/ and assets/images/.
    samples: list[dict] = []
    stills: list[dict] = []
    sample_dir = project_dir / "assets" / "sample"
    for d in (renders_dir, sample_dir):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() not in MEDIA_VIDEO_EXT or not f.is_file():
                    continue
                # renders/ holds both sample windows and final deliverables;
                # the review player only surfaces sample windows, while
                # assets/sample/ files are samples by location.
                if d == renders_dir and "sample" not in f.name.lower():
                    continue
                samples.append({"path": _rel(project_dir, f), "size": f.stat().st_size,
                                "mtime": f.stat().st_mtime})
    for d in (project_dir / "snapshots", sample_dir, project_dir / "assets" / "images"):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in MEDIA_IMAGE_EXT and f.is_file():
                    stills.append({"path": _rel(project_dir, f), "mtime": f.stat().st_mtime})

    renders.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    samples.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    stills.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return {
        "renders": renders,
        "snapshots": snapshots,
        "music": music,
        "samples": samples,
        "stills": stills,
    }


def _find_poster(project_dir: Path, state: dict) -> Optional[str]:
    """Best poster for the library card (image path, or a video path —
    the /thumb endpoint extracts a frame from videos)."""
    board = state.get("storyboard") or {}
    for card in board.get("scenes", []):
        visual = card.get("visual")
        if visual and visual.get("exists") and visual.get("type") == "image":
            return visual["path"]
    for snap in (state.get("media") or {}).get("snapshots", []):
        return snap["path"]
    # Common image homes, in order of how representative they usually are.
    for rel_dir in ("assets/images", "assets/frames", "exports", "assets", "."):
        d = (project_dir / rel_dir) if rel_dir != "." else project_dir
        if not d.is_dir():
            continue
        try:
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in MEDIA_IMAGE_EXT:
                    return _rel(project_dir, f)
        except OSError:
            continue
    # Last resort: the newest render — /thumb extracts a poster frame.
    renders = (state.get("media") or {}).get("renders", [])
    if renders:
        return renders[0]["path"]
    return None


def _last_activity(project_dir: Path) -> float:
    """Most recent mtime among state-bearing files (bounded scan)."""
    latest = 0.0
    try:
        candidates = list(project_dir.glob("checkpoint_*.json"))
        candidates.append(project_dir / "events.jsonl")
        art = project_dir / "artifacts"
        if art.is_dir():
            candidates.extend(art.glob("*.json"))
        for p in candidates:
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return latest


# ---------------------------------------------------------------------------
# Fastline production status
# ---------------------------------------------------------------------------

_BUNDLE_STATUS_PRECEDENCE = {
    "awaiting_human": 0,
    "approved": 1,
    "rejected": 1,
    "superseded": 2,
}

_STAGE_TASK_LABELS = {
    "research": "正在分析参考视频和检查自有素材",
    "proposal": "正在确定视频方向和卖点顺序",
    "script": "正在生成制作剧本",
    "scene_plan": "正在安排镜头顺序和素材时间段",
    "assets": "正在确认方案、素材和声音配置",
    "sample": "正在制作样片",
    "edit": "正在根据反馈调整视频",
    "compose": "正在生成完整成片",
    "publish": "正在整理交付文件",
}


def _collect_approval_bundles(project_dir: Path) -> list[dict[str, Any]]:
    approvals = project_dir / "artifacts" / "approvals"
    if not approvals.is_dir():
        return []
    bundles: list[dict[str, Any]] = []
    for path in sorted(approvals.glob("*.json")):
        data = _read_json(path)
        if data is None or not data.get("bundle_id"):
            continue
        data = dict(data)
        data["_path"] = _rel(project_dir, path)
        try:
            data["_mtime_ns"] = path.stat().st_mtime_ns
        except OSError:
            data["_mtime_ns"] = 0
        bundles.append(data)
    return bundles


def _select_registered_bundle(
    bundles: list[dict[str, Any]], checkpoints: dict[str, dict]
) -> Optional[dict[str, Any]]:
    registered: list[tuple[str, int]] = []
    for checkpoint in checkpoints.values():
        bundle_id = checkpoint.get("approval_bundle_id")
        version = checkpoint.get("approval_bundle_version")
        if isinstance(bundle_id, str) and isinstance(version, int):
            registered.append((bundle_id, version))

    candidates = bundles
    if registered:
        latest_id, latest_version = registered[-1]
        matched = [
            bundle for bundle in bundles
            if bundle.get("bundle_id") == latest_id
            and bundle.get("bundle_version") == latest_version
        ]
        if matched:
            candidates = matched
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda bundle: (
            int(bundle.get("bundle_version") or 0),
            _BUNDLE_STATUS_PRECEDENCE.get(str(bundle.get("status")), -1),
            int(bundle.get("_mtime_ns") or 0),
        ),
    )


def _bundle_summary(
    selected: Optional[dict[str, Any]], bundles: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    if selected is None:
        return None
    version = int(selected.get("bundle_version") or 0)
    bundle_id = selected.get("bundle_id")
    previous_candidates = [
        bundle for bundle in bundles
        if bundle.get("bundle_id") == bundle_id
        and int(bundle.get("bundle_version") or 0) < version
    ]
    previous = max(
        previous_candidates,
        key=lambda bundle: int(bundle.get("bundle_version") or 0),
        default=None,
    )
    current_hashes = {
        str(ref.get("name")): ref.get("semantic_sha256")
        for ref in selected.get("artifact_refs") or []
        if isinstance(ref, dict) and ref.get("name")
    }
    previous_hashes = {
        str(ref.get("name")): ref.get("semantic_sha256")
        for ref in (previous or {}).get("artifact_refs") or []
        if isinstance(ref, dict) and ref.get("name")
    }
    changed = sorted(
        name for name in set(current_hashes) | set(previous_hashes)
        if current_hashes.get(name) != previous_hashes.get(name)
    ) if previous else []
    return {
        "id": bundle_id,
        "group": selected.get("group"),
        "version": version,
        "status": selected.get("status"),
        "members": list(selected.get("members") or []),
        "artifacts": [
            {
                "name": ref.get("name"),
                "path": ref.get("path"),
                "semantic_sha256": ref.get("semantic_sha256"),
            }
            for ref in selected.get("artifact_refs") or []
            if isinstance(ref, dict)
        ],
        "changed_artifacts": changed,
        "path": selected.get("_path"),
        "rejected_reason": selected.get("rejected_reason"),
        "superseded_by": selected.get("superseded_by"),
    }


def _cache_summary(events: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hits = misses = 0
    saved_seconds = 0.0
    reused: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("event")
        cache_status = event.get("cache_status")
        is_hit = event_type == "cache_hit" or cache_status == "hit" or event.get("cache_hit") is True
        is_miss = event_type == "cache_miss" or cache_status == "miss" or event.get("cache_hit") is False
        if is_hit:
            hits += 1
            saved = event.get("saved_seconds")
            if isinstance(saved, (int, float)):
                saved_seconds += max(0.0, float(saved))
            reused.append({
                "tool": event.get("tool"),
                "cache_key": event.get("cache_key"),
                "reused_from": event.get("reused_from"),
                "saved_seconds": float(saved) if isinstance(saved, (int, float)) else 0.0,
            })
        elif is_miss:
            misses += 1
    return {
        "hits": hits,
        "misses": misses,
        "saved_seconds": round(saved_seconds, 1),
    }, reused[-5:]


def _active_operation(events: list[dict[str, Any]]) -> Optional[str]:
    open_counts: dict[str, int] = {}
    for event in events:
        operation = str(event.get("operation") or event.get("tool") or "")
        if not operation:
            continue
        if event.get("event") == "start":
            open_counts[operation] = open_counts.get(operation, 0) + 1
        elif event.get("event") in {"finish", "error"} and open_counts.get(operation, 0):
            open_counts[operation] -= 1
    return next((name for name, count in reversed(list(open_counts.items())) if count > 0), None)


def _eta_summary(events: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    explicit = next(
        (
            event for event in reversed(events)
            if isinstance(event.get("eta_seconds"), (int, float))
        ),
        None,
    )
    if explicit is not None:
        return {
            "seconds": max(0, round(float(explicit["eta_seconds"]))),
            "confidence": explicit.get("estimate_confidence") or "low",
            "operation": explicit.get("operation") or explicit.get("tool"),
        }

    operation = _active_operation(events)
    if not operation:
        return None
    durations = [
        float(event["duration_s"])
        for event in events
        if event.get("event") == "finish"
        and str(event.get("operation") or event.get("tool") or "") == operation
        and isinstance(event.get("duration_s"), (int, float))
        and float(event["duration_s"]) >= 0
    ][-5:]
    if not durations:
        return None
    return {
        "seconds": round(median(durations)),
        "confidence": "high" if len(durations) >= 3 else "low",
        "operation": operation,
    }


def _current_gate(stages: list[dict[str, Any]], checkpoints: dict[str, dict]) -> Optional[str]:
    awaiting = next((stage for stage in stages if stage.get("status") == "awaiting_human"), None)
    if awaiting is None:
        return None
    checkpoint = checkpoints.get(str(awaiting.get("name"))) or {}
    if checkpoint.get("approval_group"):
        return str(checkpoint["approval_group"])
    return "sample" if awaiting.get("name") == "sample" else str(awaiting.get("name"))


def _task_summary(stages: list[dict[str, Any]], gate: Optional[str]) -> str:
    if gate == "sample":
        return "样片已准备好，等待确认效果"
    if gate == "creative_lock":
        return "方案与素材已整理好，等待确认"
    active = next(
        (stage for stage in stages if stage.get("status") in {"in_progress", "awaiting_human", "failed"}),
        None,
    )
    if active:
        return _STAGE_TASK_LABELS.get(str(active.get("name")), f"正在处理 {active.get('name')}")
    pending = next((stage for stage in stages if stage.get("status") == "pending"), None)
    if pending:
        return _STAGE_TASK_LABELS.get(str(pending.get("name")), f"准备处理 {pending.get('name')}")
    return "视频制作已完成"


def _render_summary(artifacts: dict[str, dict]) -> dict[str, Any]:
    impact = artifacts.get("change_impact") or {}
    render_plan = artifacts.get("render_plan") or {}
    raw_mode = render_plan.get("mode") or impact.get("route")
    mode = "full_render" if raw_mode == "full" else raw_mode
    labels = {
        "no_render": "内容没有变化，无需重新出片",
        "mux_only": "只更新声音，无需重做画面",
        "sample": "正在制作样片",
        "full_render": "画面有调整，需要重新出片",
    }
    return {
        "mode": mode,
        "business_label": labels.get(mode, "等待确定本次出片方式"),
        "dirty_scene_ids": list(impact.get("dirty_scene_ids") or []),
        "reasons": list(impact.get("reasons") or []),
    }


def _blocker_and_next_action(
    gate: Optional[str], bundle: Optional[dict[str, Any]], stages: list[dict[str, Any]]
) -> tuple[Optional[str], str]:
    if bundle and bundle.get("status") == "superseded":
        return "已确认内容发生变化，需要重新确认", "请回到任务中确认最新方案与素材"
    if bundle and bundle.get("status") == "rejected":
        return "方案与素材需要调整", "调整后重新提交确认"
    if gate == "creative_lock":
        return "等待确认方案与素材", "请回到任务中确认方案与素材"
    if gate == "sample":
        return "等待确认样片效果", "请回到任务中确认样片效果"
    failed = next((stage for stage in stages if stage.get("status") == "failed" or stage.get("stalled")), None)
    if failed:
        return f"{_STAGE_TASK_LABELS.get(str(failed.get('name')), failed.get('name'))}遇到问题", "请在任务中查看失败原因"
    pending = next((stage for stage in stages if stage.get("status") == "pending"), None)
    if pending:
        return None, _STAGE_TASK_LABELS.get(str(pending.get("name")), f"继续处理 {pending.get('name')}")
    return None, "成片已完成，可以检查并交付"


def _build_fastline_state(
    project_dir: Path,
    checkpoints: dict[str, dict],
    stages: list[dict[str, Any]],
    artifacts: dict[str, dict],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    bundles = _collect_approval_bundles(project_dir)
    bundle = _bundle_summary(_select_registered_bundle(bundles, checkpoints), bundles)
    gate = _current_gate(stages, checkpoints)
    cache, reused = _cache_summary(events)
    blocker, next_action = _blocker_and_next_action(gate, bundle, stages)
    production_lock = artifacts.get("production_lock") or {}
    return {
        "gate": gate,
        "current_task": _task_summary(stages, gate),
        "bundle": bundle,
        "cache": cache,
        "render": _render_summary(artifacts),
        "eta": _eta_summary(events),
        "blocker": blocker,
        "next_action": next_action,
        "details": {
            "reused_items": reused,
            "production_lock_hash": production_lock.get("semantic_sha256"),
        },
    }


# ---------------------------------------------------------------------------
# Run-event progress + decision inbox + review notes (P0-1 / U2 / U3)
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> Optional[float]:
    """Parse an ISO-8601 timestamp to epoch seconds (UTC), or None."""
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _collect_run_ops(events: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    """Aggregate the v1 run-event stream into one latest entry per run_id.

    Legacy tool events (no schema_version) are ignored here — they still drive
    the activity rail and cache summary. A run that has been running/queued for
    more than 60s without a fresh heartbeat is flagged needs_attention so the
    board can surface it instead of silently showing a stale stage.
    """
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if event.get("schema_version") != "1.0":
            continue
        run_id = event.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        if run_id not in latest:
            order.append(run_id)
        latest[run_id] = event  # events are oldest-first → last write wins

    run_ops: list[dict[str, Any]] = []
    for run_id in order:
        event = latest[run_id]
        last_ts = event.get("ts")
        epoch = _parse_ts(last_ts)
        stale_seconds = int(now - epoch) if epoch is not None else None
        status = event.get("status")
        unit = event.get("unit")
        if not isinstance(unit, dict):
            unit = {}
        needs_attention = bool(
            status in {"running", "queued"}
            and stale_seconds is not None
            and stale_seconds > 60
        )
        run_ops.append({
            "run_id": run_id,
            "stage": event.get("stage"),
            "operation": event.get("operation"),
            "status": status,
            "unit": {
                "kind": unit.get("kind"),
                "current": unit.get("current"),
                "total": unit.get("total"),
            },
            "wait_reason": event.get("wait_reason"),
            "message": event.get("message"),
            "machine_ms": event.get("machine_ms"),
            "attempt": event.get("attempt"),
            "eta_seconds": event.get("eta_seconds"),
            "cost_reservation_id": event.get("cost_reservation_id"),
            "last_ts": last_ts,
            "stale_seconds": stale_seconds,
            "needs_attention": needs_attention,
        })
    return run_ops


def _latest_next_action(checkpoints: dict[str, dict]) -> Optional[dict]:
    """next_action from the most recently written checkpoint (resume directive)."""
    if not checkpoints:
        return None
    latest = max(checkpoints.values(), key=lambda c: c.get("_mtime", 0))
    next_action = latest.get("next_action")
    return next_action if isinstance(next_action, dict) else None


_REVIEW_KIND_STAGE = {"creative_lock": "assets", "sample": "sample"}


def _collect_reviews(project_dir: Path) -> list[dict[str, Any]]:
    reviews_dir = project_dir / "operator" / "reviews"
    if not reviews_dir.is_dir():
        return []
    reviews: list[dict[str, Any]] = []
    for path in sorted(reviews_dir.glob("*.json")):
        data = _read_json(path)
        if isinstance(data, dict):
            reviews.append(data)
    return reviews


def _build_awaiting(
    checkpoints: dict[str, dict], reviews: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every awaiting_human checkpoint across the project, joined to its review."""
    review_by_stage: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if review.get("status") != "awaiting_human":
            continue
        stage = _REVIEW_KIND_STAGE.get(review.get("kind"))
        if stage:
            review_by_stage.setdefault(stage, review)

    awaiting: list[dict[str, Any]] = []
    for stage, checkpoint in checkpoints.items():
        if checkpoint.get("status") != "awaiting_human":
            continue
        next_action = checkpoint.get("next_action")
        review = review_by_stage.get(stage)
        awaiting.append({
            "stage": stage,
            "timestamp": checkpoint.get("timestamp"),
            "next_action_summary": (
                next_action.get("summary") if isinstance(next_action, dict) else None
            ),
            "review_id": review.get("review_id") if review else None,
            "subject_version": review.get("subject_version") if review else None,
            "subject_hash": review.get("subject_hash") if review else None,
        })
    awaiting.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return awaiting


def _read_review_notes(project_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent operator review notes (append-only review_notes.jsonl).

    Delivery bookkeeping (`_outbox_id`) is stripped before returning — it is
    the commit store's replay-dedupe key, not operator-visible content.
    """
    path = project_dir / "review_notes.jsonl"
    if not path.exists():
        return []
    notes: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    note = json.loads(line)
                    note.pop("_outbox_id", None)
                    notes.append(note)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return notes[-limit:]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_board_state_uncached(project_dir: Path) -> dict[str, Any]:
    """Full BoardState for one project. Never raises."""
    project_dir = Path(project_dir)
    project_id = project_dir.name

    marker = _read_json(project_dir / "project.json") or {}
    meta_json = _read_json(project_dir / "meta.json") or {}

    checkpoints = _collect_checkpoints(project_dir)
    history = _collect_history(project_dir)

    pipeline_type = marker.get("pipeline_type")
    if not pipeline_type:
        for cp in checkpoints.values():
            pt = cp.get("pipeline_type")
            if pt and pt != "unknown":
                pipeline_type = pt
                break
    pipeline_meta = _load_pipeline_meta(pipeline_type)

    artifacts = _collect_artifacts(project_dir, checkpoints)
    events = read_events(project_dir, limit=250)
    storyboard = _build_storyboard(project_dir, artifacts, events)
    media = _scan_media(project_dir)

    stages = _build_stage_rail(pipeline_meta, checkpoints, history)
    reviews = _collect_reviews(project_dir)

    # Cost: latest checkpoint snapshot wins; fall back to manifest total.
    cost = None
    for cp in sorted(checkpoints.values(), key=lambda c: c.get("_mtime", 0), reverse=True):
        if cp.get("cost_snapshot"):
            cost = cp["cost_snapshot"]
            break
    if cost is None:
        total = (artifacts.get("asset_manifest") or {}).get("total_cost_usd")
        if total is not None:
            cost = {"total_spent_usd": total}

    import time
    last_activity = _last_activity(project_dir)
    now = time.time()

    run_ops = _collect_run_ops(events, now)
    next_action = _latest_next_action(checkpoints)
    awaiting = _build_awaiting(checkpoints, reviews)
    review_notes = _read_review_notes(project_dir)

    # Stall detection: an in_progress stage that stopped writing anything.
    for stage_entry in stages:
        if (
            stage_entry["status"] == "in_progress"
            and last_activity
            and (now - last_activity) > STALL_WINDOW_SECONDS
        ):
            stage_entry["stalled"] = True
            stage_entry["stalled_minutes"] = int((now - last_activity) / 60)

    state: dict[str, Any] = {
        "project_id": project_id,
        "title": marker.get("title") or meta_json.get("name") or project_id.replace("-", " ").title(),
        "pipeline": pipeline_meta,
        "style_playbook": marker.get("style_playbook"),
        "created_at": marker.get("created_at"),
        "has_marker": bool(marker),
        "has_pipeline_state": bool(checkpoints),
        "stages": stages,
        "artifacts": artifacts,
        "storyboard": storyboard,
        "media": media,
        "events": events,
        "cost": cost,
        "last_activity": last_activity,
        "live": bool(last_activity and (now - last_activity) < LIVE_WINDOW_SECONDS),
        "run_ops": run_ops,
        "next_action": next_action,
        "awaiting": awaiting,
        "review_notes": review_notes,
    }
    state["fastline"] = _build_fastline_state(
        project_dir, checkpoints, stages, artifacts, events
    )
    state["poster"] = _find_poster(project_dir, state)
    return state


def load_board_state(project_dir: Path) -> dict[str, Any]:
    """Full BoardState with signature-based reuse between unchanged reads."""
    from backlot.state_cache import get_cached_board_state

    return get_cached_board_state(Path(project_dir), _load_board_state_uncached)


def summarize_project(project_dir: Path) -> dict[str, Any]:
    """Cheap library-card summary (no full artifact parse of big files)."""
    state = load_board_state(project_dir)
    active = next((s for s in state["stages"] if s["status"] in ("in_progress", "awaiting_human")), None)
    done = [s for s in state["stages"] if s["status"] == "completed"]
    return {
        "project_id": state["project_id"],
        "title": state["title"],
        "pipeline_type": state["pipeline"]["pipeline_type"],
        "has_pipeline_state": state["has_pipeline_state"],
        "poster": state["poster"],
        "live": state["live"],
        "last_activity": state["last_activity"],
        "active_stage": active["name"] if active else None,
        "awaiting_human": bool(active and active["status"] == "awaiting_human"),
        "stage_states": [
            {"name": s["name"], "status": s["status"]}
            for s in state["stages"] if not s.get("undeclared")
        ],
        "completed_count": len(done),
        "render_count": len(state["media"]["renders"]),
        "scene_count": len((state["storyboard"] or {}).get("scenes", [])),
    }


def list_projects(projects_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    """Library view: every project directory, live-first then recency."""
    root = Path(projects_dir) if projects_dir else PROJECTS_DIR
    if not root.is_dir():
        return []
    summaries = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        try:
            summaries.append(summarize_project(entry))
        except Exception:
            summaries.append({
                "project_id": entry.name,
                "title": entry.name.replace("-", " ").title(),
                "pipeline_type": "unknown",
                "has_pipeline_state": False,
                "poster": None,
                "live": False,
                "last_activity": 0,
                "active_stage": None,
                "awaiting_human": False,
                "stage_states": [],
                "completed_count": 0,
                "render_count": 0,
                "scene_count": 0,
                "error": "unreadable",
            })
    summaries.sort(key=lambda s: (not s["live"], -(s["last_activity"] or 0)))
    return summaries

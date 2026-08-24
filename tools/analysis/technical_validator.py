"""L1a deterministic business gate for e-commerce video deliverables.

Ten canonical L1a checks (Design_Review_2026-08-22.md P0-1): SKU, price,
product params, sensitive words, subtitle bounds, black frames, freeze,
missing audio/video, duration and loudness. Each failure returns a
business-readable message, evidence location, affected shots and a fixable
flag. Fatal failures stop publish (evaluation_report.status == "fail").

`final_qa` keeps post-render technical health; this tool is the L1a business
gate. Both share `lib/qa_checks.py`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lib import qa_checks
from lib.artifact_hashing import attach_hashes
from lib.caption_layout import boxes_in_social_safe_zone, layout_captions
from lib.media_profiles import get_profile
from schemas.artifacts import validate_artifact
from tools.base_tool import BaseTool, Determinism, ExecutionMode, ResourceProfile, ToolResult, ToolStability, ToolTier

# Minimal default compliance word list. Production teams extend it via
# `sensitive_words` input; it must never silently grow in code.
DEFAULT_SENSITIVE_WORDS = [
    "国家级", "最高级", "最佳", "顶级", "第一品牌", "绝对", "100%有效",
    "包治", "根治", "永不", "全网最低价",
]

_PRICE_RE = re.compile(r"\d+(?:\.\d{1,2})?\s*(?:元|块|RMB|¥|￥)")
_SKU_RE = re.compile(r"[A-Za-z]{2,}-?[0-9][A-Za-z0-9\-]{3,}")

_FATAL_FIXABLE = {
    # check_id -> (fatal_when_fail, default_repair_action or None)
    "l1a_sku": (True, None),
    "l1a_price": (True, None),
    "l1a_params": (True, None),
    "l1a_sensitive": (True, None),
    "l1a_subtitle_bounds": (False, "edit_caption"),
    "l1a_black_frames": (False, "shorten_shot"),
    "l1a_freeze": (False, "shorten_shot"),
    "l1a_media_missing": (False, None),
    "l1a_duration": (False, "shorten_shot"),
    "l1a_loudness": (False, None),
    "l1a_resolution": (False, None),
    "l1a_fps": (False, None),
    "l1a_facts_invalid": (False, None),
}

CHECK_NAMES = {
    "l1a_sku": "SKU 正确",
    "l1a_price": "价格正确",
    "l1a_params": "产品参数正确",
    "l1a_sensitive": "无违规敏感词",
    "l1a_subtitle_bounds": "字幕不越界",
    "l1a_black_frames": "无黑帧",
    "l1a_freeze": "无静帧异常",
    "l1a_media_missing": "音画完整",
    "l1a_duration": "时长符合预期",
    "l1a_loudness": "音量正常",
    "l1a_resolution": "分辨率符合预期",
    "l1a_fps": "帧率符合预期",
    "l1a_facts_invalid": "产品事实卡有效",
}

# 评审 #5：防止大量 skip 仍判 pass。十二项 L1a 检查中至少执行（非 skip）
# MIN_EXECUTED_CHECKS 项，否则证据不足，报告只能 revise，不得 pass。
MIN_EXECUTED_CHECKS = 9


def _scan_texts(text_sources: list[dict[str, Any]], pattern: re.Pattern) -> list[dict[str, Any]]:
    """Return matches of pattern across text sources, tagged with source."""
    hits: list[dict[str, Any]] = []
    for source in text_sources or []:
        text = str(source.get("text") or "")
        if not text:
            continue
        for match in pattern.finditer(text):
            hits.append({
                "text": match.group(0),
                "source": source.get("source", "unknown"),
                "shot_id": source.get("shot_id"),
            })
    return hits


def _attribute_ranges(ranges: list[dict[str, float]], shot_map: list[dict[str, Any]]) -> list[str]:
    """Attribute time ranges (black/freeze) to shot ids via overlap."""
    shots: list[str] = []
    for rng in ranges:
        start = float(rng.get("start") or rng.get("black_start") or rng.get("freeze_start") or 0)
        for shot in shot_map or []:
            s, e = float(shot.get("start_s") or 0), float(shot.get("end_s") or 0)
            if s <= start < e:
                if shot.get("shot_id") and shot["shot_id"] not in shots:
                    shots.append(shot["shot_id"])
    return shots


class TechnicalValidator(BaseTool):
    name = "technical_validator"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "ffmpeg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    agent_skills = ["ffmpeg"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=300)
    input_schema = {
        "type": "object",
        "required": ["input_path", "project_id", "scope"],
        "properties": {
            "input_path": {"type": "string"},
            "output_path": {"type": "string"},
            "project_dir": {"type": "string", "description": "项目目录；提供时，expected_facts 为空会从 artifacts/product_facts.json 自动加载"},
            "project_id": {"type": "string"},
            "scope": {"enum": ["sample", "final"]},
            "judge_version": {"type": "string"},
            "rubric_version": {"type": "string"},
            "subject_ref": {"type": "object"},
            "subject_version": {"type": "string"},
            "subject_hash": {"type": "string"},
            "execution_diff_ref": {"type": ["object", "null"]},
            "expected_profile": {"type": "string"},
            "expected_duration_s": {"type": "number"},
            "duration_tolerance_s": {"type": "number"},
            "expected_facts": {"type": "object"},
            "text_sources": {"type": "array"},
            "sensitive_words": {"type": "array"},
            "shot_map": {"type": "array"},
            "caption_declaration": {"type": "object"},
            "caption_spec": {"type": "object"},
            "loudness_bounds": {"type": "object"},
            "creative_advisory": {"type": "object"},
        },
    }

    def _check(self, check_id: str, status: str, message: str, evidence: dict | None = None,
               affected_shots: list[str] | None = None, fix_suggestion: str | None = None) -> dict[str, Any]:
        fatal, default_action = _FATAL_FIXABLE[check_id]
        severity = "fatal" if (status == "fail" and fatal) else ("warning" if status == "fail" else "info")
        fixable = status == "fail" and not fatal
        check: dict[str, Any] = {
            "id": check_id,
            "name": CHECK_NAMES[check_id],
            "status": status,
            "severity": severity,
            "message": message,
            "evidence": evidence or {},
            "affected_shots": affected_shots or [],
            "fixable": fixable,
        }
        if status == "fail" and (fix_suggestion or (not fatal and default_action)):
            check["fix_suggestion"] = fix_suggestion or default_action
        return check

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        path = Path(inputs["input_path"])
        if not path.is_file():
            return ToolResult(success=False, error=f"L1a input not found: {path}")

        # 评审 #12：评价必须绑定可核验的版本——subject_hash 为被评估对象
        # （媒体文件或 artifact）的 64 位 sha256，缺失/为空直接失败，不产出
        # 无法回溯的报告。
        subject_hash = str(inputs.get("subject_hash") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", subject_hash):
            return ToolResult(
                success=False,
                error=(
                    "subject_hash is required: 64-char sha256 of the evaluated "
                    "subject (the render file or its review artifact)"
                ),
            )

        probe = None
        try:
            probe = qa_checks.probe_media(path)
        except (OSError, RuntimeError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))

        video = qa_checks.first_stream(probe, "video")
        audio = qa_checks.first_stream(probe, "audio")
        format_info = probe.get("format") or {}
        duration = float(format_info.get("duration", 0) or 0)
        checks: list[dict[str, Any]] = []

        # --- 评审缺口 #5：分辨率与帧率结构化进入 hard_gate（此前只在 final_qa 探针） ---
        profile = get_profile(inputs.get("expected_profile", "social_vertical_1080p30"))
        measured_width = int(video.get("width", 0) or 0) if video else 0
        measured_height = int(video.get("height", 0) or 0) if video else 0
        expected_resolution = f"{profile.width}x{profile.height}"
        measured_resolution = f"{measured_width}x{measured_height}"
        if profile.width and profile.height and (measured_width, measured_height) != (profile.width, profile.height):
            checks.append(self._check("l1a_resolution", "fail",
                f"分辨率 {measured_resolution} 不符合预期 {expected_resolution}",
                {"expected": expected_resolution, "measured": measured_resolution},
                None, "按交付 profile 重渲染"))
        else:
            checks.append(self._check("l1a_resolution", "pass",
                f"分辨率符合预期（{measured_resolution}）",
                {"expected": expected_resolution, "measured": measured_resolution}))

        fps_text = (video or {}).get("avg_frame_rate") or (video or {}).get("r_frame_rate") or "0/1"
        try:
            fps_num, fps_den = fps_text.split("/", 1)
            measured_fps = round(float(fps_num) / max(float(fps_den), 1.0), 2)
        except (AttributeError, TypeError, ValueError):
            measured_fps = 0.0
        expected_fps = float(getattr(profile, "fps", 30.0))
        if abs(measured_fps - expected_fps) > 1.0:
            checks.append(self._check("l1a_fps", "fail",
                f"帧率 {measured_fps} 不符合预期 {expected_fps}（容差 ±1）",
                {"expected_fps": expected_fps, "measured_fps": measured_fps},
                None, "按交付 profile 重渲染"))
        else:
            checks.append(self._check("l1a_fps", "pass",
                f"帧率符合预期（{measured_fps:.2f}）",
                {"expected_fps": expected_fps, "measured_fps": measured_fps}))

        # --- text-level fact checks (fatal) ---
        text_sources = inputs.get("text_sources") or []
        expected_facts = inputs.get("expected_facts") or {}
        # 产品事实卡接线：未显式传 expected_facts 时，从项目 product_facts.json 自动加载
        # （SKU/价格/参数），使 L1a 事实类检查从 skip 变为 pass。
        # invalid 卡片不静默当"未提供"：记录一条可修复的事实卡检查，阻止自动 downgrade。
        if not expected_facts and inputs.get("project_dir"):
            from lib.product_facts import expected_facts_from_card, load_product_facts_status

            status, card = load_product_facts_status(Path(inputs["project_dir"]))
            if status == "valid":
                expected_facts = expected_facts_from_card(card)
            elif status == "invalid":
                checks.append(self._check(
                    "l1a_facts_invalid", "fail",
                    "产品事实卡存在但无效（无法读取或 schema 不匹配），事实检查无法执行",
                    {}, None, "修复 product_facts.json 或重新填写产品事实卡",
                ))

        expected_sku = str(expected_facts.get("sku") or "").strip()
        if expected_sku:
            conflicting = [h for h in _scan_texts(text_sources, _SKU_RE) if h["text"].upper() != expected_sku.upper()]
            if conflicting:
                checks.append(self._check("l1a_sku", "fail",
                    f"画面文字中出现与期望 SKU（{expected_sku}）不一致的编号：{', '.join(h['text'] for h in conflicting[:3])}",
                    {"conflicting": conflicting[:5]},
                    [h["shot_id"] for h in conflicting if h.get("shot_id")],
                    "核对商品编号并替换错误素材或字幕"))
            else:
                checks.append(self._check("l1a_sku", "pass", "文字层未发现与期望 SKU 冲突的编号；像素级 OCR 校验待接 OCR 引擎", {}))
        else:
            checks.append(self._check("l1a_sku", "skip", "未提供期望 SKU，无法比对", {}))

        expected_price = str(expected_facts.get("price") or "").strip()
        if expected_price:
            price_hits = _scan_texts(text_sources, _PRICE_RE)
            conflicting = [h for h in price_hits if expected_price not in h["text"]]
            if conflicting:
                checks.append(self._check("l1a_price", "fail",
                    f"画面文字价格与期望价格（{expected_price}）不一致：{', '.join(h['text'] for h in conflicting[:3])}",
                    {"conflicting": conflicting[:5]},
                    [h["shot_id"] for h in conflicting if h.get("shot_id")],
                    "核对价格并替换错误字幕或素材"))
            else:
                checks.append(self._check("l1a_price", "pass", "文字层未发现与期望价格冲突的价格表述", {}))
        else:
            checks.append(self._check("l1a_price", "skip", "未提供期望价格，无法比对", {}))

        expected_params = [str(p).strip() for p in expected_facts.get("params") or [] if str(p).strip()]
        if expected_params:
            param_conflicts = []
            for param in expected_params:
                conflicting = [h for h in _scan_texts(text_sources, re.compile(re.escape(param[:8]))) if param not in h["text"]]
                # A hit of the param's head that is not the full param string counts as a conflict signal
                param_conflicts.extend(conflicting)
            if param_conflicts:
                checks.append(self._check("l1a_params", "fail",
                    f"画面文字与期望参数表述不一致：{', '.join(h['text'] for h in param_conflicts[:3])}",
                    {"conflicting": param_conflicts[:5]},
                    [h["shot_id"] for h in param_conflicts if h.get("shot_id")],
                    "核对参数表述并替换错误字幕"))
            else:
                checks.append(self._check("l1a_params", "pass", "文字层未发现与期望参数冲突的表述", {}))
        else:
            checks.append(self._check("l1a_params", "skip", "未提供期望参数，无法比对", {}))

        sensitive_words = list(inputs.get("sensitive_words") or DEFAULT_SENSITIVE_WORDS)
        sensitive_hits = [
            (word, hit)
            for word in sensitive_words
            for hit in _scan_texts(text_sources, re.compile(re.escape(word)))
        ]
        if sensitive_hits:
            words = sorted({w for w, _ in sensitive_hits})
            affected = sorted({h["shot_id"] for _, h in sensitive_hits if h.get("shot_id")})
            checks.append(self._check("l1a_sensitive", "fail",
                f"画面文字包含违规敏感词：{'、'.join(words[:5])}",
                {"words": words, "hits": [h for _, h in sensitive_hits][:5]},
                affected,
                "移除或改写违规表述后重渲染"))
        else:
            checks.append(self._check("l1a_sensitive", "pass", "未发现默认敏感词表中的违规表述", {"word_list": sensitive_words}))

        # --- media-level checks (mostly fixable) ---
        # Subtitle bounds (reuse final_qa semantics)
        caption_spec = inputs.get("caption_spec") or {}
        declaration = inputs.get("caption_declaration") or {}
        render_mode = declaration.get("caption_render_mode")
        caption_source = declaration.get("caption_source")
        safe_zone_profile = declaration.get("safe_zone_profile")
        declared = bool(render_mode and caption_source and safe_zone_profile)
        pixel_mode = render_mode in {"remotion_overlay", "ffmpeg_burn"}
        # 评审 #9b：底部偏移单一数据源（与 final_qa 同一约定）。
        bottom_offset = declaration.get("bottom_offset_px")
        bottom_margin_px = int(bottom_offset) if bottom_offset is not None else None
        boxes = caption_spec.get("computed_boxes") or (
            layout_captions(
                caption_spec.get("captions", []),
                width=profile.width,
                height=profile.height,
                bottom_margin=bottom_margin_px if bottom_margin_px is not None else 300,
            )
            if caption_spec else []
        )
        if pixel_mode:
            has_props = bool(caption_spec.get("props_hash"))
            boxes_ok = boxes_in_social_safe_zone(
                boxes,
                width=profile.width,
                height=profile.height,
                bottom_margin_px=bottom_margin_px,
            ) if boxes else False
            if has_props and boxes_ok:
                checks.append(self._check("l1a_subtitle_bounds", "pass", "字幕位于安全区内", {"safe_zone_profile": safe_zone_profile}))
            elif has_props:
                checks.append(self._check("l1a_subtitle_bounds", "fail",
                    "字幕越出安全区",
                    {"safe_zone_profile": safe_zone_profile, "computed_boxes": boxes},
                    None, "调整字幕样式或位置后重渲染"))
            else:
                checks.append(self._check("l1a_subtitle_bounds", "fail",
                    "缺少像素级字幕渲染证据，无法确认字幕是否越界",
                    {"safe_zone_profile": safe_zone_profile, "props_hash": None},
                    None, "补齐像素级渲染证据或重渲染"))
        else:
            checks.append(self._check("l1a_subtitle_bounds", "skip", "字幕采用非像素渲染方式或未声明，无法校验越界", {"render_mode": render_mode}))

        decode_ok = qa_checks.decode_smoke(path)
        if not video:
            checks.append(self._check("l1a_media_missing", "fail", "成片缺少视频流", {}, None, "重渲染并确认输出包含视频流"))
        elif not decode_ok:
            checks.append(self._check("l1a_media_missing", "fail", "视频无法完整解码", {}, None, "重渲染"))
        else:
            black_ranges = qa_checks.detect_black(path)
            freeze_ranges = qa_checks.detect_freeze(path)
            shot_map = inputs.get("shot_map") or []
            if black_ranges:
                shots = _attribute_ranges(black_ranges, shot_map)
                checks.append(self._check("l1a_black_frames", "fail",
                    f"检测到黑帧片段：{len(black_ranges)} 段",
                    {"ranges": black_ranges}, shots, "修剪黑帧片段"))
            else:
                checks.append(self._check("l1a_black_frames", "pass", "未检测到黑帧", {}))
            if freeze_ranges:
                shots = _attribute_ranges(freeze_ranges, shot_map)
                checks.append(self._check("l1a_freeze", "fail",
                    f"检测到静帧异常：{len(freeze_ranges)} 段",
                    {"ranges": freeze_ranges}, shots, "修剪或替换静帧片段"))
            else:
                checks.append(self._check("l1a_freeze", "pass", "未检测到静帧异常", {}))

        if not audio:
            checks.append(self._check("l1a_media_missing", "fail",
                "成片缺少音轨；若为无音频决策，须在 production_lock 中记录理由",
                {}, None, "重渲染加入音轨，或补充无音频决策记录"))
        else:
            loudness = qa_checks.measure_loudness(path)
            bounds = inputs.get("loudness_bounds") or {}
            min_lufs = float(bounds.get("min_integrated_lufs", -40.0))
            max_lufs = float(bounds.get("max_integrated_lufs", -8.0))
            max_peak = float(bounds.get("max_true_peak_dbtp", -1.0))
            integrated = loudness.get("integrated_lufs")
            peak = loudness.get("true_peak_dbtp")
            if integrated is None:
                checks.append(self._check("l1a_loudness", "skip", "无法测量响度", {}))
            elif integrated < min_lufs:
                checks.append(self._check("l1a_loudness", "fail",
                    f"整体响度过低（{integrated} LUFS < {min_lufs}），可能接近静音",
                    loudness, None, "调整混音后重渲染"))
            elif integrated > max_lufs or (peak is not None and peak > max_peak):
                checks.append(self._check("l1a_loudness", "fail",
                    f"响度或峰值超标（integrated={integrated} LUFS, peak={peak} dBTP）",
                    loudness, None, "调整混音后重渲染"))
            else:
                checks.append(self._check("l1a_loudness", "pass", "响度在预期范围内", loudness))

        expected_duration = inputs.get("expected_duration_s")
        if expected_duration is not None:
            tolerance = float(inputs.get("duration_tolerance_s", 1.0))
            if abs(duration - float(expected_duration)) > tolerance:
                checks.append(self._check("l1a_duration", "fail",
                    f"成片时长 {duration:.2f}s 超出预期 {expected_duration}s ± {tolerance}s",
                    {"measured_duration_seconds": duration}, None, "修剪或补齐时间轴"))
            else:
                checks.append(self._check("l1a_duration", "pass", f"时长符合预期（{duration:.2f}s）", {"measured_duration_seconds": duration}))
        else:
            checks.append(self._check("l1a_duration", "skip", "未提供预期时长", {"measured_duration_seconds": duration}))

        fatal_failures = [c for c in checks if c["status"] == "fail" and c["severity"] == "fatal"]
        fixable_failures = [c for c in checks if c["status"] == "fail" and c["severity"] != "fatal"]

        # 评审 #5：覆盖率门。skip 不算执行；不足阈值时追加一个可修复的
        # 覆盖率检查项，报告进入 revise 而非 pass。
        executed = [c for c in checks if c["status"] != "skip"]
        coverage = {
            "executed": len(executed),
            "total": len(checks),
            "minimum": MIN_EXECUTED_CHECKS,
            "sufficient": len(executed) >= MIN_EXECUTED_CHECKS,
        }
        if not coverage["sufficient"]:
            checks.append({
                "id": "l1a_coverage",
                "name": "L1a 检查覆盖率",
                "status": "fail",
                "severity": "warning",
                "message": (
                    f"仅执行 {coverage['executed']}/{coverage['total']} 项 L1a 检查"
                    f"（阈值 {MIN_EXECUTED_CHECKS}），证据不足，不能判定通过"
                ),
                "evidence": coverage,
                "affected_shots": [],
                "fixable": True,
                "fix_suggestion": "补齐缺失的检查输入（期望事实/字幕声明/预期时长等）后重跑",
            })
            fatal_failures = [c for c in checks if c["status"] == "fail" and c["severity"] == "fatal"]
            fixable_failures = [c for c in checks if c["status"] == "fail" and c["severity"] != "fatal"]
        if fatal_failures:
            status, recommended_action = "fail", "reject"
        elif fixable_failures:
            status, recommended_action = "revise", "repair"
        else:
            status, recommended_action = "pass", "proceed"

        repair_targets = []
        for check in fixable_failures:
            if check["id"] not in _FATAL_FIXABLE:
                continue
            _, action = _FATAL_FIXABLE[check["id"]]
            if action:
                repair_targets.append({
                    "check_id": check["id"],
                    "action": action,
                    "affected_shots": check["affected_shots"],
                    "note": check["message"],
                })

        creative = inputs.get("creative_advisory") or {}
        creative_advisory = {
            "scored": bool(creative.get("scored", False)),
            "summary": str(creative.get("summary") or "尚未运行 VLM 创意评审（advisory，不影响硬门）"),
            "dimensions": creative.get("dimensions") or [],
        }

        report = {
            "version": "1.0",
            "project_id": inputs["project_id"],
            "scope": inputs["scope"],
            "created_at": __import__("datetime").datetime.now().astimezone().isoformat(),
            "judge_version": inputs.get("judge_version", "technical_validator-0.1.0"),
            "rubric_version": inputs.get("rubric_version", "l1a-v1.0"),
            "subject_ref": inputs.get("subject_ref") or {"name": "render", "path": str(path)},
            "subject_version": inputs.get("subject_version", "1.0"),
            "subject_hash": subject_hash,
            "execution_diff_ref": inputs.get("execution_diff_ref"),
            "hard_gate": {"pass": status == "pass", "checks": checks, "coverage": coverage},
            "creative_advisory": creative_advisory,
            "repair_targets": repair_targets,
            "status": status,
            "recommended_action": recommended_action,
        }
        report = attach_hashes(report)
        validate_artifact("evaluation_report", report)
        output = inputs.get("output_path")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            import json
            Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return ToolResult(success=status != "fail", data=report, artifacts=[str(output)] if output else [])

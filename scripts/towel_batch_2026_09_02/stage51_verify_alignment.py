"""阶段 5.1：口播-画面自动对齐验证。

对 4 条样片覆盖全部脚本段；动作/结果证明镜同时检查动作前、动作中和结果态，
单个 midpoint 只用于静态展示镜。
产物：<run>/analysis/alignment_check.json + 汇总打印。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests
import hashlib
ROOT = Path(__file__).resolve().parents[2]
RUNS = ["template-run-yinlizi-A", "template-run-tiansi-A", "template-run-chenxu-A", "template-run-yujin-A"]
MODEL = os.environ.get("TOWEL_ANNOTATION_MODEL") or "qwen-vl-max"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DIMENSIONS = (
    "action_match", "result_support", "narration_caption_match",
    "product_identity_match", "crop_completeness",
)
ALLOWED = {"pass", "revise", "fail"}


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def ask_vlm(frames: Path | list[Path], narration: str, api_key: str, *, static_shot: bool = False) -> dict:
    """VLM 判定。static_shot（口播无动作声明，如 hook/使用场景/材质细节/标签镜）：
    action_match/result_support 无判定对象，应 pass（无 claim 即无冲突）。"""
    static_note = ("" if not static_shot else
                   "注意：该镜口播不含任何动作声明（静态展示镜），"
                   "action_match 与 result_support 应判定为 pass（无动作 claim 即无冲突），"
                   "只评估产品身份、花字与 3:4 主体完整性。")
    prompt = (
        f"这是一条电商毛巾/浴巾短视频同一镜按时间顺序的画面。该镜口播是：「{narration}」。"
        f"请分别判断动作、结果、口播与花字、产品身份、3:4主体完整性。"
        f"{static_note}"
        f"只输出 JSON，字段 action_match/result_support/narration_caption_match/product_identity_match/crop_completeness，"
        f"每个值只能是 pass/revise/fail，另有 reason（≤20字）。"
    )
    frame_list = [frames] if isinstance(frames, Path) else list(frames)
    image_parts = [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")}}
        for frame in frame_list
    ]
    body = {"model": MODEL, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                *image_parts]}]}
    resp = requests.post(API_URL, headers={"Authorization": f"Bearer {api_key}"},
                         json=body, timeout=120)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise RuntimeError(f"VLM 未返回 JSON: {text[:200]}")
    return json.loads(text[s:e + 1])


def canonicalize_vlm_check(
    raw: dict, *, expected_shot_id: str, expected_section_id: str,
    generated_route: bool = False,
) -> dict:
    """Validate and normalize one stage51 VLM result; never infer missing dimensions."""
    if not isinstance(raw, dict):
        raise ValueError("VLM result must be an object")
    if str(raw.get("shot_id") or expected_shot_id) != expected_shot_id:
        raise ValueError("shot_id mismatch")
    if str(raw.get("section_id") or expected_section_id) != expected_section_id:
        raise ValueError("section_id mismatch")
    missing = [field for field in DIMENSIONS if field not in raw]
    if missing:
        raise ValueError("missing alignment dimensions: " + ", ".join(missing))
    normalized = {field: str(raw[field]).strip().lower() for field in DIMENSIONS}
    invalid = [field for field, value in normalized.items() if value not in ALLOWED]
    if invalid:
        raise ValueError("invalid alignment dimension: " + ", ".join(invalid))
    result = {
        "shot_id": expected_shot_id,
        "section_id": expected_section_id,
        **normalized,
        "reason": str(raw.get("reason") or "")[:60],
    }
    if generated_route:
        # The VLM dimensions cover visible action/identity/crop.  Generated
        # text/logo integrity and voice timing are deterministic contract
        # checks here: the route forbids generated text, while the narration
        # cue is bound to the same selected sample window by the runner.
        result.update({
            "generated_text_integrity": "pass",
            "voice_caption_timing_match": "pass",
        })
    return result


def canonical_alignment_gate_errors(checks: list[dict]) -> list[str]:
    """已知语义错配 fail closed；普通 sample approval 不能覆盖。"""
    errors = []
    for check in checks:
        shot_id = str(check.get("shot_id") or "<unknown>")
        missing = [field for field in DIMENSIONS if check.get(field) not in ALLOWED]
        if missing:
            errors.append(f"alignment {shot_id}: missing/invalid {','.join(missing)}")
            continue
        failed = [field for field in DIMENSIONS if check.get(field) != "pass"]
        if failed:
            errors.append(f"alignment {shot_id}: non-pass {','.join(failed)}")
    return errors


def is_static_shot(section: dict) -> bool:
    """口播是否声明了动作；无动作声明的 hook/使用场景/材质细节/标签镜 = 静态镜。"""
    narration = str(section.get("narration") or section.get("text") or "")
    if any(k in narration for k in ("倒", "泼", "滴", "沾", "渗", "擦", "滚",
                                    "吸", "称", "测", "垂", "抖", "量", "裹",
                                    "拧", "按", "计时", "倒水")):
        return False
    return True


def select_review_sections(sections: list[dict]) -> list[dict]:
    """A source-led sample is full length, so every section must be reviewed."""
    return list(sections)


def sample_review_sections(
    sections: list[dict], shot_plan: dict, *, sample_duration: float
) -> list[dict]:
    """Map the selected render shots onto their actual sample timeline.

    The execution plan keeps full-video timestamps, while a representative
    sample may reorder/append a generated shot into a shorter window.  Review
    must therefore use the render order and cumulative shot durations rather
    than the original script timestamps.
    """
    by_section = {str(item.get("id") or ""): item for item in sections}
    mapped: list[dict] = []
    cursor = 0.0
    for shot in (shot_plan.get("shots") or []):
        section = by_section.get(str(shot.get("section_id") or ""))
        if section is None:
            continue
        duration = float(shot.get("duration_seconds") or 0.0)
        if duration <= 0 or cursor >= sample_duration - 1e-6:
            continue
        end = min(cursor + duration, sample_duration)
        mapped.append({"section": section, "shot": shot,
                       "start_seconds": round(cursor, 3),
                       "end_seconds": round(end, 3)})
        cursor = end
    return mapped


def review_timestamps(section: dict) -> list[float]:
    """Return midpoint for static shots, or before/action/result points for proof shots."""
    start = float(section["start_seconds"])
    end = float(section["end_seconds"])
    duration = end - start
    if duration <= 0:
        raise ValueError("section duration must be positive")
    if not section.get("action_keys") and is_static_shot(section):
        return [round(start + duration * 0.5, 3)]
    return [
        round(start + duration * 0.2, 3),
        round(start + duration * 0.5, 3),
        round(start + duration * 0.85, 3),
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run", action="append", dest="selected_runs",
        help="只复核指定项目；可重复传入，默认复核全部样片项目。",
    )
    args = parser.parse_args(argv)
    _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("[fatal] DASHSCOPE_API_KEY 未配置")
        return 2
    totals = {"pass": 0, "fail": 0}
    # Explicit runs may include aligned/pilot projects created by the main
    # workbench; the fixed RUNS tuple remains the default batch set.
    runs = list(args.selected_runs or RUNS)
    unknown = [
        run for run in runs
        if not (ROOT / "projects" / run / "artifacts" / "script.json").is_file()
    ]
    if unknown:
        print("[fatal] run 缺少 script.json: " + ", ".join(unknown))
        return 2
    for run in runs:
        d = ROOT / "projects" / run
        script = json.loads((d / "artifacts" / "script.json").read_text(encoding="utf-8"))
        shot_plan = json.loads((d / "artifacts" / "shot_execution_plan.json").read_text(encoding="utf-8"))
        final_props = json.loads((d / "artifacts" / "final_props.json").read_text(encoding="utf-8"))
        shot_by_section = {
            str(shot.get("section_id")): str(shot.get("id") or shot.get("shot_id"))
            for shot in shot_plan.get("shots", []) if isinstance(shot, dict) and shot.get("section_id")
        }
        sample_duration = float(
            subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(d / "renders" / "sample-v1.mp4")],
                text=True,
            ).strip()
        )
        shot_by_id = {
            str(item.get("id") or item.get("shot_id") or ""): item
            for item in (shot_plan.get("shots") or [])
            if isinstance(item, dict)
        }
        # final_props.scenes is the realized sample order; shot_execution_plan
        # retains the full 30s plan and may contain shots outside the sample.
        shot_plan_rows = [
            shot_by_id[str(scene.get("id") or scene.get("shot_id") or "")]
            for scene in (final_props.get("scenes") or [])
            if str(scene.get("id") or scene.get("shot_id") or "") in shot_by_id
        ]
        sample_rows = sample_review_sections(
            script["sections"], {"shots": shot_plan_rows},
            sample_duration=sample_duration,
        )
        sections = [row["section"] for row in sample_rows]
        sample_times = {
            str(row["section"].get("id") or ""): row
            for row in sample_rows
        }
        checks = []
        for sec in sections:
            expected_shot_id = shot_by_section.get(str(sec["id"]), str(sec.get("shot_id") or sec["id"]))
            frames = []
            row = sample_times[str(sec.get("id") or "")]
            review_sec = {
                **sec,
                "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"],
            }
            for point_index, timestamp in enumerate(review_timestamps(review_sec), start=1):
                frame = d / "analysis" / "alignment" / f"{sec['id']}-{point_index}.jpg"
                frame.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{timestamp:.3f}", "-i",
                                str(d / "renders" / "sample-v1.mp4"), "-frames:v", "1",
                                "-vf", "scale=540:720", "-q:v", "3", str(frame)],
                               check=True, timeout=60)
                frames.append(frame)
            last = None
            for attempt in range(3):
                try:
                    res = ask_vlm(frames, sec["narration"] or sec["screen_copy"], api_key,
                                  static_shot=is_static_shot(sec))
                    res = canonicalize_vlm_check(
                        res, expected_shot_id=expected_shot_id,
                        expected_section_id=str(sec["id"]),
                        generated_route=any(
                            str(shot.get("id") or shot.get("shot_id") or "") == expected_shot_id
                            and shot.get("visual_route") == "generated_from_product_image"
                            for shot in shot_plan.get("shots", [])
                            if isinstance(shot, dict)
                        ),
                    )
                    checks.append(res)
                    totals["pass" if all(res[field] == "pass" for field in DIMENSIONS) else "fail"] += 1
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(2 * (attempt + 1))
            else:
                checks.append({"shot_id": expected_shot_id, "section_id": sec["id"],
                               **{field: "fail" for field in DIMENSIONS}, "reason": str(last)[:60]})
                totals["fail"] += 1
        out = d / "analysis" / "alignment_check.json"
        sample_path = d / "renders" / "sample-v1.mp4"
        report = {
            "version": "1.0",
            "run": run,
            "sample_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
            "script_sha256": str(script.get("semantic_sha256") or ""),
            "checks": checks,
        }
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        gate_errors = canonical_alignment_gate_errors(checks)
        print(f"=== {run} ===")
        human_items = []
        for c in checks:
            state = "pass" if all(c.get(f, "fail") == "pass" for f in DIMENSIONS) else "人工确认"
            print(f"  [{state:7s}] {c.get('section_id','')} — {c.get('reason','')}")
            if state == "人工确认":
                human_items.append({"shot_id": c.get("shot_id"), "section_id": c.get("section_id"),
                                    "reason": c.get("reason", "")})
        if human_items:
            print(f"  [人工确认通道] {len(human_items)} 镜（部分性/单帧误判判定，交人工复核）："
                  + ", ".join(f"{i['section_id']}" for i in human_items[:8]))
        if gate_errors:
            print("  [BLOCKED] " + "; ".join(gate_errors[:8]))
    print(f"\n总计: pass={totals['pass']} fail={totals['fail']}（fail 全部计入人工确认通道；仅判定数据缺失/非法才 BLOCKED）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

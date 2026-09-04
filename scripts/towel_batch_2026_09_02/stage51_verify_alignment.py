"""阶段 5.1：口播-画面自动对齐验证（针对用户反馈"文字/口播和画面对不上"）。

对 4 条样片，每镜取中点帧，VLM 判定画面是否支撑该镜口播。
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


def ask_vlm(frame: Path, narration: str, api_key: str) -> dict:
    prompt = (
        f"这是一条电商毛巾/浴巾短视频某一镜中间时刻的画面。该镜口播是：「{narration}」。"
        f"请分别判断动作、结果、口播与花字、产品身份、3:4主体完整性。"
        f"只输出 JSON，字段 action_match/result_support/narration_caption_match/product_identity_match/crop_completeness，"
        f"每个值只能是 pass/revise/fail，另有 reason（≤20字）。"
    )
    data_url = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")
    body = {"model": MODEL, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}}]}]}
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
    return {
        "shot_id": expected_shot_id,
        "section_id": expected_section_id,
        **normalized,
        "reason": str(raw.get("reason") or "")[:60],
    }


def canonical_alignment_gate_errors(checks: list[dict]) -> list[str]:
    errors = []
    for check in checks:
        shot_id = str(check.get("shot_id") or "<unknown>")
        missing = [field for field in DIMENSIONS if check.get(field) not in ALLOWED]
        failing = [field for field in DIMENSIONS if check.get(field) != "pass"]
        if missing:
            errors.append(f"alignment {shot_id}: missing/invalid {','.join(missing)}")
        elif failing:
            errors.append(f"alignment {shot_id}: non-pass {','.join(failing)}")
    return errors


def main() -> int:
    _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("[fatal] DASHSCOPE_API_KEY 未配置")
        return 2
    totals = {"pass": 0, "fail": 0}
    for run in RUNS:
        d = ROOT / "projects" / run
        script = json.loads((d / "artifacts" / "script.json").read_text(encoding="utf-8"))
        shot_plan = json.loads((d / "artifacts" / "shot_execution_plan.json").read_text(encoding="utf-8"))
        shot_by_section = {
            str(shot.get("section_id")): str(shot.get("id") or shot.get("shot_id"))
            for shot in shot_plan.get("shots", []) if isinstance(shot, dict) and shot.get("section_id")
        }
        sections = script["sections"][:5]
        checks = []
        for sec in sections:
            expected_shot_id = shot_by_section.get(str(sec["id"]), str(sec.get("shot_id") or sec["id"]))
            mid = (sec["start_seconds"] + sec["end_seconds"]) / 2
            frame = d / "analysis" / "alignment" / f"{sec['id']}.jpg"
            frame.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i",
                            str(d / "renders" / "sample-v1.mp4"), "-frames:v", "1",
                            "-vf", "scale=540:720", "-q:v", "3", str(frame)],
                           check=True, timeout=60)
            last = None
            for attempt in range(3):
                try:
                    res = ask_vlm(frame, sec["narration"] or sec["screen_copy"], api_key)
                    res = canonicalize_vlm_check(
                        res, expected_shot_id=expected_shot_id,
                        expected_section_id=str(sec["id"]),
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
        for c in checks:
            state = c.get("action_match", "fail")
            print(f"  [{state:7s}] {c.get('section_id','')} — {c.get('reason','')}")
        if gate_errors:
            print("  [BLOCKED] " + "; ".join(gate_errors[:8]))
    print(f"\n总计: pass={totals['pass']} fail={totals['fail']}")
    return 1 if totals["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

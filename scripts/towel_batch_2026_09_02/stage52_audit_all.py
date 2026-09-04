"""阶段 5.2：全量逐镜绑定审计（16 run × 12 镜）。

对每个 slot：从原始素材按绑定窗口取起点/中点两帧，VLM 输出画面内容描述 +
与口播匹配度（yes/partial/no）+ 相邻镜画面相似度提示。
产物：<run>/analysis/slot_audit.json + 汇总打印（为修复提供精确依据）。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
RESEARCH = {"yinlizi": "maojin-yinlizi", "tiansi": "maojin-tiansi",
            "chenxu": "maojin-chenxu", "yujin": "yujin-chenxu"}
MODEL = os.environ.get("TOWEL_ANNOTATION_MODEL") or "qwen-vl-max"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


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


def ask_vlm(frames: list[Path], narration: str, api_key: str) -> dict:
    prompt = (
        f"电商毛巾/浴巾短视频中一镜的两帧（左=镜头开始，右=镜头中段）。"
        f"该镜口播是：「{narration}」。"
        f"1) 用 ≤22 字描述画面里实际发生的内容；"
        f"2) 判断画面是否支撑这句口播。"
        f"只输出 JSON：{{\"content\": \"描述\", \"match\": \"yes/partial/no\", \"reason\": \"≤20字\"}}"
    )
    content = [{"type": "text", "text": prompt}]
    for f in frames:
        data_url = "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    body = {"model": MODEL, "temperature": 0.0,
            "messages": [{"role": "user", "content": content}]}
    resp = requests.post(API_URL, headers={"Authorization": f"Bearer {api_key}"},
                         json=body, timeout=180)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise RuntimeError(f"VLM 未返回 JSON: {text[:160]}")
    return json.loads(text[s:e + 1])


def audit_slot(run: str, pk: str, scene: dict, mapping: dict, sec: dict, api_key: str) -> dict:
    d = PROJECTS / run
    src_path = PROJECTS / RESEARCH[pk] / mapping["source_path"]
    win = mapping["source_interval"]
    frames_dir = d / "analysis" / "slot_frames" / scene["id"]
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate([win["start_seconds"], (win["start_seconds"] + win["end_seconds_exclusive"]) / 2], 1):
        out = frames_dir / f"f{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src_path),
                        "-frames:v", "1", "-vf", "scale=360:640", "-q:v", "3", str(out)],
                       check=True, timeout=90)
        frames.append(out)
    last = None
    for attempt in range(3):
        try:
            res = ask_vlm(frames, sec.get("narration") or sec.get("screen_copy", ""), api_key)
            res["scene_id"] = scene["id"]
            res["source"] = mapping["source_path"].split("/")[-1]
            res["window"] = win
            res["narration"] = sec.get("narration", "")
            res["domain"] = sec.get("narration_action_key", "")
            return res
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    return {"scene_id": scene["id"], "source": mapping["source_path"].split("/")[-1],
            "window": win, "narration": sec.get("narration", ""), "domain": sec.get("narration_action_key", ""),
            "match": "error", "content": "", "reason": str(last)[:60]}


def main() -> int:
    _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("[fatal] DASHSCOPE_API_KEY 未配置")
        return 2
    summary = []
    for pk, research in RESEARCH.items():
        for arch in "ABCD":
            run = f"template-run-{pk}-{arch}"
            d = PROJECTS / run
            sp = json.loads((d / "artifacts/scene_plan.json").read_text())
            script = json.loads((d / "artifacts/script.json").read_text())
            jobs = list(zip(sp["scenes"], sp["metadata"]["source_mapping"], script["sections"]))
            results = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(audit_slot, run, pk, sc, m, sec, api_key): sc["id"]
                           for sc, m, sec in jobs}
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as exc:  # noqa: BLE001
                        results.append({"scene_id": futures[fut], "match": "error", "reason": str(exc)[:40]})
            results.sort(key=lambda r: r.get("scene_id", ""))
            (d / "analysis/slot_audit.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            cnt = {}
            for r in results:
                cnt[r.get("match", "?")] = cnt.get(r.get("match", "?"), 0) + 1
            summary.append((run, cnt, results))
            print(f"[{run}] {cnt}")
    # 打印所有非 yes 的明细
    print("\n===== 非 yes 明细 =====")
    for run, cnt, results in summary:
        for r in results:
            if r.get("match") != "yes":
                print(f"{run} {r['scene_id']} [{r.get('match')}] 「{r.get('narration','')[:16]}」"
                      f" 源={r.get('source','')[-18:]}@{r.get('window',{}).get('start_seconds','')}s "
                      f"画面={r.get('content','')[:24]} {r.get('reason','')[:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

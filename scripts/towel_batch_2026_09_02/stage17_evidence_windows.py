"""阶段 1.7：证据时间窗标注（修复"口播与画面对不上"）。

问题根因：动作域匹配只到"选哪条素材"，未匹配"素材内动作发生的时间窗"——
盲目的 0 秒起窗口导致口播先于画面动作。修复：每条素材按已知时间点采样 6 帧，
VLM 逐帧判定"<动作域> 动作/主体是否可见"，生成 evidence window。

产物：<project>/analysis/evidence_windows.json
  {stem: {domain, start, end, matching_frames, confident}}
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
PRODUCTS = [("maojin-yinlizi", "银离子毛巾"), ("maojin-tiansi", "天丝莱赛尔毛巾"),
            ("maojin-chenxu", "沉序毛巾"), ("yujin-chenxu", "沉序浴巾")]
MODEL = os.environ.get("TOWEL_ANNOTATION_MODEL") or "qwen-vl-max"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
N_FRAMES = 6
CELL_W, CELL_H = 360, 640  # 2x3 网格 → 1080x1280


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


def sample_frames(src: Path, dur: float, out_dir: Path) -> list[Path]:
    times = [dur * (i + 0.5) / N_FRAMES for i in range(N_FRAMES)]
    frames = []
    for i, t in enumerate(times, 1):
        out = out_dir / f"ev_{i:02d}.jpg"
        if out.is_file():
            frames.append(out)
            continue
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={CELL_W}:{CELL_H}", "-q:v", "3", str(out)],
            check=True, timeout=120)
        frames.append(out)
    return frames, times


def build_sheet(frames: list[Path], out: Path) -> bool:
    filters = []
    for i, f in enumerate(frames):
        filters.append(f"[{i}]scale={CELL_W}:{CELL_H}[v{i}]")
    filters += ["[v0][v1]hstack[a]", "[a][v2]hstack[top]",
                "[v3][v4]hstack[b]", "[b][v5]hstack[bottom]",
                "[top][bottom]vstack[out]"]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in frames:
        cmd += ["-i", str(f)]
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-frames:v", "1", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return proc.returncode == 0 and out.is_file()


def ask_vlm(sheet: Path, domain: str, api_key: str) -> dict:
    prompt = (
        f"这是同一条竖拍视频按时间先后排列的 6 帧（左→右，上→下，帧1最早）。"
        f"请判断哪些帧能清楚看到「{domain}」动作或主体（如倒水/擦拭/标识特写/揉搓等与该动作域相关的画面）。"
        f"只输出 JSON：{{\"matching\": [可见帧编号], \"confident\": true/false, \"note\": \"≤20字说明\"}}"
    )
    data_url = "data:image/jpeg;base64," + base64.b64encode(sheet.read_bytes()).decode("ascii")
    body = {"model": MODEL, "temperature": 0.1,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}}]}]}
    resp = requests.post(API_URL, headers={"Authorization": f"Bearer {api_key}"},
                         json=body, timeout=180)
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise RuntimeError(f"VLM 未返回 JSON: {text[:200]}")
    return json.loads(text[s:e + 1])


def process_clip(stem: str, meta: dict, project: Path, api_key: str) -> tuple[str, dict | None]:
    cache = project / "analysis" / "evidence_windows" / f"{stem}.json"
    if cache.is_file():
        return stem, json.loads(cache.read_text(encoding="utf-8"))
    dur = float(meta["duration_seconds"])
    src = project / "inputs" / "source" / "video" / "product" / f"{stem}.MP4"
    tmp = project / "analysis" / "evidence_frames" / stem
    tmp.mkdir(parents=True, exist_ok=True)
    frames, times = sample_frames(src, dur, tmp)
    sheet = tmp / "sheet.jpg"
    if not sheet.is_file():
        build_sheet(frames, sheet)
    last = None
    for attempt in range(3):
        try:
            res = ask_vlm(sheet, meta["domain"], api_key)
            matching = [int(x) for x in res.get("matching", []) if isinstance(x, (int, float)) and 1 <= x <= N_FRAMES]
            if not matching:
                # 无可见帧 → 整段可用（低置信）
                ev = {"domain": meta["domain"], "start": 0.0, "end": round(dur, 3),
                      "matching_frames": [], "confident": False,
                      "note": res.get("note", "")}
            else:
                first = min(matching) - 1
                last_i = max(matching) - 1
                start = max(0.0, times[first] - 0.4)
                end = min(dur, times[last_i] + 0.8)
                if end - start < 1.2:
                    mid = (start + end) / 2
                    start = max(0.0, mid - 0.6)
                    end = min(dur, mid + 0.6)
                ev = {"domain": meta["domain"], "start": round(start, 3), "end": round(end, 3),
                      "matching_frames": matching, "confident": bool(res.get("confident", False)),
                      "note": res.get("note", "")}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
            return stem, ev
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    return stem, {"error": str(last)}


def main() -> int:
    _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("[fatal] DASHSCOPE_API_KEY 未配置")
        return 2
    for pid, pname in PRODUCTS:
        project = PROJECTS / pid
        sem_map = json.loads((project / "analysis" / "semantic_map.json").read_text(encoding="utf-8"))
        jobs = [(stem, meta) for stem, meta in sem_map.items()]
        out: dict[str, dict] = {}
        ok = fail = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(process_clip, stem, meta, project, api_key): stem for stem, meta in jobs}
            for fut in as_completed(futures):
                stem, ev = fut.result()
                if ev is None or "error" in ev:
                    fail += 1
                    print(f"[{pid}] {stem[:20]} FAILED: {(ev or {}).get('error', 'n/a')[:80]}")
                else:
                    ok += 1
                    out[stem] = ev
        out_path = project / "analysis" / "evidence_windows.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        confident = sum(1 for v in out.values() if v.get("confident"))
        print(f"[{pid}] evidence windows: {ok} ok / {fail} failed, confident={confident}/{ok} -> {out_path}")
    print("[done] stage 1.7")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

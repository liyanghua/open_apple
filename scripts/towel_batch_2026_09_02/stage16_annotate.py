"""阶段 1.6：VLM 语义标注（付费分析调用，dashscope qwen-vl-max）。

对每段素材的 4 帧接触表做动作域/主体/景别/镜头/可用性标注，
产物：<project>/analysis/annotations/<sha>.json + annotations.json 聚合。

标注结果用于：source_media_review 语义化、语义符号链接命名、模板 slot→素材映射。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
PRODUCTS = ["maojin-yinlizi", "maojin-tiansi", "maojin-chenxu", "yujin-chenxu"]


def _load_env() -> None:
    """与 tool_registry 相同的 .env 加载方式（不进 os.environ 的变量不覆盖）。"""
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
MODEL = os.environ.get("TOWEL_ANNOTATION_MODEL") or "qwen-vl-max"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

PROMPT = (
    "你是电商毛巾/浴巾短视频素材标注员。图中是同一段竖拍素材按时间顺序的 4 帧"
    "（左上→右上→左下→右下）。只输出 JSON，不要其他文字。字段：\n"
    "action_domain: 从以下选一个最贴切的动作域——吸水演示/抗菌标识/材质细节/亲肤柔软/"
    "厚度克重/包装展示/使用场景/色彩质感/尺寸对比/其他；\n"
    "subject: 画面主体简述（≤15字）；\n"
    "shot_size: 特写/近景/中景/全景；\n"
    "camera_movement: 固定/推/拉/手持/摇；\n"
    "usable: fully/partial/bad；\n"
    "quality_note: 可用性问题简述（模糊、过曝、主体出框、抖动等；无问题填 无）；\n"
    "text_on_screen: 画面可见文字/标识/数字（吊牌、检测报告等），没有填 无。"
)


def call_vlm(sheet_path: Path, api_key: str) -> dict:
    data_url = "data:image/jpeg;base64," + base64.b64encode(sheet_path.read_bytes()).decode("ascii")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "temperature": 0.1,
    }
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=180,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"VLM 未返回 JSON: {text[:200]}")
    return json.loads(text[start:end + 1])


def annotate_one(project: Path, sha: str, sheet: Path, api_key: str, retries: int = 2) -> dict:
    out = project / "analysis" / "annotations" / f"{sha}.json"
    if out.is_file():
        return json.loads(out.read_text(encoding="utf-8"))
    last = None
    for attempt in range(retries + 1):
        try:
            data = call_vlm(sheet, api_key)
            data["model"] = MODEL
            data["annotated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    return {"error": str(last), "sha": sha}


def main() -> int:
    _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("[fatal] DASHSCOPE_API_KEY 未配置")
        return 2
    total_done = 0
    for pid in PRODUCTS:
        project = PROJECTS / pid
        manifest_path = project / "analysis" / "contact_sheets" / "sheets_manifest.json"
        if not manifest_path.is_file():
            print(f"[skip] {pid}: 无接触表 manifest")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jobs = [(sha, project / meta["sheet"]) for sha, meta in manifest.items()]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(annotate_one, project, sha, sheet, api_key): sha
                       for sha, sheet in jobs}
            done, failed = 0, 0
            for fut in as_completed(futures):
                sha = futures[fut]
                try:
                    res = fut.result()
                    if "error" in res:
                        failed += 1
                        print(f"[{pid}] {sha[:10]} FAILED: {res['error'][:80]}")
                    else:
                        done += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    print(f"[{pid}] {sha[:10]} EXC: {exc}")
        print(f"[{pid}] annotated {done} ok / {failed} failed")
        total_done += done
    print(f"[done] annotations: {total_done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

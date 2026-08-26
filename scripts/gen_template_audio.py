"""为 template run 生成 Doubao TTS 口播（付费，voice-timeline-fit 实测），并把适配写进 decision_log。

生成每个 script section 的 narration → assets/audio/narration-sNN.mp3 + .json（含词级时间戳），
用 ffprobe 实测每段时长，对比槽位时长（slot_s）；放不下则按 voice-timeline-fit 顺序处理：
先 speech_rate +10%/+20%...+50% 每档重测，仍不行则标记改写（此处先只做 rate 档，不自动改写）。

用法：python -m scripts.gen_template_audio --run template-run-sheet-01-video1-aks-zhuodian
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.tool_registry import registry

ROOT = Path(__file__).resolve().parents[1]
# voice-timeline-fit：匹配豆包 seed-tts 语速档（+10% → +20% → +50%）
RATE_STEPS = [0, 10, 20, 30, 50]


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _speech_seconds(meta_path: Path) -> float | None:
    """从 TTS 词级时间戳取每句实际言语结束（不含 mp3 尾部静音 padding）。"""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sentences = (data.get("data") or {}).get("sentences") or data.get("sentences") or []
    if not sentences:
        return None
    return max(float(s.get("endTime", 0)) for s in sentences) / 1000.0


def _audio_duration(path: Path) -> float | None:
    try:
        from tools.analysis.audio_probe import probe_duration
        return probe_duration(path)
    except Exception:
        return None


def narration_filename(sec_id: str) -> str:
    """口播音频文件名（唯一命名契约）：sec-001 → narration-s001.mp3（三位、与 section 编号一致）。

    混音/清单/渲染都必须使用本函数，禁止在别处用两位编号拼文件名（评审 P0-2）。
    """
    num = str(sec_id).split("-")[-1].zfill(3)
    return f"narration-s{num}.mp3"


def narration_meta_filename(sec_id: str) -> str:
    return narration_filename(sec_id).replace(".mp3", ".mp3.json")


def _text_sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TTS_LOCK: dict[str, Any] = {
    "voice_id": "zh_female_vv_uranus_bigtts",
    "resource_id": "seed-tts-2.0",
    "format": "mp3",
}


def _sidecar(sec_id: str, audio_dir: Path) -> Path:
    return audio_dir / f"{narration_filename(sec_id)}.lock.json"


def _tts_lock_valid(lock: Path, text: str, *, speech_rate: int) -> bool:
    """缓存完整绑定（评审 P1-2）：文案 hash + voice/resource/format/rate 全部一致才复用。"""
    if not lock.is_file():
        return False
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        data.get("text_sha") == _text_sha(text)
        and data.get("speech_rate") == speech_rate
        and all(data.get(k) == v for k, v in TTS_LOCK.items())
    )


def generate(run: str, *, max_workers: int = 4) -> list[dict]:
    registry.discover()
    tts = registry._tools.get("doubao_tts")
    project = ROOT / "projects" / run
    script = _load(project / "artifacts" / "script.json")
    audio_dir = project / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    sections = [s for s in script["sections"] if str(s.get("narration") or s.get("text") or "").strip()]
    if not sections:
        return []
    # 并行生成（doubao 异步轮询，单段 1-2 分钟；逐段串行会拖垮批量跑片时间线）。
    # 每段独立 rate 阶梯；结果按 section 顺序落回。
    from concurrent.futures import ThreadPoolExecutor

    def _one(sec: dict) -> dict:
        sid = str(sec["id"])  # sec-001
        text = str(sec.get("narration") or sec.get("text") or "").strip()
        slot_s = float(sec["end_seconds"]) - float(sec["start_seconds"])
        out = audio_dir / narration_filename(sid)
        meta = audio_dir / narration_meta_filename(sid)
        sha_file = _sidecar(sid, audio_dir)
        best = None
        speech_s = _speech_seconds(meta) if meta.is_file() else None
        existing_dur = _audio_duration(out) if out.is_file() else None
        fit_s = speech_s if speech_s is not None else existing_dur
        lock_ok = _tts_lock_valid(sha_file, text, speech_rate=0)
        if lock_ok and fit_s is not None and fit_s <= slot_s:
            # 幂等（评审 P1-5/P1-2）：文案+voice+resource+format+rate 全绑定且放得下 → 复用。
            best = {"section": sid, "status": "ok", "slot_s": slot_s,
                    "audio_s": round(fit_s, 2), "speech_rate": 0,
                    "output": str(out), "cost_usd": 0.0, "reused": True, "text": text}
            return best
        for rate in RATE_STEPS:
            result = tts.execute({
                "text": text, "voice_id": "zh_female_vv_uranus_bigtts", "resource_id": "seed-tts-2.0",
                "format": "mp3", "speech_rate": rate, "enable_timestamp": True,
                "output_path": str(out), "metadata_path": str(meta),
            })
            if not result.success:
                best = {"section": sid, "status": "error", "error": result.error[:120], "slot_s": slot_s}
                break
            dur = _speech_seconds(meta) or _audio_duration(out)
            price = result.cost_usd or 0.0
            if dur is not None and dur <= slot_s:
                lock = {**TTS_LOCK, "text_sha": _text_sha(text), "speech_rate": rate}
                sha_file.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
                best = {"section": sid, "status": "ok", "slot_s": slot_s,
                        "audio_s": round(dur, 2), "speech_rate": rate,
                        "output": str(out), "cost_usd": price, "text": text}
                break
            if rate == RATE_STEPS[-1]:
                best = {"section": sid, "status": "overflow", "slot_s": slot_s,
                        "audio_s": round(dur, 2) if dur is not None else None,
                        "speech_rate": rate, "cost_usd": price, "text": text}
        return best

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        ordered = list(pool.map(_one, sections))
    for best in ordered:
        print(f"  {best['section']}: {best['status']}")
    return ordered


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-01-video1-aks-zhuodian")
    args = p.parse_args()
    results = generate(args.run)
    # 汇总
    ok = [r for r in results if r["status"] == "ok"]
    for r in results:
        if r["status"] != "ok":
            print(f"  非OK: {r['section']} {r['status']} {r.get('error') or r.get('reason') or r.get('audio_s')}")
    print(f"\nOK {len(ok)}/{len(results)}；总成本 ${round(sum(r.get('cost_usd',0) for r in results if r.get('cost_usd')),4)}")


if __name__ == "__main__":
    main()

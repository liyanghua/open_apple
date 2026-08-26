"""模板 run 的媒体管线一键脚本：proxies + TTS + BGM + mix + canonical 渲染制品。

主链路定位：assets 门（build_assets 四制品）之后、sample 渲染之前。一次调用完成：
  1. 逐镜 proxy（scene_plan.source_mapping 的 source_interval → assets/video/shot-NN-proxy.mp4，
     540x960 9:16 中心裁切、保留源帧率）——幂等绑定「源内容 hash + 裁剪区间」
  2. Doubao TTS 口播（复用 scripts.gen_template_audio.generate，voice-timeline-fit 逐档实测；
     内容 hash 幂等；overflow/error 直接阻断本管线）
  3. SUNO 纯音乐 BGM（assets/music/bgm-source.mp3 → 按成片时长裁切 bgm-{N}s.mp3）
  4. full_mix 混音（narration 逐段 + BGM ducking + loudnorm -14 + TP -1.5 后处理）
     → assets/audio/sample-mix.mp3（幂等绑定「TTS 文案 hash 集 + BGM hash + 目标时长」）
  5. 渲染契约四件套：asset_manifest（含 proxies + sample-mix 登记）/ final_props /
     render_plan / edit_decisions（引用真实资产名）

付费说明：本脚本调用 TTS(doubao) 与 BGM(suno)，均需 template_run_plan 已批准
（check_template_run_plan_ready fail-closed）。

用法：python -m scripts.prep_template_media --run template-run-sheet-05-video5-aks-zhuodian
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from lib.artifact_io import write_artifact_atomic
from lib.template_mainline import _load
from lib.template_run_plan import check_template_run_plan_ready

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "cinematic-fast"
PROXY_W, PROXY_H = 540, 960


def _ffprobe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(p.stdout.strip())
    except (ValueError, IndexError):
        return 0.0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar_valid(sidecar: Path, expected: dict) -> bool:
    """内容 hash 幂等（评审 P1-5）：sidecar 存在且与期望参数一致才允许跳过。"""
    if not sidecar.is_file():
        return False
    try:
        return json.loads(sidecar.read_text(encoding="utf-8")) == expected
    except (OSError, json.JSONDecodeError):
        return False


def _trim_proxy(source: Path, output: Path, src_in: float, duration: float) -> bool:
    """9:16 中心裁切 proxy，保留源帧率；sidecar 内容一致才跳过。"""
    sidecar = output.with_suffix(output.suffix + ".prep.json")
    expected = {"source_sha256": _sha256_file(source), "src_in": round(src_in, 3),
                "duration": round(duration, 3), "out_sha256": _sha256_file(output) if output.is_file() else ""}
    if output.is_file() and output.stat().st_size > 0 and _sidecar_valid(sidecar, expected):
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={PROXY_W}:{PROXY_H}:force_original_aspect_ratio=increase,"
        f"crop={PROXY_W}:{PROXY_H}:x=(iw-ow)/2:y=(ih-oh)/2"
    )
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", f"{src_in:.3f}", "-t", f"{duration:.3f}",
           "-i", str(source), "-vf", vf, "-an", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "20", str(output)]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0 or not output.is_file():
        raise RuntimeError(f"proxy 失败 {source.name}: {p.stderr.strip()[:200] or p.stdout.strip()[:200]}")
    expected["out_sha256"] = _sha256_file(output)
    sidecar.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    return True


def _trim_bgm(source: Path, output: Path, total_s: float) -> None:
    sidecar = output.with_suffix(output.suffix + ".prep.json")
    expected = {"source_sha256": _sha256_file(source), "target_s": round(total_s, 3),
                "out_sha256": _sha256_file(output) if output.is_file() else ""}
    if output.is_file() and output.stat().st_size > 0 and _sidecar_valid(sidecar, expected):
        return
    out_dur = _ffprobe_duration(source)
    cut = min(out_dur, total_s)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-t", f"{cut:.3f}",
           "-af", "afade=t=in:d=0.4,afade=t=out:st={:.3f}:d=0.4".format(max(0.0, cut - 0.4)),
           "-c:a", "libmp3lame", "-q:a", "2", str(output)]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0 or not output.is_file():
        raise RuntimeError(f"BGM 裁切失败: {p.stderr.strip()[:200]}")
    expected["out_sha256"] = _sha256_file(output)
    sidecar.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")


def _generate_bgm(project: Path, run: str, total_s: float) -> dict:
    """SUNO 生成纯音乐；已存在 bgm-source.mp3 则跳过（幂等）。"""
    music_dir = project / "assets" / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    source = music_dir / "bgm-source.mp3"
    lock_file = music_dir / "bgm-source.lock.json"
    BGM_PROMPT = ("轻快电商节奏 BGM：极简合成器 + 轻鼓点 + 明亮钢琴，"
                  "透明桌垫家居好物短视频背景，干净、亲和、不抢口播")
    BGM_MODEL = "V4_5"
    expected_lock = {"prompt_sha256": hashlib.sha256(BGM_PROMPT.encode("utf-8")).hexdigest(),
                     "model": BGM_MODEL, "instrumental": True}
    lock_ok = _sidecar_valid(lock_file, expected_lock)
    if not (source.is_file() and source.stat().st_size > 0 and lock_ok):
        # 评审 P1-2：BGM 源不存在 **或** 锁不匹配（prompt/model/instrumental 变化）→ 重新付费生成。
        from tools.tool_registry import registry

        registry.discover()
        suno = registry._tools["suno_music"]
        result = suno.execute({
            "prompt": BGM_PROMPT,
            "instrumental": True,
            "model": BGM_MODEL,
            "output_path": str(source),
        })
        if not result.success:
            raise RuntimeError(f"SUNO BGM 生成失败: {result.error}")
        print(f"  BGM 生成完成: {source.name} (cost ${round(result.cost_usd or 0, 4)})")
        bgm_cost = float(result.cost_usd or 0.0)
        lock_file.write_text(json.dumps(expected_lock, ensure_ascii=False), encoding="utf-8")
    else:
        bgm_cost = 0.0
    trimmed = music_dir / f"bgm-{int(round(total_s))}s.mp3"
    _trim_bgm(source, trimmed, total_s)
    return {"path": f"assets/music/{trimmed.name}", "cost_usd": bgm_cost, "source": str(source)}


def _generate_proxies(project: Path, sp: dict) -> None:
    """逐镜 proxy（内容 hash 幂等）。"""
    import time

    video_dir = project / "assets" / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    for i, m in enumerate(sp["metadata"]["source_mapping"], start=1):
        interval = m["source_interval"]
        timeline = m["timeline_interval"]
        duration = timeline["end_seconds_exclusive"] - timeline["start_seconds"]
        source = Path(m["source_path"])
        if not source.is_file():
            raise RuntimeError(f"素材缺失: {source}")
        out = video_dir / f"shot-{i:02d}-proxy.mp4"
        t0 = time.time()
        if _trim_proxy(source, out, float(interval["start_seconds"]), float(duration)):
            print(f"  proxy {out.name}: {duration:.2f}s in {time.time()-t0:.1f}s")


def _build_manifest(project: Path, run: str, script: dict, sp: dict,
                    tts_results: list[dict], bgm: dict, total_s: float) -> dict:
    """asset_manifest：完整登记 口播 + BGM + 逐镜 proxy + 成品混音（评审 P1-7）。"""
    audio_dir = project / "assets" / "audio"
    video_dir = project / "assets" / "video"
    assets = []
    cost = 0.0
    for r in tts_results:
        sid = r["section"]
        from scripts.gen_template_audio import narration_filename

        out = audio_dir / narration_filename(sid)
        if not out.is_file():
            continue
        cost += float(r.get("cost_usd") or 0.0)
        assets.append({
            "id": f"narration-{sid}", "type": "narration",
            "path": f"assets/audio/{out.name}", "source_tool": "doubao_tts",
            "scene_id": sid,
            "format": "mp3", "model": "seed-tts-2.0", "resolution": "24000 Hz",
            "generation_summary": f"豆包 TTS 口播 {sid}",
            "provider": "doubao", "cost_usd": round(r.get("cost_usd") or 0.0, 6),
            "duration_seconds": round(_ffprobe_duration(out), 3)})
    for i, m in enumerate(sp["metadata"]["source_mapping"], start=1):
        proxy = video_dir / f"shot-{i:02d}-proxy.mp4"
        if not proxy.is_file():
            continue
        assets.append({
            "id": f"proxy-{m['scene_id']}", "type": "video",
            "path": f"assets/video/{proxy.name}", "source_tool": "media_proxy",
            "scene_id": m["scene_id"],
            "format": "mp4", "resolution": f"{PROXY_W}x{PROXY_H}",
            "generation_summary": f"逐镜 proxy（{m['template_slot_ref']} 语义窗口）",
            "provider": "ffmpeg-local", "cost_usd": 0.0,
            "duration_seconds": round(float(m["timeline_interval"]["end_seconds_exclusive"]
                                             - m["timeline_interval"]["start_seconds"]), 3),
            "proxy_cache_key": _sha256_file(proxy)})
    mix = audio_dir / "sample-mix.mp3"
    if mix.is_file():
        assets.append({
            "id": "sample-mix", "type": "audio", "path": "assets/audio/sample-mix.mp3",
            "source_tool": "audio_mixer", "scene_id": "whole", "format": "mp3",
            "generation_summary": "narration 逐段 + BGM ducking + loudnorm -14 + TP -1.5",
            "provider": "ffmpeg-loudnorm", "cost_usd": 0.0,
            "duration_seconds": round(total_s, 3),
            "source_content_sha256": _sha256_file(mix)})
    assets.append({
        "id": f"bgm-{int(round(total_s))}s", "type": "music", "path": bgm["path"],
        "source_tool": "suno_music", "scene_id": "whole",
        "format": "mp3", "model": "V4_5", "resolution": "44100 Hz",
        "generation_summary": "Suno BGM 裁剪至成片时长",
        "provider": "suno", "cost_usd": round(float(bgm.get("cost_usd") or 0.0), 4),
        "duration_seconds": round(total_s, 3)})
    return {
        "version": "1.0",
        "metadata": {"pipeline": "template-driven", "scope": "sample_audio", "project_id": run},
        "total_cost_usd": round(cost + float(bgm.get("cost_usd") or 0.0), 4),
        "assets": assets,
    }


def _build_mix_tracks(audio_dir: Path, script: dict, bgm_path: Path) -> tuple[list[dict], dict[str, str]]:
    """构造 full_mix 轨道：narration 逐段（三位命名契约）+ BGM。

    返回 (tracks, narration_sha)；任一已声明口播缺文件即抛错（评审 P0-2/P0-3）。
    """
    from scripts.gen_template_audio import narration_filename, _text_sha

    narration_keys: dict[str, str] = {}
    tracks = []
    for sec in (script.get("sections") or []):
        sid = str(sec.get("id") or "")
        if not str(sec.get("narration") or "").strip():
            continue
        seg = audio_dir / narration_filename(sid)
        if not seg.is_file():
            raise RuntimeError(f"口播音频缺失: {seg.name}（先跑 TTS；评审 P0-2 命名契约）")
        start = float(sec.get("start_seconds") or 0.0)
        tracks.append({"path": str(seg), "role": "speech", "start_seconds": start})
        narration_keys[sid] = _text_sha(str(sec["narration"]).strip())
    tracks.append({"path": str(bgm_path), "role": "music"})
    return tracks, narration_keys


def _build_mix(project: Path, sp: dict, script: dict, bgm: dict, total_s: float) -> None:
    """narration 逐段 + BGM，full_mix（ducking + loudnorm -14）→ sample-mix.mp3。

    幂等（评审 P1-5）：sidecar 记录「每段口播文案 hash + BGM hash + 目标时长」，
    任一变化（如文案修正后的新 TTS）都会强制重混，绝不复用旧混音。
    """
    audio_dir = project / "assets" / "audio"
    out = audio_dir / "sample-mix.mp3"
    sidecar = out.with_suffix(out.suffix + ".prep.json")
    tracks, narration_keys = _build_mix_tracks(audio_dir, script, project / bgm["path"])
    expected = {"target_s": round(total_s, 3), "bgm_sha256": _sha256_file(project / bgm["path"]),
                "narration_sha": narration_keys,
                "out_sha256": _sha256_file(out) if out.is_file() else ""}
    if out.is_file() and out.stat().st_size > 0 and _sidecar_valid(sidecar, expected):
        return
    from tools.tool_registry import registry

    registry.discover()
    mixer = registry._tools["audio_mixer"]
    result = mixer.execute({
        "operation": "full_mix",
        "tracks": tracks,
        "target_duration": round(total_s, 3),
        "normalize": True,
        "loudnorm_target": -14,
        "output_path": str(out),
    })
    if not result.success:
        raise RuntimeError(f"混音失败: {result.error}")
    _post_normalize(out)
    expected["out_sha256"] = _sha256_file(out)
    sidecar.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")


def _post_normalize(out: Path) -> None:
    """Loudnorm 单遍：I=-14 且 True-Peak ≤ -1.5 dBTP（L1a 硬门 :> -1.0 留余量）。"""
    import subprocess as _sp

    tmp = out.with_name(out.stem + ".tmp.mp3")
    p = _sp.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(out),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=7",
        "-c:a", "libmp3lame", "-q:a", "2", str(tmp),
    ], capture_output=True, text=True, check=False)
    if p.returncode != 0 or not tmp.is_file():
        raise RuntimeError(f"loudnorm 后处理失败: {p.stderr.strip()[:200]}")
    tmp.replace(out)


def prep(run: str) -> dict:
    project = ROOT / "projects" / run
    rp = _load(project / "artifacts" / "template_run_plan.json") or {}
    readiness = check_template_run_plan_ready(rp)
    if not readiness.get("ready"):
        raise SystemExit(f"template_run_plan 未就绪，禁止付费媒体管线: {readiness.get('blockers')}")
    script = _load(project / "artifacts" / "script.json")
    sp = _load(project / "artifacts" / "scene_plan.json")
    template_id = str(rp.get("template_id") or "")
    pack = _load(ROOT / "projects/template-pack-library/artifacts/template_pack.json")
    template = next((t for t in pack.get("templates", []) if t.get("template_id") == template_id), None)
    if template is None:
        raise SystemExit(f"template {template_id} not in pack")
    total_s = float(script["total_duration_seconds"])
    shot_plan = _load(project / "artifacts" / "shot_execution_plan.json") or {}
    # 跨阶段一致性（评审 P0-1）：shot_plan 必须与当前 script/scene_plan 键控一致；
    # 漂移（如 rebuild 后未重派生）→ 先同步四制品再继续，绝不带旧制品渲染。
    from lib.template_assets import shot_plan_drift, sync_assets_artifacts

    drift = shot_plan_drift(project, template, sp, script, shot_plan)
    if drift:
        print(f"  检测到 shot_execution_plan 漂移（{len(drift)} 处），同步重派生 assets 四制品 ...")
        from backlot.project_commit import ProjectCommitStore as _PCS

        with _PCS(project).transaction(action={"action_id": f"sync-assets-{run}"}) as sink:
            sync_assets_artifacts(project, template, pipeline_dir=ROOT / "projects", sink=sink)
        shot_plan = _load(project / "artifacts" / "shot_execution_plan.json") or {}
        assert not shot_plan_drift(project, template, sp, script, shot_plan), "同步后仍漂移（中止）"
    shots = [
        {"id": str(s["id"]),
         "duration_seconds": float(s["duration_seconds"]),
         "screen_copy": str(s.get("screen_copy") or ""),
         "scene_id": str(s.get("scene_id") or ""),
         "template_slot_ref": str(s.get("template_slot_ref") or "")}
        for s in shot_plan.get("shots", [])
    ]
    # 逐镜 proxy（本地，内容 hash 幂等）
    _generate_proxies(project, sp)
    # BGM（付费，幂等）
    bgm = _generate_bgm(project, run, total_s)
    # TTS（付费，内容 hash 幂等；overflow/error 阻断）
    from scripts.gen_template_audio import generate as generate_tts

    tts_results = generate_tts(run)
    bad = [r for r in tts_results if r.get("status") in ("error", "overflow")]
    if bad:
        raise SystemExit(
            f"{run}: TTS 存在 {len(bad)} 段未通过 voice-timeline-fit："
            + "; ".join(f"{r['section']}({r.get('status')})" for r in bad[:8])
            + " —— 禁止带缺句/超长口播进入混音与渲染（评审 P1-6）")
    # 混音（内容 hash 幂等）
    _build_mix(project, sp, script, bgm, total_s)

    # 渲染契约四件套
    from lib.template_render import build_edit_decisions, build_final_props, build_render_plan

    manifest = _build_manifest(project, run, script, sp, tts_results, bgm, total_s)
    fp = build_final_props(project, script, shots,
                           narration_mix="assets/audio/sample-mix.mp3",
                           bgm_path=bgm["path"])
    render_plan = build_render_plan(project, mode="full", total_frames=int(round(total_s * 30)),
                                    audio_path=project / "assets/audio/sample-mix.mp3")
    edit_decisions = build_edit_decisions(project, shots, render_runtime="remotion",
                                          narration_mix="assets/audio/sample-mix.mp3",
                                          bgm_path=bgm["path"], scene_plan=sp)

    from backlot.project_commit import ProjectCommitStore

    with ProjectCommitStore(project).transaction(action={"action_id": f"prep-media-{run}"}) as sink:
        envs = {
            "asset_manifest": write_artifact_atomic("artifacts/asset_manifest.json", "asset_manifest",
                                                    manifest, project_dir=project, sink=sink),
            "final_props": write_artifact_atomic("artifacts/final_props.json", "final_props",
                                                 fp, project_dir=project, sink=sink),
            "render_plan": write_artifact_atomic("artifacts/render_plan.json", "render_plan",
                                                 render_plan, project_dir=project, sink=sink),
            "edit_decisions": write_artifact_atomic("artifacts/edit_decisions.json", "edit_decisions",
                                                    edit_decisions, project_dir=project, sink=sink),
        }
    # 制品重写后刷新所有 checkpoint 信封（评审 P0-1：跨阶段 hash 引用保持一致）。
    from lib.checkpoint import refresh_checkpoint_envelopes

    refresh_checkpoint_envelopes(ROOT / "projects", run, pipeline_type=PIPELINE)
    return {"envs": envs, "bgm": bgm, "tts": tts_results, "total_s": total_s, "manifest": manifest}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="template-run-sheet-05-video5-aks-zhuodian")
    args = p.parse_args()
    result = prep(args.run)
    print(f"\n{args.run} 媒体管线完成：{result['total_s']}s, TTS {len(result['tts'])} 段, "
          f"BGM {result['bgm']['path']}, manifest cost ${result['manifest']['total_cost_usd']}")


if __name__ == "__main__":
    main()

"""模板 run 发布：ExportBundle 交付包 + publish_log + publish checkpoint（completed）。

用法：python -m scripts.publish_template_run --run <run>
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = "cinematic-fast"


def _load(project: Path, name: str) -> dict | None:
    f = project / "artifacts" / f"{name}.json"
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def verify_publish_gates(project: Path, run: str) -> dict:
    """发布硬门（评审 P0-2/P0-3）：媒体 hash、输入/QA artifact hash、gate 状态全部绑定
    delivery_certificate（certified delivery version）才允许导出"""
    import hashlib
    import os

    def _stage_status(stage: str):
        f = project / f"checkpoint_{stage}.json"
        if not os.path.exists(f):
            return None
        return json.loads(f.read_text(encoding="utf-8")).get("status")

    def _file_sha(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    qa = _load(project, "final_qa_full")
    l1a = _load(project, "l1a_final")
    cert = _load(project, "delivery_certificate")
    problems = []
    if not qa or str(qa.get("status") or "") != "pass":
        problems.append(f"final_qa status={(qa or {}).get('status', '缺失')}")
    if not l1a or str(l1a.get("status") or "") != "pass":
        problems.append(f"l1a_final status={(l1a or {}).get('status', '缺失')}")
    compose_status = _stage_status("compose")
    if compose_status != "completed":
        problems.append(f"compose checkpoint {compose_status or '缺失'}")
    sample_status = _stage_status("sample")
    if sample_status != "completed":
        problems.append(f"sample checkpoint {sample_status or '缺失'}（样例未批，禁止发布）")
    # 交付证书：媒体快照 + 输入/QA hash 必须与磁盘一致（不可变交付版本绑定）。
    if not cert:
        problems.append("delivery_certificate 缺失（无 certified delivery version，禁止发布）")
    else:
        final = project / cert["media"]["final_path"]
        if not final.is_file():
            problems.append(f"final 媒体缺失: {cert['media']['final_path']}")
        elif _file_sha(final) != cert["media"]["final_sha256"]:
            problems.append("final.mp4 与交付证书 hash 不一致（媒体被改动，禁止发布）")
        sample = project / cert["media"]["sample_path"]
        if sample.is_file() and _file_sha(sample) != cert["media"]["sample_sha256"]:
            problems.append("sample-v1.mp4 与交付证书 hash 不一致")
        for name, want in (list((cert.get("source_hashes") or {}).items())
                           + list((cert.get("qa_refs") or {}).items())):
            f = project / "artifacts" / f"{name}.json"
            if not f.is_file() or _file_sha(f) != want:
                problems.append(f"{name}.json 与交付证书 hash 不一致")
        if cert.get("gates", {}).get("final_qa") != "pass" \
                or cert.get("gates", {}).get("l1a_final") != "pass":
            problems.append("交付证书 gate 非 pass")
    # 正式版准入（严格档）：指认账本 strict_required=true 的正式版必须通过 strict_pass，
    # 否则禁止发布（历史已发布版本不受追溯影响；重发布视为新准入）。
    from lib.template_source_match import material_reuse_report

    sp = _load(project, "scene_plan") or {}
    reuse = material_reuse_report(sp)
    ledger = _load(ROOT / "projects/template-pack-library", "release_designations")
    strict_required = False
    strict_reason = ""
    for dg in (ledger or {}).get("designations", []):
        if str(dg.get("official_run")) == run:
            strict_required = bool(dg.get("strict_required", True))
            strict_reason = str(dg.get("reason") or "")
            break
    if strict_required and not reuse.get("strict_pass"):
        problems.append("严格档准入未通过（画面重复 S1\'-S5\'）" + (f"：{strict_reason}" if strict_reason else "") +
                        "—— 正式版须严格档全绿（见 overview 画面重复列）")
    if problems:
        raise SystemExit(f"{run}: 发布阻断（评审 P0-2/P0-3）——" + "; ".join(problems))
    return {"final_qa": qa.get("status"), "l1a_final": l1a.get("status"),
            "compose": compose_status, "sample": sample_status,
            "strict_gate": "pass" if (not strict_required or reuse.get("strict_pass")) else "fail",
            "certified_media_sha256": cert["media"]["final_sha256"]}


def publish(run: str) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    project = ROOT / "projects" / run
    verify_publish_gates(project, run)
    from backlot.project_commit import ProjectCommitStore
    from lib.artifact_io import write_artifact_atomic
    from lib.checkpoint import write_checkpoint
    from tools.tool_registry import registry

    old = _load(project, "publish_log") if (project / "artifacts/publish_log.json").exists() else {}
    meta = ((old.get("entries") or [{}])[0].get("metadata_used") or {})
    title = meta.get("title", "透明桌垫 · 餐桌省心好物")
    hashtags = meta.get("hashtags", ["透明桌垫", "TPU桌垫"])
    desc = meta.get("description", "透明桌垫 proof-driven 短视频")
    if "两层字幕" not in desc:
        desc += "（两层字幕：左上书法花字 + 底部口播字幕）"

    registry.discover()
    bundle = registry._tools["export_bundle"]
    result = bundle.execute({
        "video_path": str(project / "renders/final.mp4"),
        "title": title, "description": desc, "hashtags": hashtags,
        "platform": "local", "visibility": "private",
    })
    if not result.success:
        raise RuntimeError(f"导出失败: {result.error}")

    entry = {
        "platform": "local", "status": "exported", "export_path": "renders/final.mp4",
        "timestamp": datetime.now(timezone.utc).isoformat(), "visibility": "private",
        "metadata_used": {"title": title, "description": desc, "hashtags": hashtags},
    }
    publish_log = {
        "version": "1.0", "entries": [entry],
        "metadata": {"note": f"本地交付包；未上传任何平台。导出包: {result.data.get('export_path')}"},
    }
    with ProjectCommitStore(project).transaction(action={"action_id": f"publish-{run}"}) as sink:
        env = write_artifact_atomic("artifacts/publish_log.json", "publish_log", publish_log,
                                    project_dir=project, sink=sink)
        write_checkpoint(ROOT / "projects", run, "publish", "completed", {"publish_log": env},
                         pipeline_type=PIPELINE, next_action=None, sink=sink)
    return {"export_path": result.data.get("export_path"), "files": result.data.get("files_written")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    args = p.parse_args()
    print(publish(args.run))


if __name__ == "__main__":
    main()

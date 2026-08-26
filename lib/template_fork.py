"""模板 run 项目：复用共享 research 的一次性 fork 播种。

模板驱动（Req 3）与 candidate fork 同构：**不重新跑一遍完整视频分析**。research 只用
一次（在共享源项目），每个 template run 是一个 fork 出的项目，播种共享 research 制品 +
派生 analysis/ 文件 + 共享商品事实，并写一个 ``completed`` 的 research checkpoint，使该
run 的 `checkpoint.get_next_stage` 从 proposal 开始。这与 `lib.batch_fork` 的 main-chain
复用模式一致，不旁路、不重复分析。

只负责播种 + 校验；不在此做任何创意决策、不写 scene_plan/script 内容（见各 director 契约）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import init_project, write_checkpoint
from schemas.artifacts import validate_artifact

# 共享研究制品（与 batch_fork 一致），模板 run 全部复用，不重跑。
SHARED_RESEARCH_ARTIFACTS = (
    "research_brief",
    "video_analysis_brief",
    "source_media_review",
    "media_index",
    "reference_fingerprint",
    "research_breakdown",
    "reference_source_matrix",
    "research_synthesis",
    "research_scorecard",
    "caption_style_fingerprint",
)

RESEARCH_CHECKPOINT_ARTIFACTS = SHARED_RESEARCH_ARTIFACTS


def shared_research_refs(source_project_dir: Path) -> list[dict[str, Any]]:
    """从共享研究源项目读取 9+ 制品的 artifact_sha256 引用，供 template_batch 记录。"""
    refs: list[dict[str, Any]] = []
    for name in SHARED_RESEARCH_ARTIFACTS:
        path = source_project_dir / "artifacts" / f"{name}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sha = str(data.get("artifact_sha256") or data.get("semantic_sha256") or "")
        if sha:
            refs.append({"name": name, "path": f"artifacts/{name}.json", "artifact_sha256": sha})
    return refs


def fork_template_run(
    run_project: str,
    *,
    source_project_dir: Path,
    pipeline_dir: Path,
    product_facts_path: Path | None = None,
) -> Path:
    """把一个 template run 项目播种为可从 proposal 开始的 main-chain 项目。

    幂等：重复运行刷新共享研究副本（同内容=同 hash），写回 completed research checkpoint。
    不覆盖 run 已有的 template_run_plan / product_facts。
    """
    project_dir = init_project(
        run_project,
        title=f"Template run {run_project}",
        pipeline_type="cinematic-fast",
        pipeline_dir=pipeline_dir,
    )

    # 1) 复制共享研究制品
    for name in SHARED_RESEARCH_ARTIFACTS:
        source = source_project_dir / "artifacts" / f"{name}.json"
        if not source.is_file():
            continue
        target = project_dir / "artifacts" / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    # 2) 复制派生 analysis/（证据帧完整性）
    analysis_source = source_project_dir / "analysis"
    if analysis_source.is_dir():
        shutil.copytree(analysis_source, project_dir / "analysis", dirs_exist_ok=True)

    # 3) 复制共享商品事实（若已有 run 自有卡则保留，不覆盖）
    if product_facts_path is not None and product_facts_path.is_file():
        target = project_dir / "artifacts" / "product_facts.json"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(product_facts_path, target)

    # 4) 重建信封 + 写 completed research checkpoint（research 无人门，可完成）。
    envelopes: dict[str, dict[str, Any]] = {}
    for name in RESEARCH_CHECKPOINT_ARTIFACTS:
        path = project_dir / "artifacts" / f"{name}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        envelopes[name] = write_artifact_atomic(
            f"artifacts/{name}.json", name, data, project_dir=project_dir
        )
    write_checkpoint(
        pipeline_dir,
        run_project,
        "research",
        "completed",
        envelopes,
        pipeline_type="cinematic-fast",
        next_action=None,
    )

    # 5) 把共享研究来源 + template 血缘写入 project.json（可追溯）。
    marker_path = project_dir / "project.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["template_run"] = {
        "source_research_project": source_project_dir.name,
        "shared_research_refs": shared_research_refs(source_project_dir),
    }
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_dir

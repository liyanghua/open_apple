"""模板 run 项目：复用共享 research 的一次性 fork 播种。

模板驱动（Req 3）与 candidate fork 同构：**不重新跑一遍完整视频分析**。research 只用
一次（在共享源项目），每个 template run 是一个 fork 出的项目，播种共享 research 制品 +
派生 analysis/ 文件 + 共享商品事实，并写一个 ``completed`` 的 research checkpoint，使该
run 的 `checkpoint.get_next_stage` 从 proposal 开始。这与 `lib.batch_fork` 的 main-chain
复用模式一致，不旁路、不重复分析。

只负责播种 + 校验；不在此做任何创意决策、不写 scene_plan/script 内容（见各 director 契约）。
"""
from __future__ import annotations

import copy
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


def adapt_shared_research_artifact(
    name: str,
    data: Mapping[str, Any],
    *,
    target_input_mode: str | None,
) -> dict[str, Any]:
    """Adapt source-owned evidence provenance to a template run's mode.

    A source-led-template run is still grounded in the same owned observations,
    but validators require its semantic index and matrix to state the consumer
    mode explicitly.  Only those mode discriminators change; reference fields
    remain null and template text never becomes evidence.
    """
    result = copy.deepcopy(dict(data))
    if target_input_mode != "source_led_template":
        return result
    if name == "source_semantic_index" and result.get("input_mode") == "source_led":
        result["input_mode"] = "source_led_template"
    elif name == "reference_source_matrix" and result.get("matrix_mode") == "source_led":
        result["matrix_mode"] = "source_led_template"
    elif name == "research_brief":
        metadata = result.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("input_mode") == "source_led":
            result["metadata"] = {**dict(metadata), "input_mode": "source_led_template"}
    return result


def shared_research_artifact_names(source_project_dir: Path) -> tuple[str, ...]:
    """Return the canonical Research artifact set owned by the source checkpoint.

    Reference-driven projects keep the legacy ten-artifact bundle.  Source-led
    projects deliberately omit synthetic reference artifacts and may add the
    semantic index plus browser product-page evidence.  Treating the source
    checkpoint as the ownership manifest prevents a fork from silently
    re-introducing ``video_analysis_brief``/``reference_fingerprint`` or
    dropping ``source_semantic_index``.
    """
    checkpoint_path = Path(source_project_dir) / "checkpoint_research.json"
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SHARED_RESEARCH_ARTIFACTS
    artifacts = checkpoint.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return SHARED_RESEARCH_ARTIFACTS
    names = tuple(
        str(name)
        for name in artifacts
        if isinstance(name, str)
        and name
        and (Path(source_project_dir) / "artifacts" / f"{name}.json").is_file()
    )
    return names or SHARED_RESEARCH_ARTIFACTS


def materialize_template_run_provenance(
    project_dir: Path,
    *,
    template_pack_path: Path,
    batch_project_id: str,
) -> dict[str, Any]:
    """Copy the canonical pack into a run and bind its batch-root ownership."""
    if not template_pack_path.is_file():
        raise FileNotFoundError(f"template pack not found: {template_pack_path}")
    pack = json.loads(template_pack_path.read_text(encoding="utf-8"))
    validate_artifact("template_pack", pack)
    target = project_dir / "artifacts" / "template_pack.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_pack_path, target)
    marker_path = project_dir / "project.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    prior = dict(marker.get("template_prior") or {})
    prior.update({
        "present": True,
        "usage": "structural_only",
        "template_pack_ref": "artifacts/template_pack.json",
    })
    marker["template_prior"] = prior
    run = dict(marker.get("template_run") or {})
    run["batch_project_id"] = str(batch_project_id)
    marker["template_run"] = run
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return pack


def shared_research_refs(source_project_dir: Path) -> list[dict[str, Any]]:
    """从共享研究源项目读取 9+ 制品的 artifact_sha256 引用，供 template_batch 记录。"""
    refs: list[dict[str, Any]] = []
    for name in shared_research_artifact_names(source_project_dir):
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
    input_mode: str | None = None,
    template_prior: Mapping[str, Any] | None = None,
    template_pack_path: Path | None = None,
    batch_project_id: str | None = None,
    product_input: Mapping[str, Any] | None = None,
) -> Path:
    """把一个 template run 项目播种为可从 proposal 开始的 main-chain 项目。

    幂等：重复运行刷新共享研究副本（同内容=同 hash），写回 completed research checkpoint。
    不覆盖 run 已有的 template_run_plan / product_facts。
    """
    if product_input is None:
        try:
            source_marker = json.loads(
                (Path(source_project_dir) / "project.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            source_marker = {}
        inherited_product_input = source_marker.get("product_input")
        if isinstance(inherited_product_input, Mapping):
            product_input = dict(inherited_product_input)

    project_dir = init_project(
        run_project,
        title=f"Template run {run_project}",
        pipeline_type="cinematic-fast",
        pipeline_dir=pipeline_dir,
        input_mode=input_mode,
        template_prior=template_prior,
        product_input=product_input,
        owned_source_root="inputs/source",
    )
    if template_pack_path is not None:
        if not batch_project_id:
            raise ValueError("template_pack_path requires batch_project_id")
        materialize_template_run_provenance(
            project_dir,
            template_pack_path=template_pack_path,
            batch_project_id=batch_project_id,
        )

    # 1) 复制共享研究制品
    research_names = shared_research_artifact_names(source_project_dir)
    for name in research_names:
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

    # Raw owned footage remains single-copy.  A project-local link preserves
    # the canonical ``inputs/source/...`` paths consumed by Scene/Assets while
    # avoiding multi-gigabyte duplication for every candidate run.
    source_inputs = source_project_dir / "inputs" / "source"
    run_inputs = project_dir / "inputs" / "source"
    if source_inputs.is_dir() and not run_inputs.exists():
        run_inputs.parent.mkdir(parents=True, exist_ok=True)
        run_inputs.symlink_to(source_inputs.resolve(), target_is_directory=True)

    # 3) 复制共享商品事实（若已有 run 自有卡则保留，不覆盖）
    if product_facts_path is not None and product_facts_path.is_file():
        target = project_dir / "artifacts" / "product_facts.json"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(product_facts_path, target)

    # 4) 重建信封 + 写 completed research checkpoint（research 无人门，可完成）。
    envelopes: dict[str, dict[str, Any]] = {}
    for name in research_names:
        path = project_dir / "artifacts" / f"{name}.json"
        if not path.is_file():
            continue
        data = adapt_shared_research_artifact(
            name,
            json.loads(path.read_text(encoding="utf-8")),
            target_input_mode=input_mode,
        )
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
        **dict(marker.get("template_run") or {}),
        "source_research_project": source_project_dir.name,
        "shared_research_refs": shared_research_refs(source_project_dir),
    }
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_dir

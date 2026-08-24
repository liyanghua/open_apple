"""候选项目分叉测试（Autoresearch §4 / 评审缺口 #1）。"""

from __future__ import annotations

import json
from pathlib import Path

from lib.batch_fork import fork_candidate_projects
from lib.candidate_batch import create_candidate_batch
from lib.checkpoint import init_project, read_checkpoint, write_checkpoint
from lib.artifact_io import write_artifact_atomic
from tests.integration.test_cinematic_fast_end_to_end import PIPELINE, _envelopes

SHARED = [
    "research_brief", "video_analysis_brief", "source_media_review", "media_index",
    "reference_fingerprint", "research_breakdown", "reference_source_matrix",
    "research_synthesis", "research_scorecard", "caption_style_fingerprint",
]


def _source_project(tmp_path: Path) -> Path:
    project = init_project("source-research", title="Shared Research",
                           pipeline_type=PIPELINE, pipeline_dir=tmp_path)
    # 派生证据文件（analysis/），分叉时必须一起复制（B3）。
    frame = project / "analysis" / "reference" / "keyframes" / "frame_0000.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"frame")
    _envelopes(project, SHARED)
    write_checkpoint(
        tmp_path, "source-research", "research", "completed",
        _envelopes(project, SHARED), pipeline_type=PIPELINE,
    )
    return project


def _batch(tmp_path: Path) -> dict:
    candidates = [
        {"candidate_id": "cand-01", "label": "结果先行",
         "project_id": "cand-01",
         "direction": {"hook": "result_first", "pacing": "快切", "packaging": "字幕主导"}},
        {"candidate_id": "cand-02", "label": "痛点先行",
         "project_id": "cand-02",
         "direction": {"hook": "problem_first", "pacing": "问题-解决", "packaging": "口播主导"}},
    ]
    return create_candidate_batch(
        "mix-001",
        shared_research_refs=[
            {"name": name, "path": f"artifacts/{name}.json"} for name in SHARED
        ],
        candidates=candidates,
        source_media_refs=["inputs/source/video-01.mp4", "inputs/source/video-02.mp4"],
    )


def test_fork_creates_candidate_projects_with_valid_research(tmp_path: Path):
    source = _source_project(tmp_path)
    batch = _batch(tmp_path)
    created = fork_candidate_projects(batch, source_project_dir=source, pipeline_dir=tmp_path)

    assert set(created) == {"cand-01", "cand-02"}
    for candidate_id, project_dir in created.items():
        # 共享研究制品 + 派生证据完整复制
        assert (project_dir / "artifacts" / "research_brief.json").is_file()
        assert (project_dir / "artifacts" / "caption_style_fingerprint.json").is_file()
        assert (project_dir / "analysis" / "reference" / "keyframes" / "frame_0000.jpg").is_file()
        # research 检查点完成且有效（B3 派生文件门通过）
        checkpoint = read_checkpoint(tmp_path, candidate_id, "research")
        assert checkpoint["status"] == "completed"
        assert "caption_style_fingerprint" in checkpoint["artifacts"]
        # 候选元数据可追溯
        marker = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        assert marker["candidate"]["candidate_id"] == candidate_id
        assert marker["candidate"]["batch_id"] == "mix-001"
        assert marker["candidate"]["source_research_project"] == "source-research"
        plan = json.loads((project_dir / "artifacts" / "candidate_variant_plan.json").read_text())
        assert plan["approval_status"] == "awaiting_human"
        assert plan["difference_fingerprint"]["structural_shot_count"] >= 3


def test_fork_is_idempotent(tmp_path: Path):
    source = _source_project(tmp_path)
    batch = _batch(tmp_path)
    first = fork_candidate_projects(batch, source_project_dir=source, pipeline_dir=tmp_path)
    second = fork_candidate_projects(batch, source_project_dir=source, pipeline_dir=tmp_path)
    assert set(first) == set(second)
    read_checkpoint(tmp_path, "cand-01", "research")  # 仍有效
    first_plan = (first["cand-01"] / "artifacts" / "candidate_variant_plan.json").read_bytes()
    second_plan = (second["cand-01"] / "artifacts" / "candidate_variant_plan.json").read_bytes()
    assert first_plan == second_plan


def test_fork_copies_batch_product_facts(tmp_path: Path):
    source = _source_project(tmp_path)
    batch = _batch(tmp_path)
    # 批根产品事实卡（batch_id = mix-001）
    batch_root = tmp_path / "mix-001" / "artifacts"
    batch_root.mkdir(parents=True, exist_ok=True)
    (batch_root / "product_facts.json").write_text(
        json.dumps({"version": "1.0", "product_name": "透明桌垫",
                    "sku": "TM-2mm", "price": "49.9元", "params": ["厚度 2mm"]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    created = fork_candidate_projects(batch, source_project_dir=source, pipeline_dir=tmp_path)
    for candidate_id, project_dir in created.items():
        card = project_dir / "artifacts" / "product_facts.json"
        assert card.is_file()
        assert json.loads(card.read_text(encoding="utf-8"))["sku"] == "TM-2mm"

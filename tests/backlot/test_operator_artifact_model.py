from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _node(expression: str) -> dict:
    script = f"""
import {{ createOperatorStore, parseViewSelection, serializeViewSelection }} from './backlot/ui/operator/store.js';
import {{ buildApprovalStages, buildApprovalViewModel }} from './backlot/ui/operator/approval_model.js';
{expression}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _node_dynamic(expression: str) -> dict:
    script = f"""
global.window = {{
  location: {{search: '?from=batch', pathname: '/p/demo', hash: ''}},
  history: {{state: null, replaceState(...args) {{ this.replaced = args[2]; }}, pushState(...args) {{ this.pushed = args[2]; }}}},
}};
const {{ createOperatorStore }} = await import('./backlot/ui/operator/store.js');
{expression}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_store_initializes_gate_and_round_trips_url_selection() -> None:
    result = _node(
        """
const store = createOperatorStore('?stage=sample&artifact=sample_video');
store.setProject({revision:'r1', stages:[
  {id:'script', status:'已完成', version:1, editor:{data:{sections:[]}}},
  {id:'sample', status:'等待确认', version:2, editor:{data:{preview_url:'/sample.mp4'}}},
] , pending_review:{kind:'sample', review_id:'review-1', subject_hash:'hash-1', subject_version:2}});
const snapshot = store.get();
console.log(JSON.stringify({
  gate:snapshot.reviewGateId,
  stage:snapshot.selectedStageId,
  artifact:snapshot.selectedArtifactId,
  parsed:parseViewSelection('?from=batch&stage=assets&artifact=generation_list'),
  url:serializeViewSelection({stageId:'assets', artifactId:'generation_list'}, '?from=batch'),
}));
"""
    )
    assert result == {
        "gate": "sample",
        "stage": "sample",
        "artifact": "sample_video",
        "parsed": {"stageId": "assets", "artifactId": "generation_list"},
        "url": "?from=batch&stage=assets&artifact=generation_list",
    }


def test_store_preserves_valid_selection_and_resets_on_revision_or_subject_change() -> None:
    result = _node(
        """
const project = {revision:'r1', stages:[
  {id:'script', status:'已完成', version:1, editor:{data:{sections:[]}}},
  {id:'sample', status:'等待确认', version:2, editor:{data:{preview_url:'/sample.mp4'}}},
], pending_review:{kind:'sample', review_id:'review-1', subject_hash:'hash-1', subject_version:2}};
const store = createOperatorStore();
store.setProject(project); store.selectStage('script'); store.selectArtifact('production_script');
const preserved = store.get();
store.setProject({...project, summary:{progress_percent:50}});
const sameRevision = store.get();
store.setProject({...project, revision:'r2'});
const changedRevision = store.get();
store.setProject({...project, revision:'r2', stages:[project.stages[0], {...project.stages[1], version:3}]});
const changedVersion = store.get();
store.setProject({...project, revision:'r3', pending_review:{...project.pending_review, subject_hash:'hash-2'}});
const changedSubject = store.get();
console.log(JSON.stringify({
  preserved:[preserved.selectedStageId,preserved.selectedArtifactId],
  sameRevision:[sameRevision.selectedStageId,sameRevision.selectedArtifactId],
  changedRevision:[changedRevision.selectedStageId,changedRevision.selectedArtifactId],
  changedVersion:[changedVersion.selectedStageId,changedVersion.selectedArtifactId],
  changedSubject:[changedSubject.selectedStageId,changedSubject.selectedArtifactId],
}));
"""
    )
    assert result == {
        "preserved": ["script", "production_script"],
        "sameRevision": ["script", "production_script"],
        "changedRevision": ["sample", "sample_video"],
        "changedVersion": ["sample", "sample_video"],
        "changedSubject": ["sample", "sample_video"],
    }


def test_approval_adapter_covers_nine_stages_with_stable_materials_and_missing_state() -> None:
    result = _node(
        """
const stages = buildApprovalStages({stages:[
  {id:'script', status:'等待确认', version:3, summary:'脚本已准备', editor:{data:{sections:[{text:'你好'}]}}},
], pending_review:{kind:'script_lock', review_id:'review-1', subject_hash:'hash-1', subject_version:3}});
console.log(JSON.stringify(stages.map((stage) => ({
  id:stage.stageId, label:stage.stageLabel, first:stage.artifacts[0]?.id,
  count:stage.artifacts.length, health:stage.artifacts[0]?.health,
  actionable:stage.review.actionable,
}))));
"""
    )
    assert [item["id"] for item in result] == [
        "research", "proposal", "script", "scene_plan", "assets", "sample", "edit", "compose", "publish"
    ]
    assert all(item["count"] > 0 for item in result)
    assert result[2]["first"] == "production_script"
    assert result[2]["actionable"] is True
    assert result[0]["health"] in {"missing", "processing"}


def test_approval_adapter_uses_public_projection_fields_and_keeps_pending_gate() -> None:
    result = _node(
        """
const view = buildApprovalViewModel({stages:[
  {id:'scenePlan', status:'已完成', editor:{data:{shots:[{id:'shot-1'}]}}},
  {id:'sample', status:'等待确认', editor:{data:{preview_url:'/sample.mp4', execution_trace:{shots:[]}}}, version:4},
], pending_review:{kind:'sample', subject_hash:'hash-2', subject_version:4}});
const scene = view.stages.find((stage) => stage.stageId === 'scene_plan');
const sample = view.stages.find((stage) => stage.stageId === 'sample');
console.log(JSON.stringify({
  gate:view.reviewGateId,
  sceneHealth:scene.artifacts[0].health,
  sceneSummary:scene.artifacts[0].summary,
  sampleReview:sample.review,
}));
"""
    )
    assert result["gate"] == "sample"
    assert result["sceneHealth"] == "ready"
    assert result["sceneSummary"] == "1 项，可查看详情"
    assert result["sampleReview"] == {
        "actionable": False,
        "reviewId": None,
        "subjectHash": "hash-2",
        "subjectVersion": 4,
    }


def test_research_adapter_keeps_process_outputs_and_business_groups() -> None:
    result = _node(
        """
const research = buildApprovalStages({stages:[{
  id:'research', status:'已完成', editor:{data:{
    substages:[
      {id:'reference', label:'参考片怎么拍', state:'completed', message:'已拆解参考片'},
      {id:'sources', label:'我的素材能不能接上', state:'completed', message:'已检查自有素材'},
      {id:'matching', label:'参考镜头和我的素材怎么对应', state:'completed', message:'已完成逐镜头匹配'},
      {id:'direction', label:'这条片准备怎么做', state:'completed', message:'已整理可选方向'},
      {id:'quality', label:'还有什么没看清', state:'completed', message:'已完成检查'},
    ],
    reference:{title:'参考片', summary:'动作和结果成对', preview_url:'/reference.mp4', scenes:[{description:'刮擦冲突', start_seconds:0, end_seconds:2}]},
    breakdown:{identified:1, needs_review:0, missing:0, rows:[{visual_content:'刮擦冲突', start_seconds:0, end_seconds:2}]},
    source_count:2, usable_count:1, sources:[{label:'素材 A', media_type:'video', summary:'产品近景', reviewed:true, preview_url:'/source.mp4'}],
    risks:['缺少回弹结果镜头'],
    matching:{rows:[{reference_intent:'展示回弹', match_reason:'动作一致', source_media_id:'素材 A', status:'已匹配'}]},
    directions:[{title:'真实测试', promise:'用动作证明效果', keep:['动作'], change:['节奏']}],
    quality:{status:'pass', score:10, max_score:10, checks:[{label:'素材匹配', status:'pass', message:'已检查'}]},
    proposal_handoff:{state:'ready', message:'可以进入创意方案'},
  }}
}]})[0];
console.log(JSON.stringify(research.artifacts.map((artifact) => ({
  id:artifact.id, label:artifact.label, health:artifact.health,
  count:Array.isArray(artifact.payload?.rows) ? artifact.payload.rows.length
    : Array.isArray(artifact.payload?.items) ? artifact.payload.items.length
    : Array.isArray(artifact.payload?.steps) ? artifact.payload.steps.length : null,
}))))
"""
    )
    assert [item["id"] for item in result] == [
        "task_understanding", "research_path", "research_template",
        "reference_highlights", "reference_breakdown", "source_inventory",
        "source_risks", "material_matching", "content_directions",
        "decision_inbox", "research_quality", "proposal_handoff",
    ]
    assert result[1]["count"] == 5
    assert result[4]["count"] == 1
    assert result[5]["count"] == 1
    assert result[7]["count"] == 1


def test_user_selection_uses_browser_history_but_refresh_replaces_current_url() -> None:
    result = _node_dynamic(
        """
const store = createOperatorStore('?from=batch');
store.setProject({stages:[
  {id:'script', status:'已完成', version:1, editor:{data:{sections:[]}}},
  {id:'sample', status:'等待确认', version:2, editor:{data:{preview_url:'/sample.mp4'}}},
], pending_review:{kind:'sample', review_id:'r1', subject_hash:'h1', subject_version:2}});
store.selectStage('script');
console.log(JSON.stringify({replaced:window.history.replaced, pushed:window.history.pushed}));
"""
    )
    assert result["replaced"] == "/p/demo?from=batch&stage=sample&artifact=sample_video"
    assert result["pushed"] == "/p/demo?from=batch&stage=script&artifact=production_script"

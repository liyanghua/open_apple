from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _node(expression: str) -> dict:
    script = f"""
import {{ createOperatorStore, parseViewSelection, serializeViewSelection }} from './backlot/ui/operator/store.js';
import {{ buildApprovalStages }} from './backlot/ui/operator/approval_model.js';
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

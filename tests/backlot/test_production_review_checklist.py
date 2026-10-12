import json
import subprocess
from pathlib import Path

from backlot.production_review_items import _bound_visual_confirmations
from tests.backlot.test_production_review_items import fixture_project, review_items, write_json


def test_color_confirmation_only_appears_for_exact_render(tmp_path):
    path = "artifacts/human_color_review.json"
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "decision": "accept_gray_towel_visual_for_bound_variants",
        "reviewer": {"kind": "human", "id": "user"},
        "media": [{"render": {"path": "renders/A.mp4", "sha256": "a" * 64},
                   "reviewed_interval_seconds": [11.37, 16.1]}],
    }))
    record = {"canonical_artifacts": {"human_color_review": path},
              "render": {"path": "renders/A.mp4", "sha256": "a" * 64}}
    assert len(_bound_visual_confirmations(tmp_path, record)) == 1
    record["render"]["sha256"] = "b" * 64
    assert _bound_visual_confirmations(tmp_path, record) == []


def test_structure_and_scoped_feedback_are_hash_bound(tmp_path):
    fixture_project(tmp_path)
    record_ref = "artifacts/waves/W1/A01/production_record.json"
    record = json.loads((tmp_path / record_ref).read_text())
    manifest = {"entries": [{"content_slot_id": "A01", "record_path": record_ref,
        "render_sha256": record["render"]["sha256"], "structure_id": "detail_showcase",
        "structure_label": "商品细节展示", "planned_structure_relation": "展示试点", "fit": "pilot_outside_P1_P6"}]}
    write_json(tmp_path, "artifacts/review-20261010/structure_inventory.v1.json", manifest)
    write_json(tmp_path, "artifacts/review-20261010/human_feedback.v1.json", {
        "decision": "conditional_creative_acceptance_rework_required", "reviewer": {"kind": "human"},
        "rework_items": [{"id": "opening_impact", "content_slot_ids": ["A01"]}],
    })
    items, _ = review_items(tmp_path)
    assert items[0]["content_structure"]["structure_label"] == "商品细节展示"
    assert "前三秒钩子待加强" in items[0]["scoped_review_status"]
    record["render"]["sha256"] = "b" * 64
    write_json(tmp_path, record_ref, record)
    items, _ = review_items(tmp_path)
    assert items[0]["content_structure"] is None
    assert items[0]["scoped_review_status"] is None


def test_review_workbench_shows_11_actionable_checks_without_marking_them_passed():
    script = r'''
const elements=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.textContent='';elements.push(this);}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(key,fn){this.listeners[key]=fn;}
  pause(){} play(){return Promise.resolve();} scrollIntoView(){}
}
global.document={createElement:tag=>new Element(tag),querySelectorAll:()=>[],getElementById:()=>null};
global.window={location:{search:''}};
const {renderProductionReviews}=await import('./backlot/ui/operator/approval.js');
const ids=['fact_source','product_identity','narration_content','caption_alignment','visual_continuity',
 'opening_motion','opening_framing','frozen_body','opening_join','mix_origin','video_judge'];
const checks=Object.fromEntries(ids.map(id=>[id,{machine_status:['narration_content','caption_alignment'].includes(id)?'fail':'not_run',effective_status:'not_run',observations:[]}]));
const main=new Element('main');
renderProductionReviews(main,{items:[{id:'P1-SELL-A',title:'sample',video_url:'/media/sample.mp4',review_kind:'final_review',
 blocking_checks:ids,checks,review_confirmations:['11.37 秒后的灰色毛巾已由你确认可接受；仅限此成片版本，其他商品画面仍需核看。'],
 content_structure:{structure_id:'claim_chain',structure_label:'卖点直切',planned_structure_relation:'展示试点',fit:'pilot_outside_P1_P6'},
 scoped_review_status:'其他已看过的表现项获条件通过；前三秒钩子待加强；防臭画面待加强'},
 {id:'engineering',title:'3s preview',review_kind:'opening_preview'}]},{canReview:false});
const rows=elements.filter(e=>e.tag==='li'&&e.dataset.checkId);
const text=elements.map(e=>e.textContent).join('|');
const video=elements.find(e=>e.tag==='video');
const seek=elements.find(e=>e.tag==='button'&&e.textContent==='从 2.8 秒看');
await seek.listeners.click();
const structureFilter=elements.find(e=>e.tag==='select'&&e['aria-label']==='按内容结构筛选成片');
structureFilter.value='claim_chain';structureFilter.listeners.change();
const previewCard=elements.find(e=>e.tag==='section'&&e.dataset.productionId==='engineering');
console.log(JSON.stringify({count:rows.length,unique:new Set(rows.map(e=>e.dataset.checkId)).size,
 viewer:text.includes('需要你看／听'),producer:text.includes('制作方补证据'),
 failed:text.includes('自动检查失败'),pending:text.includes('尚未完成'),
 color:text.includes('灰色毛巾已由你确认可接受'),raw:elements.some(e=>e.tag==='summary'&&e.textContent==='查看机器检查原始状态'),
 seek:video.currentTime,autoPassed:text.includes('自动检查通过'),
 structure:text.includes('卖点直切'),scoped:text.includes('防臭画面待加强'),previewHidden:previewCard.hidden}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "count": 11, "unique": 11, "viewer": True, "producer": True,
        "failed": True, "pending": True, "color": True, "raw": True,
        "seek": 2.8, "autoPassed": False, "structure": True,
        "scoped": True, "previewHidden": True,
    }

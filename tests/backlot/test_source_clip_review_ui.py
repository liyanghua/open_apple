"""Exercise the source-purpose UI and API without real media or generation."""
import json
import subprocess
from pathlib import Path

from tests.contracts.test_shot_source_contract import source_fixture


def test_source_ui_prepares_correct_purpose_and_never_offers_film_approval():
    script = r'''
const elements=[], calls=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.listeners={};this.textContent='';this.value='';elements.push(this);}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(key,fn){this.listeners[key]=fn;}
  pause(){} scrollIntoView(){}
}
global.document={createElement:tag=>new Element(tag),querySelectorAll:()=>[],getElementById:()=>null};
global.window={location:{search:'',origin:'http://testserver',reload:()=>{}}};
global.fetch=async (path,options={})=>{
  calls.push({path,body:options.body?JSON.parse(options.body):null});
  return {ok:true,json:async()=>path==='/api/v2/auth/me'?{csrf_token:'test-token'}:{review_id:'source-r',subject_version:1,subject_hash:'a'.repeat(64)}};
};
const {renderProductionReviews}=await import('./backlot/ui/operator/approval.js');
const main=new Element('main');
const common={review_kind:'source_clip',shot_id:'A',revision:'v1',original_purpose_id:'whole',original_purpose_status:'fail',version_ref:'source@sha',review_status:'待审核',checks:{},notes:[],video_url:'/source.mp4'};
renderProductionReviews(main,{items:[
 {...common,id:'A:v1:whole',title:'全貌',purpose_id:'whole',review_allowed:false},
 {...common,id:'A:v1:local',title:'局部',purpose_id:'local',interval:[0,2],review_allowed:true,
 source_observations:[{id:'weave',effective_status:'pass',observed:'可见织纹',method:'frame_sampling'}],requirements:[{id:'weave',description:'织纹'}]}
]},{canReview:true,projectId:'test'});
const buttons=elements.filter(e=>e.tag==='button');
const approve=buttons.filter(e=>e.textContent==='确认本源片用途');
await approve[0].listeners.click();
const prepared=calls.find(c=>c.path.includes('/source-reviews/'));
console.log(JSON.stringify({count:approve.length,filmButton:buttons.some(e=>e.textContent==='验收当前成片'),prepared,
 originalVisible:elements.some(e=>e.textContent.includes('whole · fail'))}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["count"] == 1 and not observed["filmButton"]
    assert observed["originalVisible"]
    assert observed["prepared"] == {"path": "/api/v2/projects/test/source-reviews/A/v1/prepare",
                                    "body": {"purpose_id": "local", "interval": [0, 2]}}


def test_source_prepare_api_and_operator_state(projects_root, backlot_client, make_project):
    project = make_project(projects_root, project_id="test")
    source_fixture(project)
    checkpoint_before = (project / "checkpoint_script.json").read_bytes()
    response = backlot_client.post("/api/v2/projects/test/source-reviews/sofa/v6/prepare",
                                   json={"purpose_id": "local-touch", "interval": [0, 2]})
    assert response.status_code == 200, response.text
    review = response.json()
    assert review["kind"] == "source_clip"
    approved = backlot_client.post(f"/api/v2/projects/test/reviews/{review['review_id']}/approve", json={
        "subject_version": review["subject_version"], "subject_hash": review["subject_hash"], "reason": "该用途通过"})
    assert approved.status_code == 200, approved.text
    assert (project / "checkpoint_script.json").read_bytes() == checkpoint_before
    state = backlot_client.get("/api/v2/projects/test/operator-state")
    assert state.status_code == 200, state.text
    cards = next(stage for stage in state.json()["stages"] if stage["id"] == "assets")["editor"]["data"]["source_reviews"]
    assert len(cards) == 2 and all(card["review_kind"] == "source_clip" for card in cards)

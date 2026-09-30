import json
import subprocess
from pathlib import Path


def test_result_card_renders_evidence_and_reports_import_errors_without_approval():
    script = r'''
const elements=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.textContent='';this.value='';elements.push(this);}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(key,fn){this.listeners[key]=fn;}
  pause(){} scrollIntoView(){}
}
global.document={createElement:tag=>new Element(tag),querySelectorAll:()=>[],getElementById:()=>null};
global.window={location:{search:'',origin:'http://testserver',reload:()=>{global.reloaded=true}}};
global.fetch=async path => path==='/api/v2/auth/me'
  ? {ok:true,json:async()=>({csrf_token:'test-csrf'})}
  : {ok:false,json:async()=>({error:{message:'原始导出校验不符',code:'validation_failed'}})};
const {renderProductionReviews}=await import('./backlot/ui/operator/approval.js');
const main=new Element('main');
renderProductionReviews(main,{items:[{id:'p',title:'Synthetic',version_ref:'p@sha',record_path:'record.json',review_status:'预览待反馈',
 opening_group:{id:'g',experiment_id:'exp',sku:'s',candidate_id:'H01',scope:'preview',role:'variant',shots:[]},
 opening_results:[{import_id:'synthetic',result_version:1,comparison_status:'数据不足',comparison_reasons:['缺少同源基线实测'],conclusion:'已导入，尚无结论',binding_status:'current',
  platform:'Synthetic Platform',account_id:'synthetic-account',publication_id:'post-1',ad_id:null,
  audience:{description:'test users',allocation_method:'synthetic split',allocation_id:'split-1'},
  window:{start:'2026-09-28T00:00:00+08:00',end:'2026-09-29T00:00:00+08:00',timezone:'Asia/Shanghai',semantics:'cumulative',label:'24h'},
  metrics:[{metric_id:'open_rate',definition:'opens / views',kind:'rate',numerator:45,numerator_unit:'open',denominator:100,denominator_unit:'view',count_unit:'event',duration_unit:null,support_count:null,value:.45,status:'observed'}],
  fee:{amount:null,currency:null,settlement_status:'unknown'},raw_export_ref:{path:'assets/raw.csv',sha256:'a'.repeat(64)},sample:{conditions:'synthetic',limitations:'not random'}}]}]},
 {canReview:true,projectId:'film'});
const field=elements.find(e=>e.tag==='textarea' && e['aria-label']==='p 实验结果 JSON');
field.value='not json';
const button=elements.find(e=>e.tag==='button' && e.textContent==='导入实验结果');
await button.listeners.click();
const localError=elements.some(e=>e.textContent.includes('JSON 格式'));
field.value='{}';
await button.listeners.click();
const serverError=elements.some(e=>e.textContent.includes('原始导出校验不符'));
const text=elements.map(e=>e.textContent).join('|');
console.log(JSON.stringify({field:!!field,button:!!button,localError,serverError,
 status:text.includes('数据不足')&&text.includes('已导入，尚无结论'),definition:text.includes('opens / views'),
 raw:text.includes('assets/raw.csv'),unknownFee:text.includes('费用待核实'),approval:elements.some(e=>e.textContent==='确认开头预览反馈')}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"field":True,"button":True,"localError":True,
        "serverError":True,"status":True,"definition":True,"raw":True,
        "unknownFee":True,"approval":False}


def test_stale_import_history_is_visible_when_opening_group_is_invalid():
    script = r'''
const elements=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.textContent='';elements.push(this);}
  append(...children){this.children.push(...children);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(key,fn){this.listeners[key]=fn;}
}
global.document={createElement:tag=>new Element(tag),querySelectorAll:()=>[]};
global.window={location:{search:''}};
const {renderProductionReviews}=await import('./backlot/ui/operator/approval.js');
const main=new Element('main');
renderProductionReviews(main,{items:[{id:'p',title:'Synthetic',version_ref:'p@sha',review_status:'开场登记或依赖已失效',
 opening_group:null,scope_error:'开场登记或依赖已失效',review:null,opening_results:[{
 import_id:'old-import',result_version:1,comparison_status:'不可比',comparison_reasons:['原始导出或绑定的生产证据已变化'],
 conclusion:'已导入，尚无结论',binding_status:'stale',platform:'synthetic',account_id:'test',publication_id:'post',ad_id:null,
 audience:{description:'synthetic',allocation_method:'unknown',allocation_id:null},
 window:{start:'2026-09-29T00:00:00+08:00',end:'2026-09-30T00:00:00+08:00',timezone:'Asia/Shanghai',semantics:'cumulative',label:'24h'},
 metrics:[{metric_id:'rate',definition:'views / impressions',kind:'rate',numerator:60,numerator_unit:'view',denominator:100,denominator_unit:'impression',count_unit:'event',duration_unit:null,support_count:null,value:.6,status:'observed'}],
 fee:{amount:null,currency:null,settlement_status:'unknown'},raw_export_ref:{path:'assets/raw.csv',sha256:'a'.repeat(64)},
 sample:{conditions:'synthetic',limitations:'no real traffic'}}]}]},{canEdit:true,projectId:'film'});
const content=elements.map(e=>e.textContent).join('|');
console.log(JSON.stringify({history:content.includes('old-import') && content.includes('60.00%'),
 stale:content.includes('证据已变化') && content.includes('不可比'),blocker:content.includes('开场登记或依赖已失效'),
 importEnabled:elements.some(e=>e.textContent==='导入实验结果')}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"history": True, "stale": True,
        "blocker": True, "importEnabled": False}

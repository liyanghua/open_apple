from __future__ import annotations
from .clock import business_today
import csv, hashlib, io, json, math, os, shutil, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from . import storage as st
from .importer import parse_file, ImportProblem, MAX_FILE, cents
from .engine import DEFAULT_CONFIG, calculate_ranking, recommendation, POLICY_VERSION, validate_config
from .chengfang import diagnose

st.init()
app=FastAPI(title='短视频付费投流优化工作台',version='1.0.0',docs_url=None,redoc_url=None,openapi_url='/api/openapi.json')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])

@app.middleware('http')
async def local_boundary(request:Request,call_next):
 if request.method not in ('GET','HEAD','OPTIONS'):
  origin=request.headers.get('origin')
  if origin and (urlparse(origin).hostname not in ('localhost','127.0.0.1','::1','testserver') or urlparse(origin).netloc!=request.headers.get('host')):
   return JSONResponse(status_code=403,content={'detail':'仅允许本机同源操作。'})
  length=request.headers.get('content-length')
  if length and int(length)>MAX_FILE+1024*1024: return JSONResponse(status_code=413,content={'detail':'上传不得超过20MB。'})
 resp=await call_next(request)
 resp.headers['X-Content-Type-Options']='nosniff';resp.headers['X-Frame-Options']='DENY'
 if request.url.path.startswith('/api/'):resp.headers['Cache-Control']='no-store'
 return resp

@app.exception_handler(ValueError)
async def badvalue(request,exc):return JSONResponse(status_code=400,content={'detail':str(exc)})


def checkfinite(value,label,low=0,high=10**14,allow_null=False):
 if value is None and allow_null:return None
 if isinstance(value,bool):raise ValueError(f'{label}不能是布尔值')
 try:n=float(value)
 except (TypeError,ValueError):raise ValueError(f'{label}需要数值')
 if not math.isfinite(n) or n<low or n>high:raise ValueError(f'{label}超出有效范围')
 return n

def create_workspace(name,kind='live',config=None):
 if kind not in ('live','historical','demo'):raise ValueError('工作区类型无效')
 if not str(name).strip():raise ValueError('请填写工作区名称')
 w=st.uid();cfg=validate_config(config or DEFAULT_CONFIG)
 with st.transaction() as c:
  c.execute('INSERT INTO workspaces(id,name,kind,config,created_at) VALUES(?,?,?,?,?)',(w,str(name)[:80],kind,st.dumps(cfg),st.now()))
  st.audit(c,w,'workspace_created',{'name':name,'kind':kind})
 return st.get_workspace(w)

@app.get('/api/health')
def health():return {'ok':True,'version':POLICY_VERSION,'server_time':st.now(),'date':business_today().isoformat(),'local_only':True}

@app.get('/api/workspaces')
def workspaces():
 with st.connect() as c:return [st.row_workspace(r) for r in c.execute('SELECT * FROM workspaces ORDER BY created_at')]

@app.post('/api/workspaces')
def newworkspace(body:dict):return create_workspace(body.get('name','我的投流'),body.get('kind','live'))

@app.put('/api/workspaces/{w}/config')
def setconfig(w:str,body:dict):
 cfg=validate_config(body)
 with st.transaction() as c:
  st.get_workspace(w,c)
  c.execute('UPDATE workspaces SET config=?,revision=revision+1 WHERE id=?',(st.dumps(cfg),w))
  st.audit(c,w,'config_updated',cfg)
 return st.get_workspace(w)


def chengfang_context_config(body):
 path=body.get('path')
 plan_id=body.get('plan_id')
 if path not in ('live','product'):raise ValueError('投放路径无效')
 if not isinstance(plan_id,str) or not plan_id.strip():raise ValueError('计划ID无效')
 if body.get('status') not in ('active','paused','stopped'):raise ValueError('计划状态无效')
 started_at=body.get('started_at')
 try:datetime.fromisoformat(started_at)
 except (TypeError,ValueError):raise ValueError('开始时间格式无效')
 target=checkfinite(body.get('marketing_roi_target'),'营销ROI目标',low=0)
 basis_note=body.get('basis_note')
 if not isinstance(basis_note,str) or not basis_note.strip():raise ValueError('请填写口径说明')
 caps={}
 for key in ('base_delivery','star_select','creator_marketing','creator_commission_bid'):
  if key not in body or not isinstance(body[key],bool):raise ValueError(f'{key}必须明确为布尔值')
  caps[key]=body[key]
 base_delivery_only=body.get('base_delivery_only',False)
 if not isinstance(base_delivery_only,bool):raise ValueError('base_delivery_only必须为布尔值')
 return {'plan_id':plan_id.strip(),'path':path,'status':body['status'],'started_at':started_at,
  'marketing_roi_target':target,'basis_note':basis_note.strip(),'base_delivery_only':base_delivery_only,**caps}


@app.put('/api/workspaces/{w}/chengfang/context')
def put_chengfang_context(w:str,body:dict):
 st.get_workspace(w)
 config=chengfang_context_config(body)
 return st.save_plan_context(w,config['path'],config['plan_id'],config)


@app.get('/api/workspaces/{w}/chengfang/contexts')
def get_chengfang_contexts(w:str,path:str|None=None):
 st.get_workspace(w)
 return st.list_plan_contexts(w,path)


CHENGFANG_LABEL_KEYS=('content_type','hook','value_proposition','person','scene','price_expression','duration_band')
CHENGFANG_OPERATION_KINDS=('roi_target_changed','budget_changed','capability_changed','product_changed','landing_changed','material_batch_added')


def chengfang_labels(value):
 if not isinstance(value,dict) or set(value)!=set(CHENGFANG_LABEL_KEYS):raise ValueError('素材标签必须完整包含固定字段')
 labels={}
 for key in CHENGFANG_LABEL_KEYS:
  item=value[key]
  if not isinstance(item,str) or not item.strip() or len(item.strip())>80:raise ValueError(f'{key}必须是1至80个字符')
  labels[key]=item.strip()
 return labels


@app.put('/api/workspaces/{w}/chengfang/plans/{plan_id}/materials/{creative_id}')
def put_chengfang_material(w:str,plan_id:str,creative_id:str,body:dict):
 st.get_workspace(w)
 path=body.get('path')
 if path not in ('live','product'):raise ValueError('投放路径无效')
 labels=chengfang_labels(body.get('labels'))
 return st.save_material_profile(w,path,plan_id,creative_id,labels)


@app.get('/api/workspaces/{w}/chengfang/materials')
def get_chengfang_materials(w:str,path:str,plan_id:str):
 st.get_workspace(w)
 return st.list_material_profiles(w,path,plan_id)


def chengfang_operation_payload(kind,value):
 if not isinstance(value,dict):raise ValueError('操作内容无效')
 def numeric(*keys):
  for key in keys:
   if key in value:return checkfinite(value[key],key,0.000001,10**14)
  raise ValueError('操作内容缺少数值变更')
 def text(*keys):
  for key in keys:
   item=value.get(key)
   if isinstance(item,str) and item.strip() and len(item.strip())<=300:return item.strip()
  raise ValueError('操作内容缺少标识')
 if kind=='roi_target_changed':numeric('roi_target','marketing_roi_target','new')
 elif kind=='budget_changed':numeric('budget','budget_yuan','new')
 elif kind=='capability_changed':
  capabilities=value.get('capabilities')
  status=value.get('status')
  if not (isinstance(capabilities,dict) and capabilities and all(key in ('base_delivery','star_select','creator_marketing','creator_commission_bid') and isinstance(item,bool) for key,item in capabilities.items())) and status not in ('active','paused','stopped'):
   raise ValueError('能力变更内容无效')
 elif kind=='product_changed':text('product_id','sku_id','product_name')
 elif kind=='landing_changed':text('landing_id','landing_url','url')
 else:
  ids=value.get('creative_ids',value.get('material_ids'))
  if not isinstance(ids,list) or not ids or len(ids)>100 or any(not isinstance(item,str) or not item.strip() or len(item.strip())>80 for item in ids):raise ValueError('素材批次内容无效')
 return value


def chengfang_operation(body):
 path=body.get('path');plan_id=body.get('plan_id');kind=body.get('kind');occurred_at=body.get('occurred_at');note=body.get('note')
 if path not in ('live','product'):raise ValueError('投放路径无效')
 st.validate_plan_id(plan_id)
 if kind not in CHENGFANG_OPERATION_KINDS:raise ValueError('操作类型无效')
 if not isinstance(note,str) or not note.strip() or len(note.strip())>500:raise ValueError('请填写操作说明')
 try:datetime.fromisoformat(str(occurred_at).replace('Z','+00:00'))
 except (TypeError,ValueError):raise ValueError('操作时间格式无效')
 payload={**chengfang_operation_payload(kind,body.get('payload')), 'note':note.strip()}
 return path,plan_id,occurred_at,kind,payload


@app.post('/api/workspaces/{w}/chengfang/operations')
def post_chengfang_operation(w:str,body:dict):
 st.get_workspace(w)
 path,plan_id,occurred_at,kind,payload=chengfang_operation(body)
 return st.append_plan_operation(w,path,plan_id,occurred_at,kind,payload)


@app.get('/api/workspaces/{w}/chengfang/operations')
def get_chengfang_operations(w:str,path:str,plan_id:str):
 st.get_workspace(w)
 return st.list_plan_operations(w,path,plan_id)

@app.get('/api/workspaces/{w}/ledger')
def getledger(w:str):return st.ledger(w)


def store_preview(w,data,filename):
 st.get_workspace(w);parsed=parse_file(data,filename)
 with st.connect() as c:
  existing=c.execute('SELECT * FROM imports WHERE workspace_id=? AND sha256=? ORDER BY imported_at DESC LIMIT 1',(w,parsed['sha256'])).fetchone()
 if existing:return public_import(st.import_record(existing))
 rawpath=st.DATA/'raw'/parsed['sha256']
 if not rawpath.exists():rawpath.write_bytes(data)
 i=st.uid();meta={'raw_path':parsed['sha256'],'known_at':None}
 with st.transaction() as c:
  c.execute('INSERT INTO imports(id,workspace_id,filename,sha256,status,imported_at,metadata,data) VALUES(?,?,?,?,?,?,?,?)',
   (i,w,filename,parsed['sha256'],'preview',st.now(),st.dumps(meta),st.dumps(parsed)))
 return public_import(st.get_import(i))

def public_import(i):
 d={k:v for k,v in i.items() if k!='data'}
 data=i['data'];d.update({k:data[k] for k in ('headers','mapping','missing_fields','sheets','sheet','header_row','totals','suggested') if k in data})
 d['issues']=data.get('issues',[])[:100];d['issue_count']=len(data.get('issues',[]));d['preview_rows']=data.get('rows',[])[:5]
 return d

@app.post('/api/imports/preview')
async def preview(workspace_id:str=Form(...),file:UploadFile=File(...)):
 data=await file.read(MAX_FILE+1)
 return store_preview(workspace_id,data,Path(file.filename or 'upload.xlsx').name)

@app.post('/api/imports/{i}/confirm')
def confirm(i:str,body:dict):
 imp=st.get_import(i)
 if imp['status']=='confirmed':return public_import(imp)
 path=body.get('path');start=body.get('period_start');end=body.get('period_end');basis=body.get('basis','reported_net');scope=body.get('scope','')
 if path not in ('live','product'):raise ValueError('请选择推直播或推商品')
 if not scope.strip():raise ValueError('请输入计划／导出范围标识')
 try:
  sd=date.fromisoformat(start);ed=date.fromisoformat(end);window=(ed-sd).days+1
 except (TypeError,ValueError):raise ValueError('请填写有效起止日期')
 if window not in (7,30):raise ValueError('V1接受完整7天或30天汇总；不能把其他窗口冒充7/30天')
 if ed>business_today():raise ValueError('截止日不能晚于今天')
 if not body.get('scope_confirmed'):raise ValueError('请确认范围及字段语义')
 raw=(st.DATA/'raw'/imp['sha256']).read_bytes()
 parsed=parse_file(raw,imp['filename'],body.get('mapping') or None,body.get('sheet'),body.get('header_row'))
 if parsed['missing_fields']:raise ValueError('必要字段未映射：'+','.join(parsed['missing_fields']))
 chengfang=st.get_workspace(imp['workspace_id'])['config'].get('delivery_mode')=='chengfang'
 chengfang_meta={}
 if chengfang:
  plan_id=body.get('plan_id')
  partition=body.get('partition')
  if not isinstance(plan_id,str) or not plan_id.strip():raise ValueError('请填写计划ID')
  plan_id=plan_id.strip()
  if partition not in ('chengfang','all_domain','overall'):raise ValueError('分区无效')
  cost_basis=body.get('cost_basis')
  if not isinstance(cost_basis,str) or not cost_basis.strip():raise ValueError('请填写成本口径')
  cost_grain=body.get('cost_grain')
  if cost_grain != 'material_attributable':raise ValueError('成本粒度必须是material_attributable')
  context=st.get_plan_context(imp['workspace_id'],path,plan_id)
  base_delivery_only=bool(context and context['config'].get('base_delivery_only'))
  if not parsed['mapping'].get('marketing_cost') and not base_delivery_only:
   raise ValueError('成方素材ROI需要营销消耗字段；仅基础投放可使用整体消耗')
  missing_cost_rows=[r['source_row'] for r in parsed['rows'] if not r['is_aggregate'] and r.get('marketing_cost') is None]
  if missing_cost_rows and not base_delivery_only:
   raise ValueError('非汇总素材行缺少营销消耗：'+','.join(map(str,missing_cost_rows[:10])))
  try:plan_marketing_cost=cents(body.get('plan_marketing_cost'))
  except ImportProblem:raise ValueError('计划营销成本无效')
  if plan_marketing_cost is None:raise ValueError('请填写计划营销成本')
  has_plan_id_column=bool(parsed['mapping'].get('plan_id'))
  if has_plan_id_column:
   mismatched=[r['source_row'] for r in parsed['rows'] if not r['is_aggregate'] and r.get('plan_id')!=plan_id]
   if mismatched:raise ValueError('非汇总素材行计划ID与声明计划不一致：'+','.join(map(str,mismatched[:10])))
  material_rows=[r for r in parsed['rows'] if not r['is_aggregate'] and not r['errors']]
  material_cost_sum=sum((r.get('marketing_cost') if r.get('marketing_cost') is not None else r.get('spend') or 0) for r in material_rows)
  tolerance_fen=max(100,round(plan_marketing_cost*.01))
  unattributed_cost_fen=plan_marketing_cost-material_cost_sum
  reconciled=abs(unattributed_cost_fen)<=tolerance_fen
  chengfang_meta={'plan_id':plan_id,'path':path,'partition':partition,'period_start':start,'period_end':end,
   'cost_basis':cost_basis.strip(),'cost_grain':cost_grain,'plan_marketing_cost':plan_marketing_cost,
   'base_delivery_only':base_delivery_only,'plan_id_confirmation':'source_matched' if has_plan_id_column else 'manual_confirmed',
   'delivery_context':({key:context['config'][key] for key in ('base_delivery','star_select','creator_marketing','creator_commission_bid')} if context else None),
   'capability_context':({'status':context['config']['status']} if context else None),
   'material_cost_sum':material_cost_sum,'eligible_material_ids':[r['creative_id'] for r in material_rows],
   'reconciliation':{'material_cost_sum':material_cost_sum,'plan_marketing_cost':plan_marketing_cost,
    'tolerance_fen':tolerance_fen,'unattributed_cost_fen':unattributed_cost_fen,'reconciled':reconciled,
    'blocks_material_roi':not reconciled}}
 known=body.get('known_at') or None
 if known:
  try:datetime.fromisoformat(known)
  except ValueError:raise ValueError('可获得时间格式无效')
 meta={**imp['metadata'],'scope_confirmed':True,'basis_note':body.get('basis_note','净额成熟范围待确认'),'timezone':'Asia/Shanghai',**chengfang_meta}
 with st.transaction() as c:
  c.execute('UPDATE imports SET status=?,path=?,period_start=?,period_end=?,window=?,basis=?,scope=?,complete=?,known_at=?,metadata=?,data=? WHERE id=?',
   ('confirmed',path,start,end,window,basis,scope,bool(body.get('complete',True)),known,st.dumps(meta),st.dumps(parsed),i))
  st.audit(c,imp['workspace_id'],'import_confirmed',{'id':i,'source':imp['filename'],'totals':parsed['totals']})
 return public_import(st.get_import(i))


@app.post('/api/workspaces/{w}/chengfang/imports/{source_id}/reuse')
def reuse_history_import(w:str,source_id:str,body:dict):
 st.get_workspace(w)
 source=st.get_import(source_id)
 if source['workspace_id']!=w:raise ValueError('只能复用当前工作区的历史导入')
 if source['status']!='confirmed' or source['complete'] is not True or source['window']!=7:
  raise ValueError('只能复用已确认完整的7天历史导入')
 path=body.get('path')
 if path not in ('live','product') or path!=source['path']:raise ValueError('历史导入的投放路径不一致')
 plan_id=body.get('plan_id')
 if not isinstance(plan_id,str) or not plan_id.strip():raise ValueError('请填写计划ID')
 plan_id=plan_id.strip()
 context=st.get_plan_context(w,path,plan_id)
 if not context:raise ValueError('请先保存计划上下文')
 if body.get('cost_basis')!='marketing_cost' or body.get('cost_grain')!='material_attributable':
  raise ValueError('历史快照必须确认营销消耗与素材可归属成本')
 try:plan_marketing_cost=cents(body.get('plan_marketing_cost'))
 except ImportProblem:raise ValueError('计划营销成本无效')
 if plan_marketing_cost is None:raise ValueError('请填写计划营销成本')
 base_delivery_only=bool(context['config'].get('base_delivery_only'))
 rows=(source.get('data') or {}).get('rows') or []
 mapping=(source.get('data') or {}).get('mapping') or {}
 if not mapping.get('marketing_cost') and not base_delivery_only:
  raise ValueError('历史导入缺少营销消耗字段；仅基础投放可确认使用整体消耗')
 if mapping.get('plan_id'):
  mismatched=[r.get('source_row') for r in rows if not r.get('is_aggregate') and r.get('plan_id')!=plan_id]
  if mismatched:raise ValueError('非汇总素材行计划ID与声明计划不一致：'+','.join(map(str,mismatched[:10])))
 material_rows=[r for r in rows if not r.get('is_aggregate') and not r.get('errors')]
 missing_cost=[r.get('source_row') for r in material_rows if r.get('marketing_cost') is None and not base_delivery_only]
 if missing_cost:raise ValueError('非汇总素材行缺少营销消耗：'+','.join(map(str,missing_cost[:10])))
 material_cost_sum=sum((r.get('marketing_cost') if r.get('marketing_cost') is not None else r.get('spend') or 0) for r in material_rows)
 tolerance_fen=max(100,round(plan_marketing_cost*.01));unattributed_cost_fen=plan_marketing_cost-material_cost_sum
 chengfang_meta={'plan_id':plan_id,'path':path,'partition':'chengfang','period_start':source['period_start'],'period_end':source['period_end'],
  'cost_basis':'marketing_cost','cost_grain':'material_attributable','plan_marketing_cost':plan_marketing_cost,
  'base_delivery_only':base_delivery_only,'plan_id_confirmation':'source_matched' if mapping.get('plan_id') else 'manual_confirmed',
  'delivery_context':{key:context['config'][key] for key in ('base_delivery','star_select','creator_marketing','creator_commission_bid')},
  'capability_context':{'status':context['config']['status']},'material_cost_sum':material_cost_sum,
  'eligible_material_ids':[r['creative_id'] for r in material_rows],
  'reconciliation':{'material_cost_sum':material_cost_sum,'plan_marketing_cost':plan_marketing_cost,'tolerance_fen':tolerance_fen,
   'unattributed_cost_fen':unattributed_cost_fen,'reconciled':abs(unattributed_cost_fen)<=tolerance_fen,
   'blocks_material_roi':abs(unattributed_cost_fen)>tolerance_fen}}
 scope=body.get('scope') or source['scope']
 if not isinstance(scope,str) or not scope.strip():raise ValueError('请输入计划／导出范围标识')
 metadata={**source['metadata'],'scope_confirmed':True,'timezone':'Asia/Shanghai',**chengfang_meta,
  'reused_from_import_id':source['id'],'history_snapshot':True}
 snapshot_id=st.uid()
 with st.transaction() as c:
  c.execute('INSERT INTO imports(id,workspace_id,filename,sha256,status,path,period_start,period_end,window,basis,scope,complete,imported_at,known_at,metadata,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
   (snapshot_id,w,'历史快照｜'+source['filename'],source['sha256'],'confirmed',path,source['period_start'],source['period_end'],7,
    source['basis'],scope.strip(),True,st.now(),source.get('known_at'),st.dumps(metadata),st.dumps(source['data'])))
  st.audit(c,w,'history_import_reused',{'id':snapshot_id,'source_import_id':source['id'],'plan_id':plan_id})
 return public_import(st.get_import(snapshot_id))

@app.get('/api/workspaces/{w}/imports')
def getimports(w:str):
 with st.connect() as c:return [public_import(st.import_record(r)) for r in c.execute('SELECT * FROM imports WHERE workspace_id=? ORDER BY period_end DESC,imported_at DESC',(w,))]

@app.get('/api/imports/{i}')
def getimport(i:str):return public_import(st.get_import(i))


def diagnosis_period(snapshot):
 try:
  start=date.fromisoformat(snapshot['period_start']);end=date.fromisoformat(snapshot['period_end'])
 except (KeyError,TypeError,ValueError):raise ValueError('诊断导入时间窗口无效')
 if snapshot.get('window')!=7 or (end-start).days!=6:raise ValueError('诊断只接受完整7天导入')
 return start,end


def validate_diagnosis_snapshot(snapshot,w,plan_id,path,context):
 if snapshot.get('workspace_id')!=w or snapshot.get('status')!='confirmed' or snapshot.get('complete') is not True:
  raise ValueError('只能选择本工作区已确认完整导入')
 meta=snapshot.get('metadata') or {}
 if (meta.get('plan_id')!=plan_id or snapshot.get('path')!=path or meta.get('partition')!='chengfang' or
     meta.get('cost_basis')!='marketing_cost' or meta.get('cost_grain')!='material_attributable'):
  raise ValueError('诊断导入与计划、路径、分区或成本口径不一致')
 if not isinstance(snapshot.get('scope'),str) or not snapshot['scope'].strip():raise ValueError('诊断导入缺少指标范围')
 config=context['config']
 expected_delivery={key:config[key] for key in ('base_delivery','star_select','creator_marketing','creator_commission_bid')}
 expected_capability={'status':config['status']}
 if (meta.get('base_delivery_only')!=bool(config.get('base_delivery_only')) or
     meta.get('delivery_context')!=expected_delivery or meta.get('capability_context')!=expected_capability):
  raise ValueError('计划上下文与导入投放条件不一致')
 return diagnosis_period(snapshot)


def diagnosis_payload(w,plan_id,path,current_id,prior_id=None):
 ws=st.get_workspace(w)
 context=st.get_plan_context(w,path,plan_id)
 if not context:raise ValueError('请先保存计划上下文')
 current=st.get_import(current_id)
 current_window=validate_diagnosis_snapshot(current,w,plan_id,path,context)
 prior=None
 if prior_id is not None:
  if prior_id==current_id:raise ValueError('两期诊断导入必须不同')
  prior=st.get_import(prior_id)
  prior_window=validate_diagnosis_snapshot(prior,w,plan_id,path,context)
  current_meta=current['metadata'];prior_meta=prior['metadata']
  keys=('plan_id','partition','cost_basis','cost_grain','base_delivery_only','delivery_context','capability_context')
  if any(prior_meta.get(key)!=current_meta.get(key) for key in keys) or prior.get('scope')!=current.get('scope'):
   raise ValueError('两期导入的计划、路径、分区、成本口径或指标范围不一致')
  if prior_window[1]>=current_window[0]:raise ValueError('两期诊断导入必须是不重叠的完整7天窗口')
 profiles=st.list_material_profiles(w,path,plan_id)
 operations=st.list_plan_operations(w,path,plan_id)
 result=diagnose(current,prior,context,profiles,ws['config'],operations)
 result['frozen_inputs']['workspace_config_revision']=ws['revision']
 return result


@app.post('/api/chengfang/diagnosis-runs')
def post_chengfang_diagnosis(body:dict):
 w=body.get('workspace_id');plan_id=body.get('plan_id');path=body.get('path')
 if path not in ('live','product'):raise ValueError('投放路径无效')
 st.validate_plan_id(plan_id)
 current_id=body.get('current_import_id')
 if not isinstance(current_id,str) or not current_id:raise ValueError('请选择当前导入')
 prior_id=body.get('prior_import_id')
 if prior_id is not None and (not isinstance(prior_id,str) or not prior_id):raise ValueError('前期导入无效')
 return st.create_diagnosis_run(w,path,plan_id,diagnosis_payload(w,plan_id,path,current_id,prior_id))


@app.get('/api/chengfang/diagnosis-runs/{i}')
def get_chengfang_diagnosis(i:str):return st.get_diagnosis_run(i)


@app.get('/api/workspaces/{w}/chengfang/diagnosis-runs')
def get_chengfang_diagnoses(w:str,path:str|None=None,plan_id:str|None=None):
 st.get_workspace(w)
 return st.list_diagnosis_runs(w,path,plan_id)


def csv_safe(value):
 if value is None:return ''
 text=str(value)
 return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text


@app.get('/api/chengfang/diagnosis-runs/{i}/export')
def export_chengfang_diagnosis(i:str):
 record=st.get_diagnosis_run(i);payload=record['payload'];out=io.StringIO();writer=csv.writer(out)
 writer.writerow(['类型','素材ID/标签','样本状态','诊断结论','原因码','警告'])
 for card in payload.get('material_cards',[]):
  writer.writerow([csv_safe(item) for item in ('素材',card.get('creative_id'),card.get('sample_state'),card.get('decision'),'；'.join(card.get('reason_codes') or []),'；'.join(card.get('warnings') or []))])
 for card in payload.get('direction_cards',[]):
  writer.writerow([csv_safe(item) for item in ('方向',' / '.join(card.get('labels') or []),str(card.get('period_count','')),card.get('decision'),'；'.join(card.get('reason_codes') or []),'；'.join(card.get('operation_warnings') or []))])
 return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="chengfang-diagnosis-{record["id"]}.csv"'})

@app.get('/api/imports/{i}/source')
def source(i:str):
 imp=st.get_import(i);return FileResponse(st.DATA/'raw'/imp['sha256'],filename=imp['filename'])

@app.post('/api/ranking-runs')
def rank(body:dict):
 w=body.get('workspace_id');ws=st.get_workspace(w)
 i30=st.get_import(body['import_30']) if body.get('import_30') else None
 i7=st.get_import(body['import_7']) if body.get('import_7') else None
 for imp in (i30,i7):
  if imp and (imp['workspace_id']!=w or imp['status']!='confirmed'):raise ValueError('只能选择本工作区已确认导入')
  if imp and imp['metadata'].get('reconciliation') and not imp['metadata']['reconciliation'].get('reconciled'):
   raise ValueError('成方成本对账未通过，不能计算素材ROI')
 if i30 and i30['window']!=30:raise ValueError('长期输入必须为30天')
 if i7 and i7['window']!=7:raise ValueError('近期输入必须为7天')
 if i30 and i7 and i30['path']!=i7['path']:raise ValueError('推商品与推直播分榜，不混合')
 if not i30 and not i7:raise ValueError('请选择数据')
 with st.connect() as c:
  weeks=[st.import_record(r) for r in c.execute("SELECT * FROM imports WHERE workspace_id=? AND status='confirmed' AND window=7 ORDER BY imported_at ASC",(w,))]
 payload=calculate_ranking(i30,i7,ws['config'],weeks=weeks,requested_mode=body.get('mode','auto'),exposure_tier=body.get('exposure_tier','all'),objective=body.get('objective','legacy'))
 if ws['kind']=='historical':payload['stale']=True;payload['warnings'].append('历史回放工作区：不产生可执行追投建议。')
 payload['workspace_kind']=ws['kind'];payload['workspace_revision']=ws['revision']
 payload['summary_30']=(i30 or i7)['data']['totals']
 id=st.uid();payload['id']=id;payload['created_at']=st.now()
 with st.transaction() as c:
  c.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(id,w,payload['path'],st.now(),st.dumps(payload)))
  st.audit(c,w,'ranking_created',{'id':id,'top_ids':payload['top_ids'],'snapshots':payload['snapshot_ids']})
 return payload

@app.get('/api/ranking-runs/{i}')
def getrank(i:str):return st.get_run(i)['payload']

@app.get('/api/workspaces/{w}/runs')
def getruns(w:str):
 with st.connect() as c:
  return [{'id':r['id'],'path':r['path'],'created_at':r['created_at'],**{k:json.loads(r['payload']).get(k) for k in ('period_end','mode','top_ids','stale','objective','exposure_tier')}} for r in c.execute('SELECT * FROM runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100',(w,))]

TASK_MONEY=('bid','bid_cap','bid_step','budget','spent','addon_cap','risk_remaining','fixed_test_budget','task_net_gmv')

def save_task(w,path,cid,body):
 st.get_workspace(w)
 if path not in ('live','product') or not str(cid).strip():raise ValueError('任务对象无效')
 if not str(body.get('task_id','')).strip():raise ValueError('请填写平台独立追投任务ID或内部唯一任务标识')
 cfg={k:v for k,v in body.items() if k not in ('id','revision','updated_at')}
 for k in TASK_MONEY:
  n=checkfinite(cfg.get(k),k,0,10**14,True);cfg[k]=None if n is None else int(n)
 if cfg.get('bid_step') is not None and cfg['bid_step']<=0:raise ValueError('价格步长必须大于0')
 cfg['review_hours']=checkfinite(cfg.get('review_hours'),'观察小时',0.01,2160,True)
 if cfg.get('task_basis') not in ('reported_net','net_1h','matured_net'):raise ValueError('请指定任务净额口径')
 for k in ('scope_confirmed','context_confirmed','mixed_scope_confirmed','config_fresh','product_ok','task_result_verified'):
  cfg[k]=bool(cfg.get(k,False))
 with st.transaction() as c:
  old=st.get_task(w,path,cid,c)
  pending=c.execute("SELECT 1 FROM proposals WHERE workspace_id=? AND path=? AND creative_id=? AND status IN ('approved','executed')",(w,path,cid)).fetchone()
  if pending:raise ValueError('当前有待执行／复核动作；先取消未执行提案或完成复核，避免覆盖基准设置')
  if old:
   cfg['last_verified_budget']=old.get('last_verified_budget');cfg['last_verified_bid']=old.get('last_verified_bid')
   c.execute('UPDATE tasks SET config=?,revision=revision+1,updated_at=? WHERE id=?',(st.dumps(cfg),st.now(),old['id']))
  else:c.execute('INSERT INTO tasks(id,workspace_id,path,creative_id,config,updated_at) VALUES(?,?,?,?,?,?)',(st.uid(),w,path,cid,st.dumps(cfg),st.now()))
  st.audit(c,w,'task_configuration_saved',{'path':path,'creative_id':cid,'config':cfg})
 return st.get_task(w,path,cid)

@app.put('/api/workspaces/{w}/tasks/{path}/{cid}')
def taskput(w:str,path:str,cid:str,body:dict):return save_task(w,path,cid,body)

@app.get('/api/workspaces/{w}/tasks/{path}/{cid}')
def taskget(w:str,path:str,cid:str):return st.get_task(w,path,cid)

@app.get('/api/workspaces/{w}/tasks')
def alltasks(w:str):
 with st.connect() as c:
  return [{'creative_id':r['creative_id'],'path':r['path'],**json.loads(r['config']),'id':r['id'],'revision':r['revision']} for r in c.execute('SELECT * FROM tasks WHERE workspace_id=?',(w,))]

@app.post('/api/recommendation-runs')
def recommend(body:dict):
 rr=st.get_run(body.get('run_id'));w=rr['workspace_id'];ws=st.get_workspace(w);run=rr['payload']
 if ws['config'].get('delivery_mode')=='chengfang':
  raise HTTPException(status_code=409,detail='乘方模式只生成素材诊断，不生成单素材预算或出价提案')
 if run['workspace_revision']!=ws['revision']:raise ValueError('规则／预算配置已变化，请重新运行排序后生成建议')
 balance=st.ledger(w);free=balance['free'];out=[]
 wanted=body.get('creative_ids') or run['top_ids']
 if len(wanted)>3 or len(set(wanted))!=len(wanted):raise ValueError('每轮最多三个不同素材')
 for cid in wanted:
  if cid not in run['top_ids']:raise ValueError('仅为本轮TOP3生成追加建议；其他对象可查看或调整规则后重排')
  item=next(r for r in run['results'] if r['creative_id']==cid)
  task=st.get_task(w,run['path'],cid)
  with st.connect() as c:
   pend=c.execute("SELECT 1 FROM proposals WHERE workspace_id=? AND path=? AND creative_id=? AND status IN ('approved','executed')",(w,run['path'],cid)).fetchone()
   success=c.execute("SELECT COUNT(*) FROM proposals WHERE workspace_id=? AND path=? AND creative_id=? AND status='reviewed' AND json_extract(review,'$.passed')=1",(w,run['path'],cid)).fetchone()[0]
  proposal=recommendation(item,run,task,ws['config'],free,is_replay=ws['kind']=='demo',pending=bool(pend),success_count=success)
  proposal['run_id']=rr['id'];proposal['source_refs']=item['sources'];proposal['score']=item['score']
  proposal['policy_version']=POLICY_VERSION
  # deterministic ID makes repeated clicks idempotent
  h=hashlib.sha256(st.dumps([rr['id'],cid,task,ws['revision'],proposal['action_type'],proposal['budget_new'],proposal['bid_new']]).encode()).hexdigest()[:32]
  proposal['id']=h
  with st.transaction() as c:
   c.execute('INSERT OR IGNORE INTO proposals(id,workspace_id,run_id,task_id,creative_id,path,created_at,expires_at,config_revision,task_revision,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
    (h,w,rr['id'],task['id'] if task else None,cid,run['path'],st.now(),(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),ws['revision'],task['revision'] if task else None,st.dumps(proposal)))
  out.append(proposal)
  if free is not None:free=max(0,free-proposal['reserve'])
 return {'proposals':out,'ledger':balance,'unallocated':free}


def proposal_row(row):
 d=dict(row);d['payload']=json.loads(d['payload']);d['execution']=json.loads(d['execution']) if d.get('execution') else None;d['review']=json.loads(d['review']) if d.get('review') else None;return d

@app.get('/api/workspaces/{w}/actions')
def actions(w:str):
 with st.connect() as c:return [proposal_row(r) for r in c.execute('SELECT * FROM proposals WHERE workspace_id=? ORDER BY created_at DESC LIMIT 300',(w,))]

@app.post('/api/recommendations/{i}/approve')
def approve(i:str,body:dict):
 if not body.get('confirm'):raise ValueError('需人工确认本地批准不等于平台执行')
 with st.transaction() as c:
  row=c.execute('SELECT * FROM proposals WHERE id=?',(i,)).fetchone()
  if not row:raise ValueError('建议不存在')
  p=proposal_row(row);ws=st.get_workspace(p['workspace_id'],c)
  if p['status']=='approved':return {'id':i,'status':'approved','idempotent':True}
  if p['status']!='draft':raise ValueError('该建议不是可批准状态')
  if datetime.fromisoformat(p['expires_at'])<datetime.now(timezone.utc):raise ValueError('提案已过期，请先重新计算排名再生成建议；原记录保留')
  if p['config_revision']!=ws['revision']:raise ValueError('配置已变化，请重新生成建议')
  run=st.get_run(p['run_id'],c)['payload'];task=st.get_task(ws['id'],p['path'],p['creative_id'],c)
  if not task or task['revision']!=p['task_revision']:raise ValueError('当前任务配置已变化')
  pending=c.execute("SELECT 1 FROM proposals WHERE workspace_id=? AND path=? AND creative_id=? AND status IN ('approved','executed')",(ws['id'],p['path'],p['creative_id'])).fetchone()
  if pending:raise ValueError('该素材已有未完成动作，不能重复批准')
  age=(business_today()-date.fromisoformat(run['period_end'])).days
  if age>ws['config']['freshness_days'] or ws['kind']=='historical':raise ValueError('历史数据不允许批准当前动作')
  ledger=st.ledger(ws['id'],c);item=next(x for x in run['results'] if x['creative_id']==p['creative_id'])
  success=c.execute("SELECT COUNT(*) FROM proposals WHERE workspace_id=? AND creative_id=? AND path=? AND status='reviewed' AND json_extract(review,'$.passed')=1",(ws['id'],p['creative_id'],p['path'])).fetchone()[0]
  checked=recommendation(item,run,task,ws['config'],ledger['free'],is_replay=ws['kind']=='demo',success_count=success)
  expected=p['payload']
  if checked['action_type'] not in ('BUDGET_TEST','BID_TEST','NEW_BOOST_TEST'):raise ValueError('当前条件不再允许试探：'+checked['reasons'][0])
  if any(checked[k]!=expected[k] for k in ('action_type','reserve','budget_new','bid_new')):raise ValueError('可用额度或条件已变化，请重新生成，不自动改动已展示方案')
  c.execute("UPDATE proposals SET status='approved',reserved=?,approved_at=? WHERE id=?",(checked['reserve'],st.now(),i))
  st.audit(c,ws['id'],'proposal_approved',{'id':i,'reserved':checked['reserve']})
 return {'id':i,'status':'approved'}

@app.post('/api/actions/{i}/execution')
def executed(i:str,body:dict):
 if not body.get('confirm_platform_done'):raise ValueError('请确认已人工在平台执行；本系统不操作平台')
 with st.transaction() as c:
  row=c.execute('SELECT * FROM proposals WHERE id=?',(i,)).fetchone()
  if not row:raise ValueError('提案不存在')
  p=proposal_row(row)
  if p['status']=='executed':return {'id':i,'status':'executed','idempotent':True}
  if p['status']!='approved':raise ValueError('请先批准并预留额度')
  payload=p['payload'];task=st.get_task(p['workspace_id'],p['path'],p['creative_id'],c)
  actualbudget=int(checkfinite(body.get('budget_new'),'实际预算',0));actualbid=int(checkfinite(body.get('bid_new'),'实际出价',0))
  if actualbudget!=payload['budget_new'] or actualbid!=payload['bid_new']:raise ValueError('实际值与批准方案不符；请先取消未执行提案，重新配置／生成。不得超批准值')
  executed_at=body.get('executed_at') or st.now()
  try:when=datetime.fromisoformat(executed_at)
  except ValueError:raise ValueError('执行时间无效')
  if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
  if when>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('执行时间不能在未来')
  review_after=(when+timedelta(hours=payload['review_hours'])).isoformat()
  record={'executed_at':when.isoformat(),'review_after':review_after,'budget_new':actualbudget,'bid_new':actualbid,'note':body.get('note',''),'platform_execution':'manual_record_only'}
  task.update({'budget':actualbudget,'bid':actualbid})
  task.pop('revision',None);task.pop('updated_at',None);task.pop('id',None)
  c.execute('UPDATE tasks SET config=?,revision=revision+1,updated_at=? WHERE id=?',(st.dumps(task),st.now(),p['task_id']))
  c.execute("UPDATE proposals SET status='executed',execution=? WHERE id=?",(st.dumps(record),i))
  st.audit(c,p['workspace_id'],'platform_execution_recorded',{'id':i,**record})
 return {'id':i,'status':'executed','review_after':review_after}

@app.post('/api/actions/{i}/cancel')
def cancel(i:str,body:dict):
 with st.transaction() as c:
  row=c.execute('SELECT * FROM proposals WHERE id=?',(i,)).fetchone()
  if not row:raise ValueError('建议不存在')
  p=proposal_row(row)
  if p['status']=='cancelled':return {'status':'cancelled','idempotent':True}
  if p['status'] not in ('draft','approved'):raise ValueError('已执行动作不能删除或释放已发生费用，请提交复核')
  c.execute("UPDATE proposals SET status='cancelled',reserved=0 WHERE id=?",(i,))
  st.audit(c,p['workspace_id'],'proposal_cancelled',{'id':i,'reason':body.get('reason','人工取消')})
 return {'status':'cancelled'}

@app.post('/api/actions/{i}/review')
def review(i:str,body:dict):
 with st.transaction() as c:
  row=c.execute('SELECT * FROM proposals WHERE id=?',(i,)).fetchone()
  if not row:raise ValueError('建议不存在')
  p=proposal_row(row);ws=st.get_workspace(p['workspace_id'],c)
  if p['status']=='reviewed':return {'status':'reviewed','idempotent':True}
  if p['status']!='executed':raise ValueError('只有已记录执行的动作可复核')
  maturity=body.get('maturity')
  if maturity not in ('pending','provisional','matured'):raise ValueError('请选择成熟状态')
  after=datetime.fromisoformat(p['execution']['review_after'])
  if maturity=='matured' and datetime.now(timezone.utc)<after and ws['kind']!='demo':raise ValueError('尚未到约定复核时间，可先保存临时观察')
  data={'maturity':maturity,'saved_at':st.now(),'note':str(body.get('note',''))[:5000], 'passed':False}
  for k in ('cohort_spend','cohort_net_gmv','net_orders','settled_spend'):
   value=checkfinite(body.get(k),k,0,10**14,allow_null=maturity!='matured');data[k]=None if value is None else int(value)
  if data.get('cohort_spend'):
   data['observed_roi']=data['cohort_net_gmv']/data['cohort_spend'] if data.get('cohort_net_gmv') is not None else None
  else:data['observed_roi']=None
  data['causal_increment']=None
  if maturity!='matured':
   c.execute('UPDATE proposals SET review=? WHERE id=?',(st.dumps(data),i));st.audit(c,ws['id'],'provisional_review',{'id':i,**data})
   return {'status':'executed','review':data}
  if not body.get('reservation_closed'):raise ValueError('确认该笔追加授权已结束；未花部分才可释放')
  if data['settled_spend']>p['reserved']:raise ValueError('预留内已消耗不可超过本笔授权。平台超额请先在其他已消耗中补记并保留异常说明')
  data['passed']=bool(body.get('passed')) and data['observed_roi'] is not None and data['observed_roi']>=ws['config']['roi_min'] and data['net_orders']>=ws['config']['min_orders']
  data['validation']='同批观察性结果，未识别因果增量'
  data['rollback_suggestion']=None if data['passed'] else p['payload']['rollback']
  c.execute("UPDATE proposals SET status='reviewed',review=?,settled_spend=?,reserved=0 WHERE id=?",(st.dumps(data),data['settled_spend'],i))
  task=st.get_task(ws['id'],p['path'],p['creative_id'],c)
  if data['passed']:
   task['last_verified_budget']=p['payload']['budget_new'];task['last_verified_bid']=p['payload']['bid_new']
  # Results are not silently overwritten with a different follow-up cohort; require fresh settings before next action.
  task['config_fresh']=False;task['task_result_verified']=False
  for k in ('id','revision','updated_at'):task.pop(k,None)
  c.execute('UPDATE tasks SET config=?,revision=revision+1,updated_at=? WHERE id=?',(st.dumps(task),st.now(),p['task_id']))
  st.audit(c,ws['id'],'review_completed',{'id':i,**data})
 return {'status':'reviewed','review':data}

@app.get('/api/exports/{run_id}')
def export(run_id:str,format:str='csv'):
 rr=st.get_run(run_id);p=rr['payload']
 if format=='json':return Response(st.dumps(p),media_type='application/json',headers={'Content-Disposition':'attachment; filename="ranking.json"'})
 out=io.StringIO();writer=csv.writer(out)
 writer.writerow(['路径','素材ID','素材名称','队列','模式','得分','30天净ROI','7天净ROI','7天净订单','7天消耗_元','效率变化','稳定性','原因','风险','7天曝光','曝光分层','层内排名','本次选中曝光层','排序目标','目标效率','曝光数每100元_平滑','净订单每100元_平滑','净ROI_目标平滑','目标自身权重','目标数据说明'])
 def safe(v):
  if v is None:return ''
  s=str(v)
  return "'"+s if (s.lstrip().startswith(('=','+','-','@','\t','\r')) or (s.isdigit() and len(s)>15)) else s
 for r in p['results']:
  m=r['metrics'];writer.writerow([safe(x) for x in (r['path'],r['creative_id'],r['creative_name'],r['queue_label'],r['mode_label'],r['score'],m['roi_30d'],m['roi_7d'],m['net_orders_7d'],(m['spend_7d']/100 if m['spend_7d'] is not None else None),m['roi_growth'],m['stability'],'；'.join(r['reasons']),'；'.join(r['flags']),m.get('impressions_7d'),r.get('exposure_label'),r.get('exposure_rank'),p.get('exposure_tier','all'),p.get('objective','legacy'),r.get('objective_value'),r.get('objective_metrics',{}).get('exposure',{}).get('value'),r.get('objective_metrics',{}).get('orders',{}).get('value'),r.get('objective_metrics',{}).get('roi',{}).get('value'),r.get('objective_metrics',{}).get(p.get('objective'),{}).get('own_weight'),r.get('objective_note'))])
 return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="ranking.csv"'})

@app.get('/api/workspaces/{w}/backup')
def backup(w:str):
 with st.connect() as c:
  data={'schema_version':1,'workspace':st.get_workspace(w,c),'exported_at':st.now()}
  for table in ('imports','runs','tasks','proposals','audit'):
   data[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE workspace_id=?',(w,))]
 return Response(st.dumps(data),media_type='application/json',headers={'Content-Disposition':'attachment; filename="workspace-backup.json"'})

@app.get('/api/workspaces/{w}/audit')
def getaudit(w:str):
 with st.connect() as c:return [{**dict(r),'payload':json.loads(r['payload'])} for r in c.execute('SELECT * FROM audit WHERE workspace_id=? ORDER BY created_at DESC LIMIT 300',(w,))]

@app.get('/api/examples')
def examples():
 manifest=st.ROOT/'examples'/'manifest.json'
 return json.loads(manifest.read_text()) if manifest.exists() else []

@app.post('/api/examples/load')
def loadexamples(body:dict):
 manifest=json.loads((st.ROOT/'examples'/'manifest.json').read_text())
 with st.connect() as c:
  ex=c.execute("SELECT * FROM workspaces WHERE kind='historical' AND name='合成30天／7天示例' LIMIT 1").fetchone()
 ws=st.row_workspace(ex) if ex else create_workspace('合成30天／7天示例','historical')
 for item in manifest:
  preview=store_preview(ws['id'],(st.ROOT/'examples'/item['file']).read_bytes(),item['original_name'])
  confirm(preview['id'],{'path':item['path'],'period_start':item['start'],'period_end':item['end'],'basis':'net_1h' if item['path']=='live' else 'reported_net','scope':'合成演示数据','complete':True,'scope_confirmed':True})
 return ws

@app.post('/api/demo')
def demo():
 from .demo import make_demo
 return make_demo(create_workspace,store_preview,confirm,save_task)

@app.get('/api/examples/template')
def template():
 text='素材ID,素材名称,整体消耗,净成交金额,净成交订单数,整体成交金额\nDEMO-001,请替换为真实素材,100,600,5,650\n'
 return Response('\ufeff'+text,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="template.csv"'})

# API routes have precedence; all front-end code is locally bundled, no CDN.
app.mount('/',StaticFiles(directory=st.ROOT/'static',html=True),name='frontend')

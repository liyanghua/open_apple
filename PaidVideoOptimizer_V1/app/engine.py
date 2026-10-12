"""Deterministic metrics and guarded trial policy. No auction/causal uplift model.
The accepted design defines scores, not probabilities; currency is integer fen.
"""
from __future__ import annotations
from .clock import business_today
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import math

POLICY_VERSION='1.3.0-objectives'
DEFAULT_CONFIG={
 'roi_min':5.0, 'smoothing_yuan':100.0, 'reference_roi':None,
 'min_orders':5, 'weights':{'30':0.30,'7':0.40,'trend':0.20,'stability':0.10},
 'freshness_days':2, 'threshold_confirmed':False,
 'threshold_note':'演示管理阈值；请按当前商品与净额口径确认',
 'budget_total':None,'external_spent':0,'external_committed':0,
 'profit_mode':'roi_screen','currency':'CNY','policy_version':POLICY_VERSION,
 'delivery_mode':'independent_boost', 'diagnosis_min_impressions':500,
 'diagnosis_min_spend_yuan':100.0, 'diagnosis_required_periods':2,
 'direction_rules':None,
}
QUEUES={'main':'放量复验候选','history':'历史参考','explore':'探索／新起量','observe':'观察／修复','data':'数据待核','inactive':'无近期消耗'}
MODES={'HISTORY_30D':'仅30天 · 历史参考','RECENT_PAIRED':'30天＋7天 · 冷启动','RECENT_NO_BASE':'新起量／缺可比前期','ROLLING_WEEKLY':'非重叠周 · 滚动模式'}
EXPOSURE_TIERS={'lt500':'不足500次','500_999':'500–999次','1000_1999':'1000–1999次',
 '2000_4999':'2000–4999次','gte5000':'5000次及以上','unknown':'曝光缺失／待核'}


def checkfinite(value,label,low=0,high=10**14,allow_null=False):
 if value is None and allow_null:return None
 if isinstance(value,bool):raise ValueError(f'{label}不能是布尔值')
 try:n=float(value)
 except (TypeError,ValueError):raise ValueError(f'{label}需要数值')
 if not math.isfinite(n) or n<low or n>high:raise ValueError(f'{label}超出有效范围')
 return n


def positive_integer(value,label,low,high):
 n=checkfinite(value,label,low,high)
 if not n.is_integer():raise ValueError(f'{label}需要整数')
 return int(n)


def validate_config(cfg):
 merged={**DEFAULT_CONFIG,**cfg}
 merged['roi_min']=checkfinite(merged['roi_min'],'ROI底线',0.0001,1000)
 merged['smoothing_yuan']=checkfinite(merged['smoothing_yuan'],'平滑强度',0,1000000)
 merged['min_orders']=int(checkfinite(merged['min_orders'],'最低净订单',1,100000))
 merged['freshness_days']=int(checkfinite(merged['freshness_days'],'新鲜度',0,30))
 merged['reference_roi']=checkfinite(merged.get('reference_roi'),'参考ROI',0,10000,True)
 for k in ('budget_total','external_spent','external_committed'):
  n=checkfinite(merged.get(k),k,0,10**14,allow_null=k=='budget_total');merged[k]=None if n is None else int(n)
 weights=merged.get('weights',{})
 if set(weights)!={'30','7','trend','stability'}:raise ValueError('权重需要30、7、trend、stability四项')
 merged['weights']={k:checkfinite(v,'权重',0,1) for k,v in weights.items()}
 if sum(merged['weights'].values())<=0 or merged['weights']['30']+merged['weights']['7']+merged['weights']['trend']<=0:raise ValueError('权重总和必须大于0')
 merged['threshold_confirmed']=bool(merged.get('threshold_confirmed',False))
 if merged.get('delivery_mode') not in ('independent_boost','chengfang'):raise ValueError('投放模式无效')
 merged['diagnosis_min_impressions']=positive_integer(merged['diagnosis_min_impressions'],'诊断最低曝光',1,10**14)
 merged['diagnosis_min_spend_yuan']=checkfinite(merged['diagnosis_min_spend_yuan'],'诊断最低消耗',0.0001,10**14)
 merged['diagnosis_required_periods']=positive_integer(merged['diagnosis_required_periods'],'诊断所需周期',2,1000)
 rules=merged.get('direction_rules')
 if rules is not None:
  if not isinstance(rules,dict):raise ValueError('方向规则需要对象')
  required={'primary_objective','min_creatives','expand_primary_ratio','expand_roi_ratio','expand_order_ratio','stop_primary_ratio','stop_roi_ratio','stop_order_ratio'}
  if set(rules)!=required:raise ValueError('方向规则不完整')
  if rules['primary_objective'] not in ('exposure','orders','roi'):raise ValueError('方向规则主目标无效')
  checked={'primary_objective':rules['primary_objective'],
   'min_creatives':positive_integer(rules['min_creatives'],'方向规则最少素材数',3,100000)}
  for key in required-{'primary_objective','min_creatives'}:
   checked[key]=checkfinite(rules[key],'方向规则比例',0.0000001,1)
  merged['direction_rules']=checked
 merged['profit_mode']='roi_screen'
 merged['policy_version']=POLICY_VERSION
 return merged


def exposure_bucket(impressions):
 if impressions is None or not isinstance(impressions,(int,float)) or not math.isfinite(impressions) or impressions<0:
  return 'unknown'
 for upper,key in ((500,'lt500'),(1000,'500_999'),(2000,'1000_1999'),(5000,'2000_4999')):
  if impressions<upper:return key
 return 'gte5000'


def div(a,b):
 return a/b if a is not None and b is not None and b>0 else None

def clip(v,lo=0,hi=1): return min(hi,max(lo,v))

def smooth(v,s,ref,s0):
 if v is None or s is None or s<=0 or ref is None: return None
 return (v+s0*ref)/(s+s0)

def growth(cur,prev):
 return cur/prev-1 if cur is not None and prev is not None and prev>0 else None

def score_roi(r,rmin): return 100*clip(r/(2*rmin)) if r is not None else None

def trend_score(cur,prev):
 if cur is None or prev is None or cur<=0 or prev<=0: return None
 return 50+50*clip(math.log(cur/prev)/math.log(2),-1,1)

def cohort_reference(imp):
 valid=[r for r in imp['data']['rows'] if not r['is_aggregate'] and not r['errors'] and (r.get('spend') or 0)>0]
 return div(sum(r['net_gmv'] for r in valid),sum(r['spend'] for r in valid)),len(valid)

def compatible(a,b):
 return all(a.get(k)==b.get(k) for k in ('workspace_id','path','basis','scope','complete'))

def fieldset(r,h):
 r=r or {}
 return {f'{k}_{h}':r.get(k) for k in ('spend','net_gmv','paid_gmv','net_orders','paid_orders','impressions','clicks')}

OBJECTIVES={'legacy':'历史综合评分','exposure':'最大化曝光','orders':'最大化成单','roi':'最大化ROI'}
OBJECTIVE_FIELDS={'exposure':('impressions_7d',10000), 'orders':('net_orders_7d',10000), 'roi':('net_gmv_7d',1)}

def objective_ranking(results, objective, s0):
 # References use paired valid observations for each outcome, never missing-as-zero.
 refs={}
 for key,(field,scale) in OBJECTIVE_FIELDS.items():
  valid=[r['metrics'] for r in results if not r['errors'] and
   (r['metrics'].get('spend_7d') or 0)>0 and r['metrics'].get(field) is not None and r['metrics'][field]>=0]
  refs[key]=div(sum(m[field] for m in valid),sum(m['spend_7d'] for m in valid))
 for r in results:
  m=r['metrics']; spend=m.get('spend_7d'); details={}
  for key,(field,scale) in OBJECTIVE_FIELDS.items():
   prior=refs[key]; output=m.get(field)
   valid=not r['errors'] and spend is not None and spend>0 and output is not None and output>=0
   value=(output+s0*prior)/(spend+s0) if valid and prior is not None else prior
   details[key]={'value':value*scale if value is not None else None,
    'reference':prior*scale if prior is not None else None,'imputed':not valid,
    'own_weight':spend/(spend+s0) if valid else 0}
  r['objective_metrics']=details
  if objective!='legacy':
   r['objective_value']=details[objective]['value']
   r['objective_note']=('无可用7天参考，目标效率不可计算' if r['objective_value'] is None else
    '缺失／异常／无有效消耗：仅参考分，待验证' if details[objective]['imputed'] else
    '实际零净订单，待验证' if m.get('net_orders_7d')==0 else '按7天单位预算效率排序')
 if objective!='legacy':
  results.sort(key=lambda r:(r['objective_value'] is None,-(r['objective_value'] or 0),
   -r['objective_metrics'][objective]['own_weight'],r['creative_id']))
 return {key:value*OBJECTIVE_FIELDS[key][1] if value is not None else None for key,value in refs.items()}


def calculate_ranking(i30, i7, config, weeks=None, as_of=None, requested_mode='auto', exposure_tier='all', objective='legacy'):
 """Snapshots are explicit; missing seven-day rows never become zero values."""
 if not i30 and not i7: raise ValueError('至少选择一份已确认导入。')
 if exposure_tier not in ('all',*EXPOSURE_TIERS):raise ValueError('未知的7天曝光分层')
 if objective not in OBJECTIVES:raise ValueError('未知排序目标')
 base=i30 or i7
 rmin=float(config['roi_min']); s0=round(float(config['smoothing_yuan'])*100)
 ref,count=cohort_reference(i30 or i7)
 if config.get('reference_roi') is not None: ref=float(config['reference_roi'])
 warnings=[]
 pair_ok=bool(i30 and i7 and compatible(i30,i7) and i30['period_end']==i7['period_end']
  and i30['window']==30 and i7['window']==7)
 if i30 and i7 and not pair_ok: warnings.append('30天／7天日期、范围或口径不一致；不计算前23天趋势。')
 if not base.get('complete'): warnings.append('这是部分导出：仅代表已导入子集，不称全计划TOP3。')
 if ref is None: warnings.append('没有可用参考ROI；缺失评分项按保守参考ROI 0计算，原始指标保持缺失。')
 maps=[]
 for imp in (i30,i7): maps.append({r['creative_id']:r for r in imp['data']['rows'] if not r['is_aggregate']} if imp else {})
 a,b=maps
 keys=sorted(set(a)|set(b)); results=[]
 ref_date=base['period_end']; today=as_of or business_today().isoformat()
 stale=(date.fromisoformat(today)-date.fromisoformat(ref_date)).days>int(config['freshness_days'])
 if stale: warnings.append(f'截至{ref_date}的数据超过新鲜度上限，仅用于历史／条件复验，不给今日可执行数值。')
 if date.fromisoformat(ref_date)>date.fromisoformat(today): warnings.append('统计截止日期晚于决策日期；只能在显式模拟中查看。')
 # Exactly dated, nonoverlapping seven-day periods; same basis and scope.
 weekly=[]
 if i7:
  week_pool={w['period_end']:w for w in (weeks or []) if w['window']==7 and compatible(w,i7)}
  week_pool[i7['period_end']]=i7
  for n in range(4):
   end=(date.fromisoformat(i7['period_end'])-timedelta(days=7*n)).isoformat()
   w=week_pool.get(end)
   if w is None: break
   weekly.append(w)
 for cid in keys:
  p=a.get(cid); r=b.get(cid)
  errors=list(dict.fromkeys((p or {}).get('errors',[])+(r or {}).get('errors',[])))
  flags=list(dict.fromkeys((p or {}).get('warnings',[])+(r or {}).get('warnings',[])))
  m={**fieldset(p,'30d'),**fieldset(r,'7d')}
  for h in ('30d','7d'):
   m['roi_'+h]=div(m['net_gmv_'+h],m['spend_'+h])
   m['paid_roi_'+h]=div(m['paid_gmv_'+h],m['spend_'+h])
   m['smooth_roi_'+h]=smooth(m['net_gmv_'+h],m['spend_'+h],ref,s0)
  m.update({'roi_23d':None,'smooth_roi_23d':None,'roi_growth':None,'gmv_growth':None,'spend_growth':None,
    'spend_23d':None,'net_gmv_23d':None,'stability':None,'week_growth':None,'week_count':0,'week_points':[]})
  m['net_discount_ratio']=None if m['paid_gmv_7d'] in (None,0) or m['net_gmv_7d'] is None else 1-m['net_gmv_7d']/m['paid_gmv_7d']
  m['net_cpa_7d']=div(m['spend_7d'],m['net_orders_7d'])
  m['net_aov_7d']=div(m['net_gmv_7d'],m['net_orders_7d'])
  m['ctr_7d']=div(m['clicks_7d'],m['impressions_7d'])
  m['paid_cvr_7d']=div(m['paid_orders_7d'],m['clicks_7d'])
  m['net_cvr_7d']=div(m['net_orders_7d'],m['clicks_7d'])
  m['roi_headroom']=None if m['smooth_roi_7d'] is None else m['smooth_roi_7d']/rmin-1
  previous_ok=False
  if pair_ok and p and r and not errors:
   if all(m[k] is not None for k in ('spend_30d','spend_7d','net_gmv_30d','net_gmv_7d')):
    s23=m['spend_30d']-m['spend_7d']; v23=m['net_gmv_30d']-m['net_gmv_7d']
    q30=m['net_orders_30d'];q7=m['net_orders_7d']
    if s23<0 or v23<0 or (q30 is not None and q7 is not None and q7>q30):
     errors.append('7天数值超过30天／前23天差额异常；需核窗口与归因修订')
    else:
     m['spend_23d']=s23; m['net_gmv_23d']=v23
     m['roi_23d']=div(v23,s23);m['smooth_roi_23d']=smooth(v23,s23,ref,s0)
     previous_ok=s23>0 and v23>0
     if previous_ok:
      m['roi_growth']=growth(m['roi_7d'],m['roi_23d'])
      m['gmv_growth']=growth(div(m['net_gmv_7d'],7),v23/23)
      m['spend_growth']=growth(div(m['spend_7d'],7),s23/23)
  if weekly and r and not errors:
   points=[]
   for w in weekly:
    row=next((rr for rr in w['data']['rows'] if rr.get('creative_id')==cid and not rr['is_aggregate']),None)
    if not row or row['errors'] or not (row.get('spend') or 0)>0: break
    points.append({'end':w['period_end'],'spend':row['spend'],'net_gmv':row['net_gmv'],
     'roi':div(row['net_gmv'],row['spend']),'smooth':smooth(row['net_gmv'],row['spend'],ref,s0),'snapshot_id':w['id']})
   m['week_points']=points;m['week_count']=len(points)
   if len(points)>=2: m['week_growth']=growth(points[0]['roi'],points[1]['roi'])
   if len(points)>=3:
    m['stability']=100*sum(w['spend'] for w in points if w['roi']>=rmin)/sum(w['spend'] for w in points)
  parts={'f30':score_roi(m['smooth_roi_30d'],rmin),'f7':score_roi(m['smooth_roi_7d'],rmin),'trend':None,'stability':m['stability']}
  mode='HISTORY_30D' if not i7 else 'RECENT_NO_BASE'
  score=None
  if not i7:
   score=parts['f30']
  elif previous_ok:
   mode='RECENT_PAIRED';parts['trend']=trend_score(m['smooth_roi_7d'],m['smooth_roi_23d'])
   ws=config['weights']; denom=ws['30']+ws['7']+ws['trend']
   if all(parts[k] is not None for k in ('f30','f7','trend')) and denom>0:
    score=(ws['30']*parts['f30']+ws['7']*parts['f7']+ws['trend']*parts['trend'])/denom
   if m['stability'] is not None and requested_mode=='rolling':
    points=m['week_points']; tt=trend_score(points[0]['smooth'],points[1]['smooth'])
    if tt is not None:
     parts['trend']=tt;mode='ROLLING_WEEKLY';denom=sum(ws.values())
     score=(ws['30']*parts['f30']+ws['7']*parts['f7']+ws['trend']*tt+ws['stability']*m['stability'])/denom
  else:
   score=parts['f7']
  reasons=[];queue='observe';eligible=False
  if errors:
   queue='data';score=None;reasons=errors.copy()
  elif not i7:
   queue='history' if (m['spend_30d'] or 0)>0 else 'inactive'
   reasons=['只有30天数据；历史评分不代表当前追投资格']
  elif r is None:
   queue='data';reasons=['近期表未匹配到该素材；未视为0消耗或失败']
  elif not (m['spend_7d'] or 0)>0:
   queue='inactive';reasons=['近期无消耗，ROI不可计算；不自动恢复投放']
  elif i30 and not pair_ok:
   queue='data';reasons=['两份报表的统计范围不一致']
  elif m['net_orders_7d'] is None:
   queue='data';reasons=['缺近期净订单，不能检查样本量']
  elif (m['roi_7d'] or 0)<rmin or (m['smooth_roi_7d'] or 0)<rmin:
   queue='observe';reasons=['近期原始或平滑ROI未过设定筛选线；不是自动暂停结论']
  elif m['net_orders_7d']<config['min_orders']:
   queue='explore';reasons=[f'近期仅{m["net_orders_7d"]}笔净订单；先限额探索']
  elif not previous_ok:
   queue='explore';reasons=['前23天无可比有效基线；新起量／不完整数据单列，不虚构趋势']
  elif requested_mode=='rolling' and mode!='ROLLING_WEEKLY':
   queue='explore';reasons=['缺至少3个连续可比非重叠周；不与完整滚动分混排']
  else:
   queue='main';eligible=True
   reasons=[f'7天净ROI {m["roi_7d"]:.2f}，平滑后 {m["smooth_roi_7d"]:.2f}，均过线{rmin:g}',f'近期{m["net_orders_7d"]}笔净订单，达到管理门槛（非统计保证）']
   if m['roi_growth'] is not None: reasons.append(f'相对前23天ROI变化{m["roi_growth"]:+.1%}')
  # Ranking is score-first. The queues above describe evidence/action readiness,
  # and never filter the leaderboard. Imputation is scoring-only.
  prior=ref if ref is not None else 0.0
  scoring={'reference_roi':prior,'imputed':[]}
  for h,row in (('30d',p),('7d',r)):
   value=m['smooth_roi_'+h]
   if value is None or (row and row.get('errors')):
    value=prior;scoring['imputed'].append(h+' ROI使用同路径参考值')
   scoring['roi_'+h]=value
  parts['f30']=score_roi(scoring['roi_30d'],rmin)
  parts['f7']=score_roi(scoring['roi_7d'],rmin)
  parts['trend']=trend_score(m['smooth_roi_7d'],m['smooth_roi_23d']) if previous_ok and not errors else None
  if requested_mode=='rolling' and mode=='ROLLING_WEEKLY' and not errors:
   parts['trend']=trend_score(m['week_points'][0]['smooth'],m['week_points'][1]['smooth'])
  if parts['trend'] is None:
   parts['trend']=50.0
   if i7:scoring['imputed'].append('趋势缺可比数据，按中性50分')
  if not i7:
   weights={'f30':1.0}
  else:
   ws=config['weights'];weights={'f30':ws['30'],'f7':ws['7'],'trend':ws['trend']}
   if requested_mode=='rolling':
    weights['stability']=ws['stability']
    if parts['stability'] is None or errors:
     parts['stability']=50.0;scoring['imputed'].append('稳定性缺可比周数据，按中性50分')
   total=sum(weights.values())
   weights={k:v/total for k,v in weights.items()} if total>0 else {'f7':1.0}
  scoring['weights']=weights
  score=sum(parts[k]*weight for k,weight in weights.items())
  if scoring['imputed']:flags.extend(scoring['imputed'])
  tier=exposure_bucket(m['impressions_7d'])
  exposure_note=('最近7天曝光不足500，ROI仅作低样本参考' if tier=='lt500' else
   '缺少有效7天曝光，无法判断曝光样本规模' if tier=='unknown' else
   '已按曝光量分层；仍需结合净订单、消耗与归因成熟度判断ROI可靠性')
  result={'creative_id':cid,'creative_name':(r or p)['creative_name'],'path':base['path'],'mode':mode,'mode_label':MODES[mode],
   'exposure_tier':tier,'exposure_label':EXPOSURE_TIERS[tier],'exposure_note':exposure_note,
   'queue':queue,'queue_label':QUEUES[queue],'score':score,'breakdown':parts,'metrics':m,'eligible':eligible,
   'reasons':reasons,'flags':flags,'errors':errors,'sku_count':max((p or {}).get('sku_count') or 0,(r or {}).get('sku_count') or 0) or None,
   'plan_count':max((p or {}).get('plan_count') or 0,(r or {}).get('plan_count') or 0) or None,
   'sources':[{'import_id':imp['id'],'filename':imp['filename'],'sheet':row['source_sheet'],'row':row['source_row']} for imp,row in ((i30,p),(i7,r)) if imp and row],
   'boost_reported':{k:(r or p).get(k) for k in ('boost_gmv','boost_net_gmv','boost_roi')},
   'scoring':scoring,'predicted_incremental_gmv':None,'success_probability':None}
  results.append(result)
 results.sort(key=lambda r:(-(r['score'] if r['score'] is not None else -1),-(r['metrics']['net_orders_7d'] or 0),-(r['metrics']['smooth_roi_7d'] or 0),r['creative_id']))
 objective_reference=objective_ranking(results,objective,s0)
 for n,r in enumerate(results,1): r['rank']=n
 groups=[]
 for key,label in EXPOSURE_TIERS.items():
  members=[r for r in results if r['exposure_tier']==key]
  for n,r in enumerate(members,1):r['exposure_rank']=n
  groups.append({'id':key,'label':label,'count':len(members),'top_ids':[r['creative_id'] for r in members[:3]]})
 main=results if exposure_tier=='all' else [r for r in results if r['exposure_tier']==exposure_tier]
 top=main[:3]
 return {'objective':objective,'objective_label':OBJECTIVES[objective],'objective_reference':objective_reference,'ranking_policy':'score_first','exposure_tier':exposure_tier,'exposure_groups':groups,
  'results':results,'top_ids':[r['creative_id'] for r in top],'ref_roi':ref,'ref_count':count,
  'mode':'HISTORY_30D' if not i7 else ('ROLLING_WEEKLY' if requested_mode=='rolling' else 'RECENT_PAIRED'),
  'as_of':today,'period_end':ref_date,'path':base['path'],'basis':base['basis'],'scope':base['scope'],
  'complete':base['complete'],'stale':stale,'warnings':warnings,
  'queue_counts':{q:sum(r['queue']==q for r in results) for q in QUEUES},
  'config':config,'snapshot_ids':[i['id'] for i in (i30,i7) if i], 'policy_version':POLICY_VERSION}


def floor_step(value,step):
 if step<=0: raise ValueError('步长必须大于0')
 return int((Decimal(str(value))/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR))*step

def recommendation(result,run,task,config,free_budget,*,is_replay=False,pending=False,success_count=0):
 """Return one single-axis trial. Input amounts integer fen; never invent current values."""
 out={'creative_id':result['creative_id'],'creative_name':result['creative_name'],'action_type':'HOLD','reason_codes':[],
  'reasons':[],'required_inputs':[],'budget_old':None,'budget_new':None,'bid_old':None,'bid_new':None,
  'reserve':0,'risk_exposure':None,'delta':0,'review_hours':None,'rollback':None,'simulated':is_replay,
  'predicted_incremental_gmv':None,'success_probability':None}
 if not config.get('threshold_confirmed'):out['required_inputs'].append('确认ROI规则与净额口径')
 if free_budget is None:out['required_inputs'].append('工作区预算池')
 if not task:out['required_inputs'].append('当前独立任务配置')
 def finish(code,reason,fields=None):
  out['action_type']=code;out['reasons'].append(reason)
  if fields: out['required_inputs']=list(dict.fromkeys(out['required_inputs']+fields))
  return out
 if run.get('stale') or run['mode']=='HISTORY_30D':
  return finish('HISTORY_ONLY','历史窗口或过旧数据只供回放；请补新鲜7天数据，不输出今日数值动作。')
 if not result['eligible']: return finish('HOLD','已参与评分排名；追投条件尚未满足：'+'；'.join(result['reasons']))
 if not config.get('threshold_confirmed'):
  return finish('WAIT_INPUT','请确认ROI筛选线及净额口径；当前只是演示阈值。',['ROI口径与筛选线'])
 if pending: return finish('WAIT_REVIEW','该素材已有已批准或已执行动作未复核；不连续叠加。')
 if not task: return finish('WAIT_INPUT','缺当前独立追投配置；不以历史CPA／7天消耗代填。',['任务ID','当前出价','任务预算','授权','任务自身结果'])
 out.update({'task_id':task['task_id'],'task_revision':task.get('revision'), 'budget_old':task.get('budget'),
  'budget_new':task.get('budget'),'bid_old':task.get('bid'),'bid_new':task.get('bid'), 'review_hours':task.get('review_hours'),
  'rollback':{'budget':task['last_verified_budget'] if task.get('last_verified_budget') is not None else task.get('budget'),'bid':task['last_verified_bid'] if task.get('last_verified_bid') is not None else task.get('bid')}})
 if not task.get('product_ok') or task.get('status') in ('blocked','stopped'):
  return finish('STOP_REVIEW','商品可售状态未确认或任务异常；建议人工核查，系统未暂停平台。')
 req=[k for k in ('task_id','bid','bid_cap','bid_step','budget','spent','addon_cap','risk_remaining','review_hours') if task.get(k) is None or task.get(k)=='']
 if req: return finish('WAIT_INPUT','当前设置或授权尚不完整。',req)
 if not task.get('scope_confirmed') or not task.get('context_confirmed'):
  return finish('WAIT_INPUT','请确认当前任务SKU、承接、历史范围与选中素材相符。',['scope_confirmed','context_confirmed'])
 if ((result.get('sku_count') or 0)>1 or (result.get('plan_count') or 0)>1) and not task.get('mixed_scope_confirmed'):
  return finish('WAIT_INPUT','历史包含多个SKU，请先确认当前任务范围及其经济门槛。',['mixed_scope_confirmed'])
 if task.get('pricing_mode','cost_bid')!='cost_bid':
  return finish('WAIT_INPUT','当前版本仅计算成本出价；目标ROI设置不能套用成本上调公式。',['成本出价模式'])
 if task.get('updated_at'):
  last=datetime.fromisoformat(task['updated_at'])
  if last.tzinfo is None:last=last.replace(tzinfo=timezone.utc)
  if (datetime.now(timezone.utc)-last).total_seconds()>86400:
   return finish('WAIT_INPUT','任务设置已超过24小时未核对，请重新确认当前配置。',['当前配置有效性'])
 if not task.get('config_fresh'): return finish('WAIT_INPUT','当前配置未确认仍然有效。',['当前配置有效性'])
 if task['bid_cap']<task['bid']: return finish('STOP_REVIEW','现价高于获批设置上限，先核查或回退，不生成加价。')
 remaining=max(0,task['budget']-task['spent'])
 out['risk_exposure']=remaining
 if task['spent']>task['budget']: return finish('STOP_REVIEW','任务已消耗超过配置预算，需先对账。')
 if remaining>task['risk_remaining']: return finish('STOP_REVIEW','既有未花额度已超过剩余毛广告风险授权；不继续放大。')
 if free_budget is None: return finish('WAIT_INPUT','未配置共享预算池。',['预算总额、其他消耗和在途授权'])
 # New task: fixed authorization, not a percentage or historical CPA substitute.
 if task['budget']==0:
  if task.get('fixed_test_budget') is None: return finish('WAIT_INPUT','新建任务没有预算基数，请批准固定测试额度。',['fixed_test_budget'])
  amount=min(task['fixed_test_budget'],task['addon_cap'],task['risk_remaining'],free_budget)
  if amount<=0: return finish('BUDGET_CONFLICT','无可用的新建测试额度。')
  out.update({'budget_new':amount,'reserve':amount,'risk_exposure':amount})
  return finish('NEW_BOOST_TEST','新建独立追投采用固定限额；历史排名仅作初筛，不继承收益。')
 if not task.get('task_result_verified') or task.get('maturity')!='matured':
  return finish('WAIT_REVIEW','独立任务自身结果未完成观察／验证；先回收结果，不直接放大。')
 if task.get('task_basis')!=run['basis']: return finish('WAIT_INPUT','任务净额口径与排名口径不同。',['task_basis'])
 if task.get('task_net_gmv') is None or task['spent']<=0:
  return finish('WAIT_INPUT','缺当前任务自己的消耗与净额，不能用素材整体收益替代。',['task_net_gmv','spent'])
 taskroi=task['task_net_gmv']/task['spent'];out['task_roi']=taskroi
 if taskroi<config['roi_min']: return finish('STOP_REVIEW','当前独立任务净ROI低于筛选线；先复核或回退，不增量。')
 h=max(0,result['metrics'].get('roi_headroom') or 0)
 evidence=0.10 if result['metrics'].get('stability') is not None and success_count>0 else 0.05
 delta_raw=min(evidence,0.25*h,0.10)
 delta=max(d for d in (0,0.05,0.10) if d<=delta_raw+1e-12)
 out.update({'delta':delta,'evidence_cap':evidence,'headroom':h,'budget_utilization':div(task['spent'],task['budget'])})
 if not delta: return finish('HOLD','历史余量尚不足以进入5%试探档；排名高也可保持。')
 diagnosis=task.get('diagnosis','unknown')
 if diagnosis not in ('budget','bid') or not task.get('diagnosis_note','').strip():
  return finish('HOLD','未确认是预算还是出价限制；预算未用完不等于出价过低。')
 if diagnosis=='budget':
  amount=min(int(Decimal(task['budget'])*Decimal(str(delta))),free_budget,task['addon_cap'],max(0,task['risk_remaining']-remaining))
  if amount<=0: return finish('BUDGET_CONFLICT','共享预算／本素材授权／风险余量不足。')
  out.update({'budget_new':task['budget']+amount,'reserve':amount,'risk_exposure':remaining+amount,'actual_change':amount/task['budget']})
  return finish('BUDGET_TEST','预算限制已人工确认：仅增加预算，成本出价保持；试探幅度不是最优解。')
 newbid=floor_step(min(Decimal(task['bid'])*(1+Decimal(str(delta))),Decimal(task['bid_cap'])),task['bid_step'])
 if newbid<=task['bid']: return finish('HOLD','按价格步长向下取整后没有合法上调空间。')
 out.update({'bid_new':newbid,'actual_change':newbid/task['bid']-1})
 return finish('BID_TEST','已给出成本出价限制依据：固定总预算试调出价；仍检查既有未花额度风险。')

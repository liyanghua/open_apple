"""Explicitly synthetic input and current tasks for exercising the whole UI."""
from .clock import business_today
from datetime import date, timedelta
import csv,io

def make_demo(create_workspace,store_preview,confirm,save_task):
 config={'roi_min':5,'reference_roi':3,'threshold_confirmed':True,'threshold_note':'教学模拟参数，不是业务阈值',
  'budget_total':100000,'external_spent':20000,'external_committed':41500}
 ws=create_workspace('教学模拟 · 排名与追投','demo',config)
 today=business_today();end=today-timedelta(days=1)
 values=[
 ('DEMO-A','教学A｜场景开头＋实拍证据',3000,18000,120,1000,7000,40),
 ('DEMO-B','教学B｜件数清晰＋价格解释',3500,22750,180,1200,10800,65),
 ('DEMO-C','教学C｜一单高ROI小样本',100,1200,2,10,200,1),
 ('DEMO-D','教学D｜近期效率下滑',2000,8000,90,700,1400,12),
 ('DEMO-E','教学E｜新起量待验证',300,2400,12,300,2400,12),
 ('DEMO-F','教学F｜零消耗记录',0,100,1,0,0,0),
 ]
 def csvbytes(rows):
  s=io.StringIO();w=csv.writer(s);w.writerow(['素材ID','素材名称','整体消耗','净成交金额','净成交订单数','整体成交金额','素材关联的商品数量'])
  for r in rows:w.writerow(r)
  return s.getvalue().encode('utf-8-sig')
 def put(days,ed,rows):
  start=ed-timedelta(days=days-1);name=f'教学推直播_{start}_{ed}_{days}天.csv'
  p=store_preview(ws['id'],csvbytes(rows),name)
  confirm(p['id'],{'path':'live','period_start':str(start),'period_end':str(ed),'basis':'reported_net','scope':'纯教学模拟','complete':True,'scope_confirmed':True,'basis_note':'教学模拟数据，无平台实绩'})
  return p['id']
 i30=put(30,end,[(i,n,s30,v30,q30,round(v30*1.1,2),1) for i,n,s30,v30,q30,s7,v7,q7 in values])
 i7=put(7,end,[(i,n,s7,v7,q7,round(v7*1.15,2),1) for i,n,s30,v30,q30,s7,v7,q7 in values])
 for offset in (7,14,21):
  rows=[]
  for i,n,s30,v30,q30,s7,v7,q7 in values:
   # The three earlier 7-day cohorts partition previous 23 days for this teaching file.
   rows.append((i,n,round((s30-s7)/3,2),round((v30-v7)/3,2),max(0,round((q30-q7)/3)),round((v30-v7)/3*1.1,2),1))
  put(7,end-timedelta(days=offset),rows)
 common={'pricing_mode':'cost_bid','optimization_event':'net_order','bid_step':1,'addon_cap':10000,'review_hours':24,
  'status':'active','scope_confirmed':True,'context_confirmed':True,'mixed_scope_confirmed':True,
  'config_fresh':True,'product_ok':True,'task_result_verified':True,'maturity':'matured','task_basis':'reported_net'}
 save_task(ws['id'],'live','DEMO-A',{**common,'task_id':'DEMO-TASK-A','bid':2400,'bid_cap':2600,'budget':30000,'spent':28500,
  'task_net_gmv':190000,'risk_remaining':5000,'diagnosis':'budget','diagnosis_note':'教学条件：当前任务自身ROI过线，且预算限制已经人工确认。'})
 save_task(ws['id'],'live','DEMO-B',{**common,'task_id':'DEMO-TASK-B','bid':2000,'bid_cap':2400,'budget':50000,'spent':10000,
  'task_net_gmv':90000,'risk_remaining':50000,'diagnosis':'bid','diagnosis_note':'教学条件：已有明确的成本出价限制依据，固定预算只改出价。'})
 return {'workspace':ws,'import_30':i30,'import_7':i7,'disclaimer':'所有数值与任务均为教学模拟，不是实际平台配置。'}

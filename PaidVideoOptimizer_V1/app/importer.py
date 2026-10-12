"""Read-only XLSX/CSV adapter. Uses Python stdlib ZIP/XML, never runs Excel formulas.
Amounts are stored in integer fen. IDs retain their source strings.
"""
from __future__ import annotations
import csv, hashlib, io, re, zipfile, posixpath
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET
from datetime import date

MAX_FILE = 20 * 1024 * 1024
MAX_XML = 100 * 1024 * 1024
MAX_ROWS = 50000
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
ALIASES = {
 'creative_id':['素材ID','素材id','视频ID','creative_id'],
 'creative_name':['素材名称','视频名称','creative_name'],
 'spend':['整体消耗','广告消耗','消耗','spend'],
 'net_gmv':['净成交金额','报表净成交金额','net_gmv','net_gmv_reported'],
 'paid_gmv':['整体成交金额','支付成交金额','paid_gmv','gmv_reported'],
 'net_orders':['净成交订单数','net_orders'],
 'paid_orders':['整体成交订单数','paid_orders'],
 'impressions':['整体展现次数','曝光量','展现次数','impressions'],
 'clicks':['整体点击次数','点击次数','clicks'],
 'sku_count':['素材关联的商品数量','sku_count'],
 'plan_count':['素材关联的计划数量','plan_count'],
 'reported_roi':['净成交ROI','reported_roi'],
 'creation_time':['素材创建时间','creation_time'],
 'boost_net_gmv':['追投调控净成交金额','boost_net_gmv'],
 'boost_gmv':['追投调控成交金额','boost_gmv'],
 'boost_roi':['追投调控净成交ROI','boost_roi_reported'],
 'source':['素材来源','source'],
 'plan_id':['计划ID','计划id','计划编号','plan_id'],
 'partition':['分区','投放分区','partition'],
 'marketing_cost':['营销消耗','营销费用','营销成本','marketing_cost'],
 'marketing_roi_reported':['营销ROI','营销roi','marketing_roi_reported'],
 'creator_commission':['达人佣金','创作者佣金','creator_commission'],
 'content_type':['内容类型','素材类型','content_type'],
 'is_aggregate':['是否汇总','汇总行','is_aggregate'],
}
MONEY = {'spend','net_gmv','paid_gmv','boost_gmv','boost_net_gmv','marketing_cost','creator_commission'}
COUNTS = {'net_orders','paid_orders','impressions','clicks','sku_count','plan_count'}

class ImportProblem(ValueError): pass

def decimal_value(value):
 if value is None or str(value).strip() in ('','-','--','—','–','N/A','null'):
  return None
 s = str(value).strip().replace(',','').replace('，','').replace('¥','').replace('￥','').replace('元','')
 try:
  d = Decimal(s)
  if not d.is_finite(): raise InvalidOperation
  return d
 except InvalidOperation:
  raise ImportProblem(f'无法解析数值：{str(value)[:70]}')

def cents(value):
 d=decimal_value(value)
 return None if d is None else int((d*100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def xml_read(z, name):
 data=z.read(name)
 if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
  raise ImportProblem('不接受包含DTD或外部实体的XML。')
 return ET.fromstring(data)

def col_index(ref):
 letters=re.match(r'[A-Z]+',ref.upper())
 if not letters: return 0
 n=0
 for c in letters.group(): n=n*26+ord(c)-64
 return n-1

def read_tables(data:bytes, filename:str):
 if len(data)>MAX_FILE: raise ImportProblem('文件超过20MB，请缩小导出范围。')
 if filename.lower().endswith('.csv'):
  text=None
  for enc in ('utf-8-sig','gb18030'):
   try: text=data.decode(enc); break
   except UnicodeDecodeError: pass
  if text is None: raise ImportProblem('CSV编码无法识别，请保存为UTF-8。')
  rows=[]
  for n,row in enumerate(csv.reader(io.StringIO(text)),1):
   if n>MAX_ROWS or len(row)>200: raise ImportProblem('超过50,000行或200列限制。')
   rows.append({'row':n,'cells':[{'v':v,'type':'s'} for v in row]})
  return [{'name':'CSV','rows':rows}]
 if not filename.lower().endswith('.xlsx'): raise ImportProblem('仅接受.xlsx或.csv；不执行宏，不支持加密文件。')
 try:
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   infos=z.infolist()
   if len(infos)>5000 or sum(x.file_size for x in infos)>MAX_XML:
    raise ImportProblem('压缩包解压尺寸过大。')
   if any('vbaProject' in x.filename for x in infos): raise ImportProblem('不接受含宏工作簿。')
   shared=[]
   if 'xl/sharedStrings.xml' in z.namelist():
    shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in xml_read(z,'xl/sharedStrings.xml')]
   wb=xml_read(z,'xl/workbook.xml')
   rels=xml_read(z,'xl/_rels/workbook.xml.rels')
   relmap={r.get('Id'):r.get('Target') for r in rels if r.get('TargetMode')!='External'}
   tables=[]
   for sh in wb.find(NS+'sheets'):
    target=relmap.get(sh.get(REL+'id'))
    if not target: continue
    target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
    if not target.startswith('xl/'): raise ImportProblem('非法工作表路径。')
    root=xml_read(z,target); sheetdata=root.find(NS+'sheetData'); rows=[]
    if sheetdata is None: continue
    for row in sheetdata:
     rn=int(row.get('r',len(rows)+1))
     if rn>MAX_ROWS: raise ImportProblem('超过50,000行限制。')
     cells=[]
     for cell in row:
      ci=col_index(cell.get('r','A1'))
      if ci>=200: raise ImportProblem('超过200列限制。')
      while len(cells)<=ci: cells.append({'v':None,'type':'n'})
      typ=cell.get('t','n'); v=cell.find(NS+'v'); value=v.text if v is not None else None
      if typ=='s': value=shared[int(value)] if value is not None else None
      elif typ=='inlineStr': value=''.join(t.text or '' for t in cell.iter(NS+'t'))
      cells[ci]={'v':value,'type':typ,'formula':cell.find(NS+'f') is not None}
     rows.append({'row':rn,'cells':cells})
    tables.append({'name':sh.get('name','Sheet1'),'rows':rows})
   return tables
 except (zipfile.BadZipFile,ET.ParseError,KeyError,ValueError,IndexError) as e:
  if isinstance(e,ImportProblem): raise
  raise ImportProblem('无法读取工作簿：文件损坏、加密或不是标准XLSX。') from e

def suggest_mapping(headers):
 clean={str(h).strip():h for h in headers}
 out={}
 for key,names in ALIASES.items():
  out[key]=next((clean[n] for n in names if n in clean),None)
 return out

def parse_file(data:bytes,filename:str,mapping=None,sheet_name=None,header_row=None):
 tables=read_tables(data,filename)
 if header_row and (int(header_row)<1 or int(header_row)>30): raise ImportProblem('表头行须位于前30行。')
 selected=None; hdr=None
 for table in tables:
  if sheet_name and table['name']!=sheet_name: continue
  for row in table['rows'][:30]:
   if header_row and row['row']!=header_row: continue
   vals=[str(c['v'] or '').strip() for c in row['cells']]
   found=suggest_mapping(vals)
   if header_row or found['creative_id']:
    selected=table; hdr=row; break
  if selected: break
 if selected is None:
  if sheet_name: selected=next((t for t in tables if t['name']==sheet_name),None)
  if selected is None and tables: selected=tables[0]
  if not selected or not selected['rows']: raise ImportProblem('工作表为空。')
  hdr=selected['rows'][0]
 headers=[str(c['v'] or '').strip() for c in hdr['cells']]
 mapping=mapping or suggest_mapping(headers)
 missing=[k for k in ('creative_id','spend','net_gmv') if not mapping.get(k)]
 header_index={h:i for i,h in enumerate(headers) if h}
 if any(v not in header_index for v in mapping.values() if v): raise ImportProblem('字段映射引用了不存在的表头。')
 rows=[]; issues=[]; seen={}; duplicates=set()
 for raw in selected['rows']:
  if raw['row']<=hdr['row']: continue
  if not any(c['v'] not in (None,'') for c in raw['cells']): continue
  rec={'source_row':raw['row'],'source_sheet':selected['name'],'errors':[],'warnings':[],'raw':{},'id_precision':'text'}
  for key,col in mapping.items():
   ci=header_index.get(col) if col else None
   cell=raw['cells'][ci] if ci is not None and ci<len(raw['cells']) else {'v':None,'type':'n'}
   v=cell.get('v'); rec['raw'][key]=v
   try:
    if key in MONEY: rec[key]=cents(v)
    elif key in COUNTS:
     num=decimal_value(v)
     if num is not None and num!=num.to_integral_value(): raise ImportProblem('计数不是整数')
     rec[key]=None if num is None else int(num)
    elif key in ('reported_roi','boost_roi','marketing_roi_reported'):
     num=decimal_value(v); rec[key]=None if num is None else float(num)
    else: rec[key]=None if v is None else str(v).strip()
   except ImportProblem as e:
    rec[key]=None; rec['errors'].append(f'{col}: {e}')
   if cell.get('formula'): rec['warnings'].append(f'{col}使用公式缓存，未执行公式')
   if key=='creative_id' and v is not None and cell.get('type')=='n':
    rec['id_precision']='numeric'
    if len(str(v).replace('.',''))>15:
     rec['errors'].append('长素材ID为数值单元格，精度待核；请改为文本重新导出')
  cid=rec.get('creative_id')
  explicit_aggregate=rec.get('is_aggregate')
  if explicit_aggregate is not None:
   explicit_aggregate=str(explicit_aggregate).strip().lower() in ('1','true','yes','y','是','汇总')
  rec['is_aggregate']=bool(explicit_aggregate) or not cid or cid in ('-','--','—','－','-2','合计','总计','全部')
  rec['creative_name']=rec.get('creative_name') or cid or '集合／无ID记录'
  for k in MONEY|COUNTS:
   if rec.get(k) is not None and rec[k]<0: rec['errors'].append(f'{k}为负数，隔离待核')
  for k in ('spend','net_gmv'):
   if rec.get(k) is None: rec['errors'].append(f'缺少{k}')
  if rec.get('paid_gmv') is not None and rec.get('net_gmv') is not None and rec['net_gmv']>rec['paid_gmv']+1:
   rec['errors'].append('净成交金额大于整体成交金额，需核口径')
  if (rec.get('sku_count') or 0)>1: rec['warnings'].append('多SKU历史，独立追投需确认商品范围')
  if (rec.get('plan_count') or 0)>1: rec['warnings'].append('历史关联多个计划，非当前任务专属效果')
  if rec.get('reported_roi') is not None and (rec.get('spend') or 0)>0 and rec.get('net_gmv') is not None:
   if abs(rec['net_gmv']/rec['spend']-rec['reported_roi'])>0.025: rec['warnings'].append('重算ROI与源值不同，请核对显示精度')
  if not rec['is_aggregate']:
   if cid in seen: duplicates.add(cid)
   seen[cid]=True
  rows.append(rec)
 for r in rows:
  if r.get('creative_id') in duplicates: r['errors'].append('同窗口ID重复；未自动相加，需确认明细维度')
  if r['errors']: issues.append({'row':r['source_row'],'id':r.get('creative_id'),'messages':r['errors']})
 totals={k:(sum(r.get(k) or 0 for r in rows) if any(r.get(k) is not None for r in rows) else None) for k in ('spend','net_gmv','paid_gmv','net_orders','impressions','clicks')}
 totals.update({'rows':len(rows),'active':sum((r.get('spend') or 0)>0 for r in rows),
   'active_single':sum((r.get('spend') or 0)>0 and not r['is_aggregate'] for r in rows),
   'aggregates':sum(r['is_aggregate'] for r in rows),'invalid_rows':len(issues)})
 dates=re.findall(r'20\d{2}-\d{2}-\d{2}',filename)
 start,end=(dates[0],dates[1]) if len(dates)>=2 else (None,None)
 window=None
 if start and end:
  try: window=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
  except ValueError: pass
 path='live' if '推直播' in filename or '追投调控净成交金额' in headers else ('product' if '推商品' in filename or '素材关联的商品数量' in headers else None)
 return {'filename':filename,'sha256':hashlib.sha256(data).hexdigest(),'sheet':selected['name'],'header_row':hdr['row'],
  'sheets':[t['name'] for t in tables],'headers':headers,'mapping':mapping,'missing_fields':missing,'rows':rows,
  'issues':issues,'totals':totals,'suggested':{'path':path,'period_start':start,'period_end':end,'window':window}}

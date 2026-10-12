from __future__ import annotations
import json, os, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from .engine import DEFAULT_CONFIG

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('OPTIMIZER_DATA_DIR',str(ROOT/'data'))).resolve()
DATA.mkdir(parents=True,exist_ok=True)
(DATA/'raw').mkdir(exist_ok=True)
DB=DATA/'optimizer.sqlite3'

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid(): return uuid.uuid4().hex
def dumps(v): return json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(',',':'))
class ClosingConnection(sqlite3.Connection):
 def __exit__(self,typ,value,tb):
  try:return super().__exit__(typ,value,tb)
  finally:self.close()

def connect():
 c=sqlite3.connect(DB,timeout=15,isolation_level=None,factory=ClosingConnection)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=15000')
 return c

@contextmanager
def transaction():
 c=connect()
 try:
  c.execute('BEGIN IMMEDIATE');yield c;c.commit()
 except Exception:
  c.rollback();raise
 finally: c.close()

def init():
 with connect() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,config TEXT NOT NULL,created_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
  CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),filename TEXT NOT NULL,sha256 TEXT NOT NULL,status TEXT NOT NULL,path TEXT,period_start TEXT,period_end TEXT,window INTEGER,basis TEXT,scope TEXT,complete INTEGER,imported_at TEXT NOT NULL,known_at TEXT,metadata TEXT NOT NULL,data TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_imports_lookup ON imports(workspace_id,path,period_end,window,status);
  CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,creative_id TEXT NOT NULL,config TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,UNIQUE(workspace_id,path,creative_id));
  CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),run_id TEXT NOT NULL REFERENCES runs(id),task_id TEXT,creative_id TEXT NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,config_revision INTEGER NOT NULL,task_revision INTEGER,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',reserved INTEGER NOT NULL DEFAULT 0,settled_spend INTEGER NOT NULL DEFAULT 0,execution TEXT,review TEXT,approved_at TEXT);
  CREATE INDEX IF NOT EXISTS idx_proposals_active ON proposals(workspace_id,creative_id,path,status);
  CREATE TABLE IF NOT EXISTS plan_contexts(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,plan_id TEXT NOT NULL,config TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,UNIQUE(workspace_id,path,plan_id));
  CREATE TABLE IF NOT EXISTS material_profiles(workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,plan_id TEXT NOT NULL,creative_id TEXT NOT NULL,labels TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,PRIMARY KEY(workspace_id,path,plan_id,creative_id));
  CREATE TABLE IF NOT EXISTS plan_operations(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,plan_id TEXT NOT NULL,occurred_at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS diagnosis_runs(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),path TEXT NOT NULL,plan_id TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_diagnosis_runs_lookup ON diagnosis_runs(workspace_id,path,plan_id,created_at DESC);
  CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,workspace_id TEXT,created_at TEXT NOT NULL,event TEXT NOT NULL,payload TEXT NOT NULL);
  ''')

def audit(c,w,event,payload): c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(uid(),w,now(),event,dumps(payload)))

def row_workspace(row):
 d=dict(row);d['config']={**DEFAULT_CONFIG,**json.loads(d['config'])};return d

def get_workspace(w,c=None):
 own=c is None;c=c or connect()
 try:
  row=c.execute('SELECT * FROM workspaces WHERE id=?',(w,)).fetchone()
  if not row: raise ValueError('工作区不存在')
  return row_workspace(row)
 finally:
  if own:c.close()

def import_record(row,with_data=True):
 d=dict(row);d['complete']=bool(d['complete']);d['metadata']=json.loads(d['metadata']);d['data']=json.loads(d['data']) if with_data else None
 return d

def get_import(i,c=None):
 own=c is None;c=c or connect()
 try:
  r=c.execute('SELECT * FROM imports WHERE id=?',(i,)).fetchone()
  if not r: raise ValueError('导入不存在')
  return import_record(r)
 finally:
  if own:c.close()

def get_run(i,c=None):
 own=c is None;c=c or connect()
 try:
  r=c.execute('SELECT * FROM runs WHERE id=?',(i,)).fetchone()
  if not r: raise ValueError('排名不存在')
  d=dict(r);d['payload']=json.loads(d['payload']);return d
 finally:
  if own:c.close()

def ledger(w,c=None):
 own=c is None;c=c or connect()
 try:
  ws=get_workspace(w,c);cfg=ws['config']
  res=c.execute("SELECT COALESCE(SUM(reserved),0) FROM proposals WHERE workspace_id=? AND status IN ('approved','executed')",(w,)).fetchone()[0]
  settled=c.execute("SELECT COALESCE(SUM(settled_spend),0) FROM proposals WHERE workspace_id=? AND status='reviewed'",(w,)).fetchone()[0]
  total=cfg.get('budget_total');used=cfg.get('external_spent') or 0;external=cfg.get('external_committed') or 0
  available=None if total is None else total-used-external-res-settled
  return {'total':total,'external_spent':used,'external_committed':external,'reserved':res,'settled':settled,
    'free':None if available is None else max(0,available),'deficit':max(0,-available) if available is not None else 0}
 finally:
  if own:c.close()

def get_task(w,path,cid,c=None):
 own=c is None;c=c or connect()
 try:
  row=c.execute('SELECT * FROM tasks WHERE workspace_id=? AND path=? AND creative_id=?',(w,path,cid)).fetchone()
  if not row:return None
  d=json.loads(row['config']);d.update({'id':row['id'],'revision':row['revision'],'updated_at':row['updated_at']});return d
 finally:
  if own:c.close()


def validate_plan_path(path):
 if path not in ('live','product'):raise ValueError('投放路径无效')


def validate_plan_id(plan_id):
 if not isinstance(plan_id,str) or not plan_id.strip():raise ValueError('计划ID无效')
 return plan_id


def plan_context_record(row):
 d=dict(row);d['config']=json.loads(d['config']);return d


def get_plan_context(w,path,plan_id,c=None):
 validate_plan_path(path);validate_plan_id(plan_id)
 own=c is None;c=c or connect()
 try:
  row=c.execute('SELECT * FROM plan_contexts WHERE workspace_id=? AND path=? AND plan_id=?',(w,path,plan_id)).fetchone()
  return plan_context_record(row) if row else None
 finally:
  if own:c.close()


def list_plan_contexts(w,path=None):
 if path is not None:validate_plan_path(path)
 with connect() as c:
  if path is None:rows=c.execute('SELECT * FROM plan_contexts WHERE workspace_id=? ORDER BY path,plan_id',(w,))
  else:rows=c.execute('SELECT * FROM plan_contexts WHERE workspace_id=? AND path=? ORDER BY plan_id',(w,path))
  return [plan_context_record(row) for row in rows]


def save_plan_context(w,path,plan_id,config):
 validate_plan_path(path);validate_plan_id(plan_id);encoded=dumps(config);updated_at=now()
 with transaction() as c:
  old=get_plan_context(w,path,plan_id,c)
  if old:
   c.execute('UPDATE plan_contexts SET config=?,revision=revision+1,updated_at=? WHERE id=?',(encoded,updated_at,old['id']))
  else:
   c.execute('INSERT INTO plan_contexts(id,workspace_id,path,plan_id,config,updated_at) VALUES(?,?,?,?,?,?)',(uid(),w,path,plan_id,encoded,updated_at))
  audit(c,w,'plan_context_saved',{'path':path,'plan_id':plan_id})
 return get_plan_context(w,path,plan_id)


def material_profile_record(row):
 d=dict(row);d['labels']=json.loads(d['labels']);return d


def get_material_profile(w,path,plan_id,creative_id,c=None):
 validate_plan_path(path);validate_plan_id(plan_id)
 own=c is None;c=c or connect()
 try:
  row=c.execute('SELECT * FROM material_profiles WHERE workspace_id=? AND path=? AND plan_id=? AND creative_id=?',(w,path,plan_id,creative_id)).fetchone()
  return material_profile_record(row) if row else None
 finally:
  if own:c.close()


def list_material_profiles(w,path,plan_id):
 validate_plan_path(path);validate_plan_id(plan_id)
 with connect() as c:
  return [material_profile_record(row) for row in c.execute('SELECT * FROM material_profiles WHERE workspace_id=? AND path=? AND plan_id=? ORDER BY creative_id',(w,path,plan_id))]


def save_material_profile(w,path,plan_id,creative_id,labels):
 validate_plan_path(path);validate_plan_id(plan_id)
 if not isinstance(creative_id,str) or not creative_id.strip():raise ValueError('素材ID无效')
 encoded=dumps(labels);updated_at=now()
 with transaction() as c:
  old=get_material_profile(w,path,plan_id,creative_id,c)
  if old:
   c.execute('UPDATE material_profiles SET labels=?,revision=revision+1,updated_at=? WHERE workspace_id=? AND path=? AND plan_id=? AND creative_id=?',(encoded,updated_at,w,path,plan_id,creative_id))
  else:
   c.execute('INSERT INTO material_profiles(workspace_id,path,plan_id,creative_id,labels,updated_at) VALUES(?,?,?,?,?,?)',(w,path,plan_id,creative_id,encoded,updated_at))
  audit(c,w,'material_profile_saved',{'path':path,'plan_id':plan_id,'creative_id':creative_id})
 return get_material_profile(w,path,plan_id,creative_id)


def operation_record(row):
 d=dict(row);d['payload']=json.loads(d['payload']);return d


def append_plan_operation(w,path,plan_id,occurred_at,kind,payload):
 validate_plan_path(path);validate_plan_id(plan_id)
 if not isinstance(kind,str) or not kind.strip():raise ValueError('操作类型无效')
 record_id=uid();created_at=now()
 with transaction() as c:
  c.execute('INSERT INTO plan_operations(id,workspace_id,path,plan_id,occurred_at,kind,payload,created_at) VALUES(?,?,?,?,?,?,?,?)',(record_id,w,path,plan_id,occurred_at,kind,dumps(payload),created_at))
  audit(c,w,'plan_operation_recorded',{'id':record_id,'path':path,'plan_id':plan_id,'kind':kind})
 with connect() as c:
  return operation_record(c.execute('SELECT * FROM plan_operations WHERE id=?',(record_id,)).fetchone())


def list_plan_operations(w,path,plan_id):
 validate_plan_path(path);validate_plan_id(plan_id)
 with connect() as c:
  return [operation_record(row) for row in c.execute('SELECT * FROM plan_operations WHERE workspace_id=? AND path=? AND plan_id=? ORDER BY occurred_at,created_at,rowid',(w,path,plan_id))]


def diagnosis_run_record(row):
 d=dict(row);d['payload']=json.loads(d['payload']);return d


def create_diagnosis_run(w,path,plan_id,payload):
 validate_plan_path(path);validate_plan_id(plan_id)
 record_id=uid();created_at=now()
 with transaction() as c:
  c.execute('INSERT INTO diagnosis_runs(id,workspace_id,path,plan_id,created_at,payload) VALUES(?,?,?,?,?,?)',(record_id,w,path,plan_id,created_at,dumps(payload)))
  audit(c,w,'diagnosis_run_created',{'id':record_id,'path':path,'plan_id':plan_id})
 return get_diagnosis_run(record_id)


def get_diagnosis_run(i,c=None):
 own=c is None;c=c or connect()
 try:
  row=c.execute('SELECT * FROM diagnosis_runs WHERE id=?',(i,)).fetchone()
  if not row:raise ValueError('诊断不存在')
  return diagnosis_run_record(row)
 finally:
  if own:c.close()


def list_diagnosis_runs(w,path=None,plan_id=None):
 if path is not None:validate_plan_path(path)
 if plan_id is not None:validate_plan_id(plan_id)
 clauses=['workspace_id=?'];values=[w]
 if path is not None:clauses.append('path=?');values.append(path)
 if plan_id is not None:clauses.append('plan_id=?');values.append(plan_id)
 with connect() as c:
  rows=c.execute('SELECT * FROM diagnosis_runs WHERE '+ ' AND '.join(clauses) +' ORDER BY created_at DESC,rowid DESC',values)
  return [diagnosis_run_record(row) for row in rows]

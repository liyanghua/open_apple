"""换序/改写变体引导：fork-first → run plan → proposal 种子 → rebuild → 批准 → 资产同步 → assets 门。"""
import sys, json
sys.path.insert(0, '.')
from pathlib import Path
from lib.artifact_hashing import attach_hashes
from lib.artifact_io import write_artifact_atomic
from lib.checkpoint import write_checkpoint
from lib.template_fork import fork_template_run
from lib.template_run_plan import create_template_run
from lib.template_source_match import match_run_plan
from lib.template_assets import sync_assets_artifacts
from backlot.project_commit import ProjectCommitStore
from schemas.artifacts import validate_artifact

ROOT = Path('.')
TID, RUN, SRC_RUN = sys.argv[1], sys.argv[2], sys.argv[3]
DD = ROOT / 'projects' / RUN
SRC = ROOT / 'projects' / SRC_RUN
PACK_DIR = ROOT / 'projects/template-pack-library'
pack = json.load(open(PACK_DIR / 'artifacts/template_pack.json'))
t = next(x for x in pack['templates'] if x['template_id'] == TID)

if not (DD / 'checkpoint_research.json').exists():
    fork_template_run(RUN, source_project_dir=ROOT / 'projects/table-mat-mix-v8', pipeline_dir=ROOT / 'projects',
                      product_facts_path=SRC / 'artifacts/product_facts.json')
    print('research seeded')

if not (DD / 'artifacts/template_run_plan.json').exists():
    facts = json.load(open(SRC / 'artifacts/product_facts.json'))
    rp = create_template_run(t, template_pack_ref={'artifact_sha256': attach_hashes(dict(pack))['artifact_sha256'], 'version': '1.0'},
                             product_facts_ref={'artifact_sha256': facts.get('artifact_sha256') or '0'*64},
                             adaptation_policy=str(t.get('archetype') or 'proof-first'))
    match_run_plan(t.get('slots') or [], rp)
    sealed = attach_hashes(dict(rp)); validate_artifact('template_run_plan', sealed)
    with ProjectCommitStore(DD).transaction(action={'action_id': 'seed-rp'}) as sink:
        write_artifact_atomic('artifacts/template_run_plan.json', 'template_run_plan', sealed, project_dir=DD, sink=sink)
        amap = {}
        for name in ('proposal_packet.json', 'creative_control_plan.json', 'hook_plan.json', 'decision_log.json'):
            data = attach_hashes(dict(json.load(open(SRC / 'artifacts' / name))))
            write_artifact_atomic(f'artifacts/{name}', name.split('.')[0], data, project_dir=DD, sink=sink)
            amap[name.split('.')[0]] = {'name': name.split('.')[0], 'path': f'artifacts/{name}',
                                        'semantic_sha256': data['semantic_sha256'], 'artifact_sha256': data['artifact_sha256'], 'data': data}
        write_checkpoint(ROOT / 'projects', RUN, 'proposal', 'completed', amap, pipeline_type='cinematic-fast',
                         next_action=None, review={'findings': [], 'verdict': 'pass'}, sink=sink)
        write_artifact_atomic('artifacts/product_facts.json', 'product_facts', attach_hashes(dict(facts)), project_dir=DD, sink=sink)
    print('run plan + proposal seeded')

from lib.template_mainline import rebuild_aligned_run
rebuild_aligned_run(RUN)
print('rebuild done')

with ProjectCommitStore(DD).transaction(action={'action_id': 'sync'}) as sink:
    rp = json.load(open(DD / 'artifacts/template_run_plan.json'))
    if rp.get('status') != 'approved':
        rp['status'] = 'approved'; rp.pop('artifact_sha256', None); rp.pop('semantic_sha256', None)
        env = write_artifact_atomic('artifacts/template_run_plan.json', 'template_run_plan', attach_hashes(dict(rp)), project_dir=DD, sink=sink)
        rplan_sha = env['artifact_sha256']
    else:
        rplan_sha = rp.get('artifact_sha256') or '0' * 64
    sync_assets_artifacts(DD, t, pipeline_dir=ROOT / 'projects', sink=sink)
with ProjectCommitStore(DD).transaction(action={'action_id': 'gate'}) as sink:
    amap2 = {}
    for name in ('asset_plan.json', 'production_lock.json', 'approval_bundle.json'):
        key = name.split('.')[0]
        data = dict(json.load(open(SRC / 'artifacts' / name)))
        data['project_id'] = RUN; data['input_hashes'] = {'base_run_plan_sha': rplan_sha}
        data.pop('artifact_sha256', None); data.pop('semantic_sha256', None)
        data = attach_hashes(data)
        write_artifact_atomic(f'artifacts/{name}', key, data, project_dir=DD, sink=sink)
        amap2[key] = {'name': key, 'path': f'artifacts/{name}', 'semantic_sha256': data['semantic_sha256'],
                      'artifact_sha256': data['artifact_sha256'], 'data': data}
    sep = json.load(open(DD / 'artifacts/shot_execution_plan.json'))
    amap2['shot_execution_plan'] = {'name': 'shot_execution_plan', 'path': 'artifacts/shot_execution_plan.json',
                                    'semantic_sha256': sep.get('semantic_sha256'), 'artifact_sha256': sep.get('artifact_sha256'), 'data': sep}
    write_checkpoint(ROOT / 'projects', RUN, 'assets', 'awaiting_human', amap2, pipeline_type='cinematic-fast',
                     next_action={'summary': f'{TID} 资产就绪', 'verb': 'await_user', 'context_refs': ['artifacts/asset_manifest.json']},
                     review={'findings': [], 'verdict': 'pass'}, sink=sink)
print('assets gate ready')

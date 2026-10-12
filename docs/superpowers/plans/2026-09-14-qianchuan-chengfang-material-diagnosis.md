# V1.5 升级实施计划：计划加预算与素材复验

**日期：** 2026-09-16
**状态：** 待用户审核；本次仅更新文档，未实施本章功能
**业务规范：** PaidVideoOptimizer_V1/docs/乘方协同素材诊断设计.md 的 V1.5 章节
**验收规范：** PaidVideoOptimizer_V1/docs/本地DEMO与真实数据验收.md 的 V1.5 章节

## 1. 目标与范围

服务毛巾、浴巾、沙发垫等品类的单计划多素材赛马。主线为每日计划数据、每周素材数据，输出计划预算试探、素材复验和内容生产建议。零历史新品先给用户额度内的限额试投方案。

保留独立追投历史功能，但不再向乘方用户索取单素材独立任务预算、出价。系统仍只记录本地建议及人工执行结果，不调用后台调价接口。

已有代码提供解析、排名、曝光层、独立任务建议及乘方诊断基础；不等于计划级追加闭环已经可用。执行前需复核实际运行服务、数据目录、前端源文件和构建产物一致性。

## 2. 分阶段实施与交付门槛

### P0 数据口径、计划关联与历史兼容

- [ ] 引入品类、计划档案、路径、计划预算版本、每日效果和整体汇总记录；平台 ID 与本地编号分开。
- [ ] 分开存储投放阶段与覆盖范围；文件名、截图“整体”字样不能代替范围确认。
- [ ] 导入支持历史文件复用及截图人工录入；展示识别字段、未知字段、周期、来源和导出时间。
- [ ] 计划下拉列表使用已保存计划及报表明确字段，不从文件名尾部猜 ID；本地编号后续可关联真实 ID。
- [ ] 同范围执行对账，视频子集展示覆盖率和差额；AIGC 独立留存，不进入普通素材榜。
- [ ] 用户单计划确认与原始关联计划数量共存；后续逐行 ID 冲突必须可见。
- [ ] 修正历史复用金额单位：前端元值与服务端 cents 转换只能发生一次；测试输入 100 元保存 10,000 分。
- [ ] 不根据佣金缺失自动设置“仅基础投放”；不把综合成本缺失伪装成零。
- [ ] 备份和迁移验证后保留旧导入、排名、任务、快照和审计；历史元数据缺失标为待核，不追溯伪造。
- [ ] 交付门槛：真实商品汇总与视频子集能并列查看，差额不导致无理由的全流程阻断。

### P1 素材诊断与复验

- [ ] 按能力逐项判断数据可用性：一期可分析、缺曝光可做订单／ROI、部分周期只作探索。
- [ ] 同品类同计划同路径参考值固定；三目标平滑按设计公式实现并显示单位、自身权重、原始值和参考值。
- [ ] 曝光层内按目标真正排序取前三，全量仍可查；缺失／零分母不生成伪值。
- [ ] 同分按自身权重及素材 ID 稳定排序；切换筛选不改变参考基准。
- [ ] 素材名称、ID、来源行及中文理由可查看；无数据显示缺失清单而非空页面。
- [ ] 两期方向结论逐期校验样本和相对基准；至少三个不同素材及完整方向规则，经营变化时降级观察。
- [ ] 保留／观察／复验与停止复制／扩产分开；内容标签和产能不完整时不给编造的原因和制作配额。
- [ ] 交付门槛：商品 730 条、直播 389 条普通素材可分析；AIGC 不占名次，商品曝光未知不阻断其他有效指标。

### P2 计划预算试验闭环

- [ ] 实现计划级净 ROI、订单成本、预算使用率及可比七天变化；按日预算生效记录计算使用率。
- [ ] 按设计实现数据待补、保持观察、优先排查、预算试探、停止继续追加／复核五类状态。
- [ ] 初版数值动作仅支持日预算；总预算保留方向建议。后台目标 ROI 与本地净 ROI 底线分别显示。
- [ ] 条件、试验公式、完整预算日起始、期限、金额步长、额度上限严格按设计；默认参数未确认不得视作经营授权。
- [ ] 新增计划级建议与预留，不能复用旧单素材任务模型掩盖对象差异；共享额度只记一次。
- [ ] 确认、取消、执行和复核幂等；并发确认不得超额；已有未复核试验时不连续追加。
- [ ] 冻结原预算、规则、输入及复核条件；人工执行后才进入观察。到期提示不等于自动回退。
- [ ] 结算明确新增授权使用依据，避免从总消耗推断增量；未关闭额度时不得自动释放。
- [ ] 交付门槛：可复现一轮本地草案→预留→人工执行登记→观察→复核→结算，并验证过期和额度不足场景。

### P3 新品向导、模板与真实验收

- [ ] 提供 A 零历史试投、B 单期诊断、C 周复验、D 数值建议四档向导，逐项列出所缺资料及下一步。
- [ ] 输出计划档案、每日计划记录、每周素材明细模板，说明必填阶段、金额单位及净额口径。
- [ ] 零历史试投只安排用户授权限额，不按素材均分预算；缺底线不宣称盈利或建议追加。
- [ ] 毛巾、浴巾、沙发垫参考数据隔离；旧桌垫素材只复用模板和待验证内容假设。
- [ ] 打通上传、范围确认、计划关联、诊断、复验和回放页面；重新构建并确认运行服务实际加载版本。
- [ ] 交付门槛：完成验收指南全部场景，附实际测试结果、页面证据及已知限制后交用户审核。

## 3. 最小接口和存储变更

维持 Python/FastAPI/SQLite 与现有 TypeScript 前端。新增计划档案、预算版本、每日计划实绩、整体汇总及来源、计划建议、计划执行／复核和授权记录；素材快照补充品类、覆盖范围、单计划确认、数据时点。

接口按“计划档案读取／保存、导入预览／确认、计划诊断生成、预算建议确认／取消、执行登记、复核结算、快照回放”划分。继续使用字符串 ID、整数分；幂等操作带请求标识并由数据库事务保护。重复确认返回原结果；状态冲突返回明确原因，不重复预留。

计划诊断与素材诊断均返回：输入版本、规则版本、证据周期、口径、建议状态、理由、缺失项、可执行标记及复核条件。读取接口不得创建新建议或变更预留。

计划关联更新不重写旧快照；新记录保存新关联版本。新增 schema 使用可重复的迁移过程，迁移前复制完整数据目录；恢复说明需验证。旧 API 与旧结果继续兼容，新增界面不能将旧独立任务审批按钮带入乘方素材卡。

## 4. 验证、发布与文档回写

- 单元：公式、缺失、零值、元分换算、固定参考、跨品类隔离、逐期阈值、预算日及额度上限。
- API：历史导入复用、计划关联、来源留存、冻结回放、幂等、并发预留、状态冲突和迁移。
- 页面：两种模式切换、缺资料提示、历史加载、商品缺曝光、真实 TOP3、计划试验闭环、刷新恢复。
- 真实样本：以设计的截图汇总及两份 08-30～09-05 明细验收，不为通过对账改写源值。
- 新品：零历史毛巾启动、一周未成熟、两周方向复验、条件完整追加和条件失败保持观察。
- 发布：先验证备份与测试数据，再在本地服务部署；核对健康响应、静态版本和实际用户工作区。不得把工作树里通过构建等同于运行服务已更新。
- 全部验收后才将具体项标为已实现，更新测试报告的实际日期、测试数和证据；旧测试记录不能证明 V1.5 已通过。

以下 2026-09-14 的计划保留作 V1.4 历史档案。其严格整体对账、两期／曝光入场条件和乘方不产生任何预留的规则，不作为本轮计划级新增能力的限制。本轮允许计划级授权，仍禁止赛马素材级预算分配。

---

# V1.4 历史实施计划


> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Chengfang plan-collaboration workflow that produces material and content-direction decisions without creating per-material budget or bid proposals.

**Architecture:** Preserve the existing independent-boost workflow as a legacy workspace mode. Add a Chengfang workspace configuration, persisted plan context, manual material profiles, operation log, and deterministic diagnostic engine. Use ranking snapshots for raw material metrics, but create a distinct diagnosis snapshot that freezes the Chengfang data partition, context, labels, thresholds, reference efficiencies, and recommendations.

**Tech Stack:** Python 3/FastAPI/SQLite, deterministic calculation in `PaidVideoOptimizer_V1/app`, vanilla TypeScript, existing `unittest` test suite.

---

## File map

| File | Change |
|---|---|
| `PaidVideoOptimizer_V1/app/storage.py` | Add plan context, material profile, operation log and diagnosis snapshot storage helpers. |
| `PaidVideoOptimizer_V1/app/importer.py` | Add aliases and validation metadata for Chengfang partition, plan identifier and marketing-cost columns. |
| `PaidVideoOptimizer_V1/app/engine.py` | Keep legacy ranking intact; add a pure Chengfang diagnosis function and reason codes. |
| `PaidVideoOptimizer_V1/app/main.py` | Add mode/context/profile/operation/diagnosis APIs; prevent proposal creation for Chengfang runs. |
| `PaidVideoOptimizer_V1/frontend/src/main.ts` | Add Chengfang mode UI, context form, label editor, diagnosis and content-decision views; retain legacy views for independent workspaces. |
| `PaidVideoOptimizer_V1/static/index.html` | Bump only the local app bundle cache version after successful frontend build. |
| `PaidVideoOptimizer_V1/tests/test_chengfang.py` | New unit and API tests for the mode, partition rules and diagnosis outcomes. |
| `PaidVideoOptimizer_V1/tests/ui_smoke.py` | Extend the browser flow for Chengfang context, labels, diagnosis, export and replay. |
| `PaidVideoOptimizer_V1/docs/乘方协同素材诊断设计.md` | Update the design only when implementation decisions deviate from the approved design. |
| `PaidVideoOptimizer_V1/docs/本地DEMO与真实数据验收.md` | Add Chengfang-specific source-data and acceptance checklist. |
| `PaidVideoOptimizer_V1/docs/测试报告.md` | Record backend, browser, replay and local-only evidence for the Chengfang release. |

## Non-negotiable compatibility rules

- Never mutate existing runs, proposals, tasks or imports; legacy workspaces remain usable.
- Use `delivery_mode` values `independent_boost` and `chengfang`. Existing workspaces migrate in memory to `independent_boost` until users opt in.
- A Chengfang workspace may rank materials, but `/api/proposals` returns a non-actionable diagnostic response; it never writes proposal reservations.
- Do not calculate ROI across `chengfang` and `all_domain` partitions. `overall` may show counts and money totals but has no ROI result.
- Never infer creator commission, marketing capability flags or content labels from a filename.

## Chunk 1: Persist mode and Chengfang context

### Task 1: Define the failing configuration and storage tests

**Files:**
- Create: `PaidVideoOptimizer_V1/tests/test_chengfang.py`
- Modify: `PaidVideoOptimizer_V1/tests/test_system.py`

- [ ] **Step 1: Write `unittest.TestCase` tests for configuration defaults and validation.**

```python
class ChengfangConfigTests(unittest.TestCase):
    def test_legacy_workspace_defaults_to_independent_boost(self):
        workspace = create_workspace('legacy')
        self.assertEqual(workspace['config']['delivery_mode'], 'independent_boost')

    def test_legacy_stored_config_merges_default_without_rewrite(self):
        # Insert a workspace config that predates delivery_mode, then load it.
        self.assertEqual(storage.get_workspace(self.legacy_id)['config']['delivery_mode'], 'independent_boost')

    def test_invalid_mode_and_thresholds_are_rejected(self):
        for bad in ('unknown', '', None):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, '投放模式'):
                    validate_config({'delivery_mode': bad})
```

Cover integer/range boundaries for `diagnosis_min_impressions`, `diagnosis_min_spend_yuan`, reject `diagnosis_required_periods=1`, and assert that an incomplete `direction_rules`, fractional `min_creatives`, or out-of-range ratio raises a validation error.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang`
Expected: FAIL because `delivery_mode` is absent.

- [ ] **Step 3: Add `delivery_mode` and diagnosis thresholds to `DEFAULT_CONFIG` and `validate_config`.**

Use these validated config fields:

```python
'delivery_mode': 'independent_boost',
'diagnosis_min_impressions': 500,
'diagnosis_min_spend_yuan': 100.0,
'diagnosis_required_periods': 2,  # integer, minimum 2
'direction_rules': None,
```

Validate `delivery_mode` as an enum; validate `diagnosis_min_impressions` as a positive bounded integer, `diagnosis_min_spend_yuan` as a positive finite money value, and `diagnosis_required_periods` as an integer no lower than `2`. `direction_rules` remains `None` until the user confirms the business rule. When present it must contain: `primary_objective` (`exposure`/`orders`/`roi`), `min_creatives` (integer >= 3), `expand_primary_ratio`, `expand_roi_ratio`, `expand_order_ratio`, `stop_primary_ratio`, `stop_roi_ratio`, and `stop_order_ratio` (all positive finite ratios). The engine must not emit `STOP_PRODUCTION` or `EXPAND_DIRECTION` while the object is unset or incomplete. Merge the new defaults in `storage.row_workspace` on read; do not persist or rewrite old config JSON merely by opening a legacy workspace.

- [ ] **Step 4: Add schema and helpers in `app/storage.py`.**

Add tables with explicit uniqueness and JSON payloads:

```sql
CREATE TABLE IF NOT EXISTS plan_contexts(
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  path TEXT NOT NULL, plan_id TEXT NOT NULL, config TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
  UNIQUE(workspace_id, path, plan_id)
);
CREATE TABLE IF NOT EXISTS material_profiles(
  workspace_id TEXT NOT NULL REFERENCES workspaces(id), path TEXT NOT NULL,
  plan_id TEXT NOT NULL, creative_id TEXT NOT NULL, labels TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL, PRIMARY KEY(workspace_id, path, plan_id, creative_id)
);
CREATE TABLE IF NOT EXISTS plan_operations(
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  path TEXT NOT NULL, plan_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnosis_runs(
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  path TEXT NOT NULL, plan_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_runs_lookup ON diagnosis_runs(workspace_id, path, plan_id, created_at DESC);
```

Every helper validates `path in ('live', 'product')`. Context and profile saves upsert and increment their revision only when invoked, profiles are always scoped to a plan ID, lists filter by workspace/path/plan and sort deterministically, operations append by `occurred_at, created_at`, and diagnosis retrieval addresses its persisted `id`. Add tests for each save's revision increment, two plan-specific versions of the same creative ID, each list's filter/order, diagnosis retrieval, and exactly one `audit` event per write.

- [ ] **Step 5: Run focused tests and the existing suite.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang tests.test_system`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add PaidVideoOptimizer_V1/app/storage.py PaidVideoOptimizer_V1/app/main.py PaidVideoOptimizer_V1/app/engine.py PaidVideoOptimizer_V1/tests/test_chengfang.py PaidVideoOptimizer_V1/tests/test_system.py
git commit -m "feat: add chengfang workspace context"
```

## Chunk 2: Import contract and partition safety

### Task 2: Add Chengfang input metadata without breaking legacy imports

**Files:**
- Modify: `PaidVideoOptimizer_V1/app/importer.py`
- Modify: `PaidVideoOptimizer_V1/app/main.py`
- Test: `PaidVideoOptimizer_V1/tests/test_chengfang.py`

- [ ] **Step 1: Write failing import tests.**

```python
def test_chengfang_context_requires_partition_plan_and_explicit_capabilities(self):
    response = client.put(f'/api/workspaces/{workspace}/chengfang/context', json={
        'plan_id': 'p-1', 'partition': 'overall', 'marketing_capabilities': {}
    })
    self.assertEqual(response.status_code, 400)

def test_confirm_binds_source_plan_partition_period_and_cost_basis(self):
    response = self.confirm_import(plan_id='p-1', partition='chengfang',
        timezone='Asia/Shanghai', base_delivery_only=False,
        cost_grain='material_attributable', plan_marketing_cost=10000)
    self.assertEqual(response.status_code, 400)  # no marketing-cost column
```

- [ ] **Step 2: Verify the tests fail.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang`
Expected: FAIL because the endpoints and validation do not exist.

- [ ] **Step 3: Extend import aliases and confirmation metadata.**

Add optional aliases for `plan_id`, `partition`, `marketing_cost`, `marketing_roi_reported`, `creator_commission`, and `content_type`. Do not change the existing canonical `spend` field. `content_type` remains raw source metadata only: never auto-write it into a material profile or content-direction label. Reuse the importer’s explicit `is_aggregate` flag: aggregate rows do not need source plan-ID equality and cannot enter material costs, references, diagnoses or direction groups. Add a test with a `'-'` aggregate ID proving it stays in totals but never in diagnosis results. At confirmation time, accept `partition` only as `chengfang`, `all_domain`, or `overall`, and persist it in immutable confirmation metadata.

The confirmation payload persists `plan_id`, `path`, `partition`, `period_start`, `period_end`, `timezone`, `cost_basis`, `cost_grain`, `plan_marketing_cost`, reconciliation result, and `base_delivery_only`. If a source `plan_id` column exists, every non-aggregate row must match the declared plan ID; if the column is absent, record `plan_id_source='manual_confirmed'`. `cost_grain` must be `material_attributable` for material ROI diagnosis; reject `plan_total_repeated` and `unknown`. Set `material_cost_sum` to the sum of non-aggregate, non-duplicate, valid material costs. Set `reconciliation_tolerance_fen = max(100, round(plan_marketing_cost * 0.01))`; mark `cost_reconciled` only when `abs(plan_marketing_cost - material_cost_sum) <= reconciliation_tolerance_fen`, and persist the signed `unattributed_cost_fen`. A failed reconciliation keeps raw rows visible but blocks ROI and content-direction conclusions. For Chengfang diagnostics, `marketing_cost` is required unless the saved plan context declares `base_delivery_only=True`; then `spend` may be used as the whole cost and the snapshot must state that limitation. A reported ROI never replaces a missing numerator or denominator.

- [ ] **Step 4: Implement APIs.**

Add:

```text
PUT /api/workspaces/{workspace_id}/chengfang/context
GET /api/workspaces/{workspace_id}/chengfang/contexts
POST /api/imports/{import_id}/confirm  # accept partition and plan_id metadata
```

The context body must include `plan_id`, `path`, `status`, `started_at`, `marketing_roi_target`, `marketing_capabilities`, and `basis_note`; it may include `base_delivery_only`. Validate `path` as `live`/`product` and status as `active`/`paused`/`stopped`. `marketing_capabilities` must explicitly supply booleans for `base_delivery`, `star_select`, `creator_marketing`, and `creator_commission_bid`. Reject missing keys or values of another type rather than assuming commission is absent. Add tests for invalid partition, source-plan mismatch, base-delivery cost fallback, repeated/unknown cost grain, failed cost reconciliation, and rejected empty/incomplete capability declarations.

Keep the `overall` partition confirmable for scale-only reporting, but explicitly reject it from `POST /api/chengfang/diagnosis-runs`; add that failing API test in Chunk 4, together with the mixed-partition diagnostic test.

- [ ] **Step 5: Run tests.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang tests.test_system`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add PaidVideoOptimizer_V1/app/importer.py PaidVideoOptimizer_V1/app/main.py PaidVideoOptimizer_V1/tests/test_chengfang.py
git commit -m "feat: validate chengfang import partitions"
```

## Chunk 3: Deterministic material and direction diagnosis

### Task 3: Build and test a pure diagnosis engine

**Files:**
- Create: `PaidVideoOptimizer_V1/app/chengfang.py`
- Modify: `PaidVideoOptimizer_V1/app/engine.py`
- Test: `PaidVideoOptimizer_V1/tests/test_chengfang.py`

- [ ] **Step 1: Write pure-function tests before implementation.**

```python
def test_low_exposure_is_observe_even_when_smoothed_roi_is_high(self):
    result = diagnose(snapshot(rows=[row(impressions=499, spend=10000, net_gmv=90000)]), context, profiles, config)
    self.assertEqual(result['materials'][0]['decision'], 'OBSERVE')

def test_missing_labels_exclude_direction_but_not_material_diagnosis(self):
    result = diagnose(snapshot(rows=[row(labels=None)]), context, {}, config)
    assert result['materials'][0]['decision'] in {'OBSERVE', 'RETAIN_RACE'}
    assert result['directions'] == []

def test_mixed_partitions_raise_instead_of_calculating_roi(self):
    with self.assertRaisesRegex(ValueError, '数据分区'):
        diagnose(mixed_snapshot, context, profiles, config)
```

Also write tests that: return `NEEDS_DATA` for missing exposure, missing required cost, unmatched range or unreconciled cost and exclude those rows from direction groups; reject missing marketing cost when no base-delivery limitation exists; reject non-attributable or unreconciled cost from ROI diagnosis; exclude different plans, paths and partitions from a reference group; classify an otherwise valid row below `diagnosis_min_spend_yuan` or with one effective period as `OBSERVE` or `TEST_VARIANT`; and prohibit `STOP_PRODUCTION`/`EXPAND_DIRECTION` until complete `direction_rules` and two non-overlapping comparable periods exist. For expansion, require the configured primary-efficiency minimum plus both ROI and order guardrails relative to the plan reference; for stopping, require the configured low-primary signal plus the configured ROI and order failure guardrails. Include one direction test that verifies its structured brief changes exactly one label, names a comparison direction and gives a production count.

- [ ] **Step 2: Verify the tests fail.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang`
Expected: FAIL because `app.chengfang.diagnose` does not exist.

- [ ] **Step 3: Implement `diagnose` as a pure function.**

Input: selected confirmed 7-day import, optional earlier non-overlapping comparable import, saved plan context, material profiles, config, and operation log.

Output contract:

```python
{
  'partition': 'chengfang',
  'basis': 'marketing_cost',
  'material_reference': {'exposure': ..., 'orders': ..., 'roi': ...},
  'materials': [{'creative_id': ..., 'labels': {...}, 'sample_state': ..., 'raw_metrics': {...},
                 'objective_metrics': {'exposure': ..., 'orders': ..., 'roi': ...},
                 'previous_period_change': {...}, 'decision': ..., 'reason_codes': [...],
                 'next_review_condition': ...}],
  'directions': [{'labels': {...}, 'creative_count': ..., 'period_count': ...,
                  'objective_metrics': {'exposure': ..., 'orders': ..., 'roi': ...},
                  'plan_reference': {...}, 'relative_efficiency': {...},
                  'decision': ..., 'reason_codes': [...], 'operation_warnings': [...], 'brief': ...}],
  'frozen_inputs': {'import_ids': [...], 'context_revision': ..., 'profile_revisions': {...},
                    'operations': [{...immutable serialized operation-log entry...}],
                    'config': {...}, 'cost_basis': ...},
  'warnings': [...],
}
```

Reuse the current `smooth` function and exposure tiers, but compute the reference only from rows with the same plan, partition, basis, positive cost and valid outcome. Return `OBSERVE`, `RETAIN_RACE`, or `TEST_VARIANT` without confirmed group thresholds. Emit `STOP_PRODUCTION` and `EXPAND_DIRECTION` only after confirmed group thresholds and required comparable periods are met.

`brief` is deterministic structured text: “retain labels”, “change exactly one label”, “produce count” and “comparison direction”; no model-generated creative claims.

- [ ] **Step 4: Add operation-change warnings.**

First write a failing test for this behavior: if an ROI target, budget, capability, product or landing context operation overlaps the observation period, the affected direction must become `OBSERVE` with `CONTEXT_CHANGED`; it cannot be `STOP_PRODUCTION` or `EXPAND_DIRECTION`. Keep the material observation result visible, but add the same warning to the material reason codes.

- [ ] **Step 5: Run diagnosis and regression tests.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang tests.test_objectives tests.test_exposure_tiers tests.test_score_first`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add PaidVideoOptimizer_V1/app/chengfang.py PaidVideoOptimizer_V1/app/engine.py PaidVideoOptimizer_V1/tests/test_chengfang.py
git commit -m "feat: add chengfang material diagnosis engine"
```

## Chunk 4: API snapshots, labels and operation logs

### Task 4: Expose only local diagnostic decisions

**Files:**
- Modify: `PaidVideoOptimizer_V1/app/main.py`
- Modify: `PaidVideoOptimizer_V1/app/storage.py`
- Test: `PaidVideoOptimizer_V1/tests/test_chengfang.py`

- [ ] **Step 1: Write failing API tests.**

```python
def test_chengfang_diagnosis_freezes_every_input(client, workspace, import_7, prior_import):
    client.put(f'/api/workspaces/{workspace}/chengfang/plans/p-1/materials/c1',
               json={'labels': {'content_type': '口播'}})
    run = client.post('/api/chengfang/diagnosis-runs', json={
        'workspace_id': workspace, 'plan_id': 'p-1', 'path': 'live',
        'import_7': import_7, 'prior_import_7': prior_import
    }).json()
    client.put(f'/api/workspaces/{workspace}/chengfang/plans/p-1/materials/c1',
               json={'labels': {'content_type': '混剪'}})
    client.put(f'/api/workspaces/{workspace}/config', json={...changed_thresholds...})
    client.post(f'/api/workspaces/{workspace}/chengfang/operations', json={...})
    saved = client.get('/api/chengfang/diagnosis-runs/' + run['id']).json()
    assert saved['materials'][0]['labels']['content_type'] == '口播'
    assert saved['frozen_inputs']['import_ids'] == [import_7, prior_import]
    assert saved['frozen_inputs']['context_revision'] == 1
    assert saved['frozen_inputs']['config']['diagnosis_min_impressions'] == 500
    assert saved['frozen_inputs']['operations'] == []

def test_chengfang_cannot_create_independent_proposal(client, chengfang_workspace, run):
    response = client.post('/api/proposals', json={'workspace_id': chengfang_workspace, 'run_id': run, 'creative_id': 'c1'})
    assert response.status_code == 409

def test_overall_partition_is_rejected_for_roi_diagnosis(client, workspace, overall_import):
    response = client.post('/api/chengfang/diagnosis-runs', json={
        'workspace_id': workspace, 'import_7': overall_import, 'plan_id': 'p-1'
    })
    assert response.status_code == 400

def test_mixed_chengfang_and_all_domain_imports_are_rejected(client, workspace, import_7, all_domain_import):
    response = client.post('/api/chengfang/diagnosis-runs', json={
        'workspace_id': workspace, 'plan_id': 'p-1', 'path': 'live',
        'import_7': import_7, 'prior_import_7': all_domain_import
    })
    assert response.status_code == 400

def test_chengfang_proposal_gate_has_no_side_effect(client, chengfang_workspace, run):
    before = client.get(f'/api/workspaces/{chengfang_workspace}/ledger').json()
    response = client.post('/api/proposals', json={'workspace_id': chengfang_workspace, 'run_id': run, 'creative_id': 'c1'})
    after = client.get(f'/api/workspaces/{chengfang_workspace}/ledger').json()
    assert response.status_code == 409
    assert after == before
```

- [ ] **Step 2: Verify tests fail.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest tests.test_chengfang`
Expected: FAIL because the endpoints do not exist and proposal creation is not mode-aware.

- [ ] **Step 3: Add APIs.**

```text
PUT /api/workspaces/{workspace_id}/chengfang/plans/{plan_id}/materials/{creative_id}
GET /api/workspaces/{workspace_id}/chengfang/materials
POST /api/workspaces/{workspace_id}/chengfang/operations
GET /api/workspaces/{workspace_id}/chengfang/operations
POST /api/chengfang/diagnosis-runs
GET /api/chengfang/diagnosis-runs/{run_id}
GET /api/workspaces/{workspace_id}/chengfang/diagnosis-runs
GET /api/chengfang/diagnosis-runs/{run_id}/export
```

`POST /api/chengfang/diagnosis-runs` requires `workspace_id`, `plan_id`, `path`, current confirmed `import_7`, and optional confirmed `prior_import_7`; load the plan context by the same workspace/path/plan. Every import must match on plan, path, partition, cost basis, cost grain, base-delivery limitation and metric scope. When `prior_import_7` is supplied, require both imports to be valid seven-day windows with **different, non-overlapping** time ranges; reject the same window, overlap, or a window of another length. `GET` returns only the stored frozen payload, including serialized operation-log entries (ID, occurred time, kind, note, payload and revision/value) that were in force when the run was created; never rehydrate them from current operation rows.

Validate label keys against a small fixed set: `content_type`, `hook`, `value_proposition`, `person`, `scene`, `price_expression`, `duration_band`. Values are nonempty strings of at most 80 characters. Operations require `path`, `plan_id`, ISO `occurred_at`, a fixed `kind` (`roi_target_changed`, `budget_changed`, `capability_changed`, `product_changed`, `landing_changed`, `material_batch_added`), and a nonempty explanatory note; payload fields are validated by kind and never invoke a platform action.

- [ ] **Step 4: Gate legacy proposal endpoints.**

Before `recommendation()` or proposal persistence, verify the workspace is `independent_boost`. Return HTTP 409 with `乘方模式只生成素材诊断，不生成单素材预算或出价提案` for Chengfang workspaces. Do not alter existing proposal rows.

- [ ] **Step 5: Run all backend tests.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add PaidVideoOptimizer_V1/app/main.py PaidVideoOptimizer_V1/app/storage.py PaidVideoOptimizer_V1/tests/test_chengfang.py
git commit -m "feat: snapshot chengfang content decisions"
```

## Chunk 5: Local UI and exports

### Task 5: Replace per-material action UI only in Chengfang mode

**Files:**
- Modify: `PaidVideoOptimizer_V1/frontend/src/main.ts`
- Modify: `PaidVideoOptimizer_V1/static/index.html`
- Modify: `PaidVideoOptimizer_V1/app/main.py`
- Test: `PaidVideoOptimizer_V1/tests/ui_smoke.py`

- [ ] **Step 1: Add browser assertions before UI implementation.**

```python
seed_confirmed_chengfang_imports_and_reconciled_cost(page)
save_plan_context(page, plan_id='p-1', path='直播', capabilities=ALL_EXPLICIT_FLAGS)
label_materials(page, plan_id='p-1', labels={'content_type': '口播', 'hook': '痛点', 'value_proposition': '价格锚点'})
page.get_by_label('投放模式').select_option('chengfang')
page.get_by_role('button', name='生成素材诊断').click()
expect(page.get_by_role('heading', name='内容决策')).to_be_visible()
expect(page.get_by_role('button', name='生成追投建议')).not_to_be_visible()
expect(page.get_by_role('button', name='批准并预留')).not_to_be_visible()
```

- [ ] **Step 2: Verify the browser test fails.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python tests/ui_smoke.py`
Expected: FAIL because no Chengfang controls or view exists.

- [ ] **Step 3: Implement conditional navigation and forms.**

In Chengfang mode:

- rename the dashboard action to “生成素材诊断”;
- replace “追投与复核” with “诊断回收与复盘”;
- replace the task form with plan context, capability flags and operation log;
- add material-label editing in the material detail modal;
- add “内容决策” grouped by `保留赛马／继续观察／补测变体／停止生产／扩产方向`;
- render the diagnostic overview as the three goal views (`最大化曝光／最大化成单／最大化 ROI`) crossed with the existing exposure tiers, with its selected goal and tier visible in the result;
- show warnings about partition, cost basis, context changes and sample state.

When multiple plan contexts exist, render an explicit plan-context selector filtered by the selected path. Store its selected `plan_id` in UI state; disable diagnosis and label editing until it is selected. Label endpoints always receive this plan ID. Treat `content_type`、`hook`、`value_proposition` as the minimum label set for a material to enter a content-direction conclusion; allow the other fixed labels as optional enrichment. Render clear empty/error states for absent context, wrong partition, unreconciled cost and missing labels.

Each material and direction decision card must display the frozen diagnostic period, partition, plan ID, marketing capabilities and cost basis; labels and group creative count; seven-day raw impressions, whole cost, net orders, net GMV and composite-marketing ROI; smoothed target efficiency, data weight, plan reference and exposure tier; prior non-overlapping-period change; operation/operating-change warning; decision, reason codes, evidence state and next review condition. For `TEST_VARIANT` or `EXPAND_DIRECTION`, it must also state what to retain, the single variable to change, production count and comparison direction. The UI must show these from the frozen result, never recomputed live values.

Keep the current dashboard, task form, approvals and action records unchanged for `independent_boost`.

- [ ] **Step 4: Add exports.**

Implement `GET /api/chengfang/diagnosis-runs/{run_id}/export` from the frozen diagnosis payload, not live profiles or config. Include plan ID, path, partition, import IDs, labels, sample state, raw metrics, all three goal efficiencies, plan references, relative efficiencies, decision, reason codes, operation warnings, next review condition and structured brief. Apply the existing CSV injection protection helper.

- [ ] **Step 5: Build and test.**

Run: `remotion-composer/node_modules/.bin/tsc -p PaidVideoOptimizer_V1/frontend/tsconfig.json`
Expected: exit 0.

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python tests/ui_smoke.py`
Expected: PASS for both legacy and Chengfang flows. The Chengfang smoke flow must list a saved diagnosis, load it after mutating live labels/context/config, assert frozen content persists, and export its CSV; it must also show a blocked state for invalid context before the valid setup.

- [ ] **Step 6: Commit.**

```bash
git add PaidVideoOptimizer_V1/frontend/src/main.ts PaidVideoOptimizer_V1/static/index.html PaidVideoOptimizer_V1/app/main.py PaidVideoOptimizer_V1/tests/ui_smoke.py
git commit -m "feat: add chengfang content decision workspace"
```

## Chunk 6: Documentation, migration and acceptance

### Task 6: Make the upgrade reviewable on real data

**Files:**
- Modify: `PaidVideoOptimizer_V1/docs/乘方协同素材诊断设计.md`
- Modify: `PaidVideoOptimizer_V1/docs/本地DEMO与真实数据验收.md`
- Modify: `PaidVideoOptimizer_V1/docs/测试报告.md`

- [ ] **Step 1: Add a Chengfang import checklist.**

Require one confirmed same-plan, same-path, `chengfang`-partition 7-day material snapshot containing creative-attributable cost, net GMV, net orders and impressions; the same-period plan marketing-cost total; a reconciliation delta no larger than `max(¥1, 1%)`; complete plan context and explicit capability flags; pilot labels for 10–20 materials; and the relevant operation log. State that `overall` is totals-only and cannot enter material or group ROI.

- [ ] **Step 2: Add a migration checklist.**

1. Stop the local application and copy the complete `PaidVideoOptimizer_V1/data/` directory as the restorable backup; workspace JSON export is an audit artifact, not a one-click restore.
2. Select Chengfang mode explicitly.
3. Save plan context and capability flags.
4. Confirm the latest import partition and cost basis.
5. Label a pilot set of 10–20 materials.
6. Generate a diagnosis but do not change plan settings during the observation window.
7. Record the human content-production and plan-level actions.
8. Import the next comparable period and replay the diagnosis.

- [ ] **Step 3: Run the final suite and capture evidence.**

Run: `cd PaidVideoOptimizer_V1 && .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
Expected: PASS.

Record one legacy replay and one Chengfang replay. The Chengfang evidence must assert frozen partition, source import IDs, plan-context revision, profile-label revisions, thresholds, operation IDs and recommendations after live records change; confirm the proposal endpoint returns a local-only 409 without reservation, proposal or audit write. Confirm the legacy replay remains unchanged. Neither replay may produce an external platform write.

- [ ] **Step 4: Commit.**

```bash
git add PaidVideoOptimizer_V1/docs PaidVideoOptimizer_V1/tests
git commit -m "docs: document chengfang diagnosis acceptance"
```

## Acceptance checklist

- [ ] Existing independent-boost demo completes unchanged.
- [ ] Chengfang context refuses absent or contradictory partition/cost declarations.
- [ ] A low-exposure high-ROI material receives `OBSERVE`, not expansion.
- [ ] Cross-partition data never yields a combined ROI.
- [ ] `overall` data is rejected from material/group ROI diagnosis.
- [ ] Material-attributable costs reconcile to the plan total within `max(¥1, 1%)`, or ROI conclusions are blocked.
- [ ] Missing labels prevent a content-direction conclusion but do not erase raw material data.
- [ ] Context changes block stable direction conclusions and appear in the snapshot.
- [ ] Legacy proposal APIs remain functional only in legacy mode; Chengfang returns a clear local-only diagnostic message.
- [ ] Diagnosis CSV and replay retain the original labels, thresholds, context and source imports.

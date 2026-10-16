# 镜头生产通用能力升级实施记录

日期：2026-10-16。研发分支：`codex/shot-source-production-20261016`。

用户授权顺序：先更新复盘文档，再“先review下文档，然后实施”。本轮是工程研发与离线验证，没有新增图片、视频、TTS、音乐或外部Judge调用，没有发布新作品，也不把现有沙发垫V6自动批准。

## 审查结果与已实施修正

实施前审查修正了5处设计缺口：明确源片审核的入口和副作用、逐镜头scope存储与消费者、唯一父预算账本、活动并发与累计消耗的独立口径、沙发垫配置新增v2而非改写v1。

实施后独立规范审查与代码审查发现并修复：

| 问题 | 最终行为与回归 |
|---|---|
| 尾帧没有进入外传预检 | 实际发送的 `end_image_url/path` 纳入全部媒体校验；未声明／未授权尾帧不发请求 |
| 已获得任务号但未绑定账本时崩溃 | 核对原attempt/key/预算/谱系后补绑并查询同一任务；不能拿任意GET任务接管预占 |
| 源片评价被成片发布门借用 | sample/compose/publish完成门明确拒绝source_clip，batch汇总排除源片 |
| 生成计划只被当作参考字典 | 付费前校验schema、实际依赖字节、项目／镜头／修订／预算与生产锁 |
| decode仅按名称检查 | 源片decode项必须使用decode方法，不能用抽帧冒充 |
| 无关或失败回执也能送审 | 回执、实际媒体、原始inputs指纹、任务、尝试和预算身份共同绑定；缺历史信息拒绝送审 |
| 改用途删掉商品身份要求 | 新增非空global_requirement_ids，每个用途及选段均核验全用途要求；原全貌结果单独保留 |
| 固定模型却返回其他模型 | 保存服务商实际模型；源片合同拒绝与固定输入模型不一致的结果 |
| 新字段破坏旧任务恢复 | 旧journal没有新增可选metadata时仍可查询原任务；不伪造旧输入指纹 |
| 前端／state只认识成片审核 | 新增source专属卡片、素材阶段入口及prepare API；用途通过不计成片、不写脚本checkpoint |

## 能力与接口

- `lib/generation_references.py` 提供只读参考预检，核验角色、字节、原生成回执、实测视频时长、已保存的URL可用性及授权。预检不访问远端，也不把本地来源证据当作服务商资格认证。
- Seedance适配器保留结构化服务商拒绝与未知结果，并支持新原币种账本；实际生成模型、usage、媒体hash、account fingerprint和原输入／请求身份保存在回执。
- `CostTracker(project_dir=...)` 使用唯一 `artifacts/budgets/generation.json` 管理原币种父预算，Decimal原子计算、跨进程预占、幂等恢复；旧USD接口兼容。native读取使用 `get_native_entry` / `snapshot_parent_budget`，旧 `entries` / `cost_snapshot` 仍为旧账本视图。历史账本不自动折算或迁移，新生产预算须依据剩余额度并注明历史未知承诺。
- `shot_source_plan` / `shot_source_record` 和 `evaluation_report.scope=source_clip` 已注册。记录存储在 `artifacts/shot_sources/<shot_id>/<revision>/`，绑定plan、evaluation、原inputs、原回执及媒体。
- `ReviewService.create_source_clip_review` 通过 `POST /api/v2/projects/{project_id}/source-reviews/{shot_id}/{revision}/prepare` 提交指定用途／选段。最终决定复用既有review接口和事务机制。
- 源片在素材阶段“镜头源片按用途审核”入口及compose候选页展示；原用途失败与局部候选可同时存在。历史批准只对原文件及用途有效。
- reviewer、asset director、Seedance与动态开头skills已固化参考分工、按原目标验收和停止规则；新增沙发垫v2保留v1字节及历史引用。

## 怎样开始下一条新镜头

1. 使用已批准事实、品类和品牌版本建立镜头承诺，指定原用途及全用途要求。商品身份归入 `global_requirement_ids`，全貌等构图要求按用途限定；参考图／人物／动作／构图分工必须明确。
2. 保存生产锁和全部参考、授权引用。新source输入使用 `project_id`、`project_dir`、`shot_id`、`revision_id`、`lineage_id`、`parent_budget_id`、`request_id`、`production_lock_ref` 和 `shot_source_plan`；其中身份与原币种预占一致。`request_id` 是native账本中的原请求身份，不能拿提供方request header混用。
3. 用 `CostTracker.create_parent_budget` 建立获批父预算，再 `estimate_native` 和 `reserve`。native不能改用另一个cost_log规避总额；相同原请求恢复复用预占。注册工具dry_run汇总参数和参考问题；通过预检不等于生产授权。
4. 在现有pipeline中调用注册工具并保存原始inputs与原始ToolResult。未知任务先恢复查询，不重新POST；确认源片字节后执行本地技术工具和画面复核。
5. 按实际返回身份填写record，保留原inputs文件的sha256。receipt中的canonical `source_inputs_fingerprint`核对inputs字典，`request_fingerprint`核对原provider请求；不用自引用文件哈希，也不重写原回执补造字段。
6. 逐项填写真实观察及时间点、审核者和输入模态。技术hard_gate仅表示技术；原用途与候选用途语义在source_review中判定。完整回放和抽帧如实区分，无声源片声音项说明不适用。
7. 调用source subject验证再提交所选用途。仅该用途人工通过后入池；合成、声音、完整片质量与最终验收仍走原主线。

具体API和脱敏跨层示例见 `tests/contracts/test_shot_source_contract.py::test_real_seedance_receipt_can_enter_source_review_offline`：它使用真实适配器返回字段，只mock网络、轮询和下载，不为回执补造身份。此测试证明接口相容，不能证明真实服务商生成画面合格。

## 离线验证与边界

- 第一轮全仓 `make test`：3483 passed、11 skipped、1 subtest passed；运行期间随后修复了审查发现的边界问题，因此该数字不充当最终变更的完整验收。
- 最终全仓 `make test`：**3543 passed、11 skipped、1 subtest passed，451.10秒**；跳过项包括可选live文档、未提供的历史gold/comparison素材、HyperFrames及环境相关测试，没有为本次实现新增跳过。
- 最后补充native pilot共账本接入，另跑包括恢复／参考／父预算／源片／审核台的核心回归：**182 passed，最后复跑5.60秒**。当前packet按自身预占数量限额，项目其他parent与既有修订不会误占packet上限；父预算全局上限仍核验，completed源片可回放预览验证。
- 恢复、参考、预算、源片与审核均有红→绿记录；`make lint`、前端三个改动模块的 `node --check` 和 `git diff --check` 通过。独立规范及代码审查完成，原报告的阻断问题均修复。
- 两条端到端审核测试验证真实UI提交source用途prepare接口、后端批准及operator-state schema，不生成媒体、不推进script checkpoint。
- `tests/fixtures/shot_sources/sofa_round_cases.json` 保存V3/V4b、图片4/5/6版及V6已记录观察的脱敏标签；`test_sofa_round_replay.py` 用它回放合同，验证改善不能抵消失败。它不是重新观看原视频、不是Gold Set，也不证明规模化成功率。
- V5明确拒绝以结构化服务商反例覆盖；旧回执／输入关联不足不自动迁入正式source审批。沙发垫V6仍是全貌任务未满足、局部用途待人工判断。
- 音乐、口播、完整动态视觉质量、线上留存与经营效果不属于本轮工程离线测试结论。

## 交接

总体方案：[镜头生产通用能力升级](../superpowers/plans/2026-10-16-shot-production-generalization.md)。源片验收与迭代模板位于 `docs/templates/`；总体评价、跨品类入口和沙发垫资料摘要已同步链接与当前状态。下一步生产先建立新的完整镜头记录，历史缺口不得用工程上线补造。

## 后续主干交付与真实生产验证

用户随后明确要求合并主干、推送远端并生成新样片。工程提交 `441b35328bfbef8fc3dcd588864796b1e0a62073` 已快进合并到 `main`，推送至 `origin/main` 和 `origin/codex/shot-source-production-20261016`，并核对远端提交号一致。合并后核心回归 **182 passed（5.95秒）**，lint通过。上文“未新增付费生成”仅指此前工程实施轮次。

真实生产已按新合同生成两段4.04秒动态素材：`full-C/v1` 包边和 `full-B/v1` 翻角背面，均已保存canonical源片记录并提交指定用途的人工审核，尚未批准入池。两次服务商usage目录估算各6.1495元，实付待核实。完整实铺 `full-A/v1` 全貌改善但商品纹理失败；`full-A/v2` 被服务商识别为视频编辑，因要求 `ratio=adaptive`、`duration=-1` 而失败，没有输出媒体。其原回执、尝试次数与未知结算费用保留，不伪装成已通过源片。完整口播10.92秒已生成；D收尾与完整片尚未生成。

历史V5明确HTTP400拒绝依据原错误回执纠正为活动任务终态，释放并发名额；没有删除原回执或将费用填零。A镜头两次请求上限已用完，当前等待追加一次参数修复的明确授权。仅有源片及本地检查，不构成完整片验收或批量生产成功率证明。运行记录留在本地 `projects/sofa-cushion-p1a-v1/artifacts/shot_sources/` 与 `artifacts/planning/full-film-v2/`，不随Git上传媒体或签名链接。

后续用户批准追加一次参数修复，A同一父预算保留全部历史条目并调整为22.2元／3次，未重建谱系或清空消耗；将已通过B素材不再需要的重试额度释放到整片分配，仍受原60元视频总额约束。自动时长本地预估30.8826元，预算门阻断且未提交；随后限定新生成4秒的 `full-A/v3b` 成功返回，目录估算7.2954元，但织纹与离手时间仍未满足，正式源片记录保留用途失败，停止追加。D与完整片仍未生成。

已通过注册 `video_compose` / Remotion输出新的 **3秒包边动态预览**：`renders/sofa-full-C-dynamic-preview-v1.mp4`，1080×1920、30fps、H.264/AAC，SHA-256 `5e25182108fe377114ce068862afc28def566e62117dc63ad24f37b75552a0a4`。统一LOGO、关键词、等宽下划线、字幕、Doubao口播和既有SUNO音乐；不是完整片，也不计300条。已登记preview生产记录与审核索引；真实DOM字体／布局通过，独立ASR存在繁简及“近／进”差异，保留失败，未调用外部Judge，未批准交付。

真实生产还暴露两项后续独立工程工作：品牌预检在渲染器将字体路径转为绝对路径后，与相对路径品牌引用比较失配；本轮使用相同字节字体的运行时路径绑定完成渲染，未改设计或代码。canonical依赖闭包仍拒绝该绝对字体路径，质量报告保持error而非通过；需独立修复路径归一化和引用闭包兼容。开头合同的兑现区间强制在3秒后，本次只登记为planning主体的未来回扣，明确未生成，不能据此声称主体兑现完成。

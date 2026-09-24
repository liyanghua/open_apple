# 批量生产与可信交付

适用于 cinematic-fast 的 research、script、scene、asset、compose、delivery 阶段。Agent 负责表达和阶段推进；使用现有 pipeline/checkpoints/canonical artifacts，不另建创意总控脚本。

## 批量内容与身份

先读取已批准 campaign_plan 的槽位及实验卡。商品 ID、内容方向、叙事结构 ID 分字段，试点 P1/P2 不等于原计划结构 P1–P6。原 300 排期保持 S01/S08/S04=100/120/80，四周各75、240实验加60支持。选择槽位后，把 content_slot_id、sku、work_id、run_id、content_version_id、experiment_family_id、production_route 写进单条 production_record。original_campaign_slot 不得用试点 ID 冒充。

事实版本、商品参考图、事实证据、原图及处理图哈希必须可追溯。AI演示动作不是实测证据。实测缺条件/来源、商品身份不清，先补素材。选择已批准卖点，允许 Agent 决定开头、场景、镜头运动、动作顺序与叙事；每次重要判断在 decision_log 写画面依据。

## 制作与局部返工

品牌执行 [production-brand-contract.md](production-brand-contract.md)。遵守指定字体真实文件与哈希、官方LOGO、关键词标题、等宽下划线、实测字幕和0.4秒尾音。展示类原始动作默认4秒，主体剪入1.8–2.6秒。实测/故事/轻喜剧使用各自 recipe，保留18–35秒主体与必要证据，不能全部套成8秒。

先资产检索和缺口分析；缺镜头才生成。商品参考必须绑定SKU，素材记原始/处理/输出哈希、任务ID、用途与使用区间。SeedanceArk提交前必须有正金额、操作匹配、足额预占和任务幂等键。未知远端状态先 query，禁止盲重发。creative追加最多2次；judge格式修复最多1次。若仍不合格，记录失败类别，交人工选最小修改，不追加无限任务。成功但创意淘汰的素材仍计费。

声音先生成并测量实际词时间；口播文案保持事实边界，左上只放关键词。用已批准 SUNO 素材和混音规范；检查BGM对口播的遮盖。最终音轨更换后，独立ASR/人工听审与字幕时轴必须重新验证。所有素材的provider/model/resolution记录真实值，960×960素材裁切成1080×1920不能标原生1080p生成。

## QA与正式验收

`production_audit` 是只读工具，使用 `operation=collect|verify|fingerprint`、`project_dir`、`record_path`；collect还接收 evidence_refs。返回报告由现有项目写入事务存入canonical路径，不能用返回success推导质量合格。

collect 的来源键：technical、brand_dom、narration、alignment、product_review、continuity、video_judge。原始报告必须绑定实际render_sha256；technical使用FinalQA实际输出media_sha256；brand_dom要真实浏览器测量；narration要独立ASR。几何预检、TTS输入和历史同路径文件不是这三项的测量证据。

机器项：file_integrity、decode、video_profile、duration、audio_track、font_identity、text_layout、dependency_integrity。内容项：fact_source、product_identity、narration_content、caption_alignment、visual_continuity。保留pass/fail/not_run/error；summary会重新核对源报告及实际媒体。人工替代仅可用于允许的内容项，包含具名reviewer_id、带时区verified_at、render_sha256、qa_report_sha256、检查项与证据路径；不能替代fact_source或机器项。

成片审核使用 ReviewService.create_final_review(record_path, submitted_by)，审核台通过现有版本/hash/CAS决策接口。留言与正式批准分开。每次交付、promote、restore都验证production_record_path、final_review_id与所有依赖；文件或依赖变化使旧批准不适用于新版。历史导入保留legacy_import与阶段缺口，不补造checkpoint。

## 差异、计数、成本和释放

跨母题至少在开头、场景、动作、结构、证据等3个实质维度变化；只换字体/颜色/文件名无效。受控实验绑定同SKU、同家族、基准与预登记变量，允许只改该变量，不受3轴规则误杀。媒体fingerprint使用实际解码首3秒和逐秒关键帧；dHash只是预警，纯色背景/统一品牌层可能误报。结合真实素材区间、顺序、口播和成片并排审核，不能凭哈希不同认定内容独立。

同片重复导出、W2/W3旧基准引用、W4同成片两路径只计一个work。进入300计数需要服务器验证的实际媒体、依赖、全套必要检查与版本批准，不读取自报status=approved。工作台只投影canonical records，不另建状态表。

预算/预占/目录估算/实付分开，币种不可猜汇率。未知实付=null，已知小计与未知项数一并列出。W4共同准备只计一次，人工/AI路径分别记增量与共同成本各50%分摊全成本。记录排队、模型、Agent工作、人工等待、渲染、返工时长；没有测量留null。

W1先选已解锁类型30条校准，批次5–10；新结构在所属周首件批准后释放。原SKU事实、品牌严格预检、实际预算和周次/结构首件均具备后才下付费单。300条首轮逐条审核。原方案预算情景不是付费授权，质量或素材不满足则延期。

# Video Judge / Video Reward Model 开源生态深度调研

> 从自动打分到 Claim Verification、Agentic Critic 与生成优化闭环  
> 版本：v1.1（评审修订版，修订记录见文末）  
> 调研日期：2026-08-21  
> 适用：AI 视频生成质量评测 / Shot Generation Optimizer / 电商短视频生成

## 执行摘要

本报告调研 VideoScore2 之外，与 Video Judge、Video Reward Model、Video Generation Evaluation、Preference/Verifier、Physics/World Consistency 相关的开源项目与最新研究路线。

**核心判断：Video Judge 正从“单模型输出总分”快速演进为“细粒度 Rubric + 原子 Claim + 主动证据获取 + Specialist Verifier + Reasoning + Reward/Repair”的 Evaluation Plane。**

对于电商 Shot Generation，不建议训练一个“大而全”的 E-commerce VideoScore 来包办画质、商品一致性、动作、物理、卖点、镜头语言和商业表现。更合理的架构是：**ShotSpec → ClaimSet → Judge Router → Specialist Judges → EvidencePack → Hard Gate / Soft Reward → Diagnosis / Repair → Regenerate**。

第一阶段最值得直接借鉴的开源组合：
- **ETVA**：原子条件验证
- **VisionReward**：Rubric / Checklist
- **VideoReward / VideoAlign**：通用 Reward + Best-of-N
- **MJ-VIDEO**：MoE Judge Router
- **VideoPhy-2 / PQSG**：物理与交互验证
- **VBench-2.0**：Evaluation Harness
- **VQ-Insight / VR-Thinker / DeScore**：Reasoning Judge 演进

---

## 1. 什么算 Video Judge

Video Judge：输入视频及其生成条件（prompt、image reference、ShotSpec、任务要求，或两段候选视频），输出可用于评价、排序、过滤、训练或修复的视频质量信号。

输出可以是：
- scalar score
- multi-dimensional score
- pairwise preference
- QA verdict
- defect label
- temporal localization
- reasoning trace
- repair instruction

核心区分：

```text
视频生成质量 ≠ Shot 执行正确 ≠ 商品表达正确 ≠ 内容商业有效
```

---

## 2. 领域演进

> 演进为趋势示意，非严格时间序（例如 ETVA 早于 Reasoning Judge 浪潮）。

```text
Feature Metric
    ↓
Human-aligned Reward
    ↓
Fine-grained Rubric
    ↓
Reasoning Judge
    ↓
Atomic Claim Verification
    ↓
Evidence Grounding
    ↓
Diagnosis / Repair
    ↓
Generate → Judge → Repair → Regenerate
```

---

## 3. 核心开源项目

### 3.1 VideoReward / VideoAlign
- Repo: https://github.com/KlingAIResearch/VideoAlign
- Paper: https://arxiv.org/abs/2501.13918（*Improving Video Generation with Human Feedback*, NeurIPS 2025；VideoReward 为论文提出的 reward 模型名）
- 约 182K 人类 preference annotation，12 个视频生成模型。
- VideoReward 评价 Visual Quality、Motion Quality、Text Alignment。
- VideoGen-RewardBench 约 26.5K annotated triplets。
- Reward 可用于 filtering、reject sampling、Flow-DPO、Flow-RWR、Flow-NRG。

**借鉴：** 最适合做 General Reward 与 Best-of-N baseline。

### 3.2 VisionReward
- Repo: https://github.com/zai-org/VisionReward
- Paper: https://arxiv.org/abs/2412.21059
- 视频数据集：VisionRewardDB-Video（HuggingFace: THUDM/VisionRewardDB-Video）
- 视频数据约 33K，最多 64 个细粒度维度。
- 每个维度通过 judgment question 进行 Yes/No 判断，再线性加权。
- 支持 pointwise scoring 与 pairwise compare。

**借鉴：** 最适合做领域 Rubric Engine；但 Critical 条件不能只靠加权平均。

### 3.3 MJ-VIDEO
- Repo: https://github.com/aiming-lab/MJ-Video
- Paper: https://arxiv.org/abs/2502.01719
- 五类 28 个 criteria。
- MoE Reward Model 动态选择 expert。
- 输出 criteria / aspect / overall 三层分数。

**借鉴：** Judge Router / Specialist MoE。

### 3.4 ETVA
- Repo: https://github.com/guankaisi/ETVA
- Paper: https://arxiv.org/abs/2503.16867
- Prompt → semantic scene graph → atomic questions → commonsense → Video QA。
- 2K prompts / 12K atomic questions / 10 categories。
- 官方报告 Spearman 58.47（同基准既有指标约 31）。

**借鉴：** ShotSpec → Atomic Claims 的最佳参考之一。

### 3.5 VideoPhy-2
- Paper: https://arxiv.org/abs/2503.06800
- 约 200 类 action。
- 评估 semantic adherence / physical commonsense / physical-rule grounding。
- 提供 VideoPhy-AutoEval。

**借鉴：** 电商商品交互的 Physics Specialist。

### 3.6 PQSG
- Repo: https://github.com/atinpothiraj/pqsg
- Paper: https://arxiv.org/abs/2606.25306
- Object → Action → Physics DAG。
- 每个节点为 Yes/No question。
- 父节点失败会向子节点传播。
- 可直接评估自定义视频并输出 graph、answers、score。

**借鉴：** Selling Point Evidence Graph。

### 3.7 VQ-Insight
- Repo: https://github.com/xuanyuzhang21/VQ-Insight
- Paper: https://arxiv.org/abs/2506.18564
- Reasoning-style VLM。
- 支持 multi-dimension scoring / pairwise / natural video scoring。
- Progressive Visual RL / GRPO。

**借鉴：** General Reasoning Judge / Meta Judge。

### 3.8 VR-Thinker
- Project: https://vr-thinker.github.io/
- Paper: https://arxiv.org/abs/2510.10518
- Weights: https://huggingface.co/qunwang13/vrthinker（无公开代码仓库）
- Thinking-with-image。
- reasoning 中可 SelectFrame 主动获取新帧。
- configurable visual memory window。

**借鉴：** 两阶段取帧，降低固定采样漏检。

### 3.9 DeScore
- Repo: https://github.com/KlingAIResearch/DeScore
- Paper: https://arxiv.org/abs/2605.05922
- Think-then-Score：CoT 与最终 score head 解耦。
- 两阶段：discriminative cold start + dual-objective RL。

**借鉴：** 未来自研领域 Reward Model 时，不要把 reasoning 文本和 scalar calibration 强耦合。

### 3.10 VBench / VBench-2.0
- Repo: https://github.com/Vchitect/VBench
- Paper (VBench-2.0): https://arxiv.org/abs/2503.21755
- VBench-2.0：Human Fidelity / Controllability / Creativity / Physics / Commonsense，18 个细粒度维度。
- 同时使用 generalist 与 specialist evaluator。

**借鉴：** Evaluation Harness / Registry。

### 3.11 T2V-CompBench
- Paper: https://arxiv.org/abs/2407.14505
- 7 类 compositional ability。
- 混合 MLLM、detector、tracker。

**借鉴：** 可确定问题优先用 specialist，不要所有问题都交给一个大 VLM。

### 3.12 LOVE / AIGVE-60K
- Repo: https://github.com/IntMeGroup/LOVE
- Paper: https://arxiv.org/abs/2505.12098
- 3,050 prompts / 20 tasks / 58,500 videos / 30 T2V models。
- 约 120K MOS + 60K QA。

**借鉴：** Gold Set 同时存 MOS、pairwise、QA、failure tag。

### 3.13 UnifiedReward
- Repo: https://github.com/CodeGoat24/UnifiedReward
- Paper: https://arxiv.org/abs/2503.05236；UnifiedReward-Think: https://arxiv.org/abs/2505.03318
- 2.0 支持视频 pointwise / pairwise。
- UnifiedReward-Think 引入 CoT。

**借鉴：** General Reward baseline。

### 3.14 补充条目（未展开）

- **VideoScore2** — https://github.com/TIGER-AI-Lab/VideoScore2（"Think before You Score"）。本报告以此为 baseline 之外展开，列此仅作对照。
- **Video-R1** — https://github.com/tulerfeng/Video-R1（NeurIPS 2025）。Reasoning judge 同族，与 VQ-Insight / DeScore 并列的重要工作。
- **WorldVQA** — https://github.com/MoonshotAI/WorldVQA。原子世界知识 QA，可作为物理 specialist（§3.5 / §3.6）的评测素材。
- **VBench++** — 同一 VBench repo 下的 I2V 等扩展；做 Evaluation Harness 时注意其扩展能力。

---

## 4. 2026 新范式

### SG-PVR
Paper: https://arxiv.org/abs/2606.11838  
Prompt → Critical/Minor claims → spatio-temporal scene graph → claim-by-claim verification。适合参考为未来 ShotSpec Verifier。

### VQQA
Project: https://yiwen-song.github.io/vqqa/  
Paper: https://arxiv.org/abs/2603.12310
QG Agent → QA Agent → Prompt Refinement Agent → Global Rater。把 critique 变成 semantic gradient，直接闭环修复 prompt。

### VIGOR
Paper: https://arxiv.org/abs/2603.16271  
几何 foundation model + 跨帧重投影误差，适合作为 geometry/temporal specialist。

### Wan-R1 / Verifiable Reward
Paper: https://arxiv.org/abs/2603.27866
说明在客观正确性任务中，通用 MLLM reward 可能产生退化解，应该使用可验证 reward。注意：论文实验对象是迷宫求解与机器人导航等客观任务；把这一结论推广到 SKU、Logo、数量、位置等电商约束，是本报告的应用引申。

---

## 5. 推荐 Evaluation Plane

```text
                      ShotSpec
                         │
                         ▼
                    Claim Compiler
                         │
                         ▼
                    Evaluation Plan
                         │
                         ▼
                     Judge Router
 ┌───────┬───────┬─────┼─────┬───────┬──────────┐
 ▼       ▼       ▼     ▼     ▼       ▼          ▼
Product Visual Motion Physics Intent Evidence Technical
 Judge   Judge  Judge  Judge  Judge  Judge   (L1a rules)
 └───────┴───────┴─────┴─────┴───────┴──────────┘
                         ▼
                    Evidence Pack
                         ▼
                      Meta Judge
                  ┌──────┼──────┐
                  ▼      ▼      ▼
                PASS   REPAIR REJECT
                         │
                         ▼
                      Regenerate
```

> 与 §6 evaluator 的对应：product_retrieval → Product Judge，physics_judge → Physics Judge，evidence_graph → Evidence Judge。Technical/L1a 为确定性规则校验（ffprobe / OCR / 黑帧 / 时长），不消耗 VLM。

---

## 6. Claim Compiler

```yaml
shot_spec:
  product: silver_antibacterial_towel
  action: wipe_wet_hair
  camera: close_up_slow_push
  selling_point: high_absorbency

claims:
  - id: P01
    type: product_identity
    expectation: exact_or_approved_sku
    criticality: hard
    evaluator: product_retrieval

  - id: SP01
    type: selling_point_evidence
    expectation: visible_absorption_effect
    criticality: hard
    evaluator: evidence_graph

  - id: PH01
    type: physics
    expectation: plausible_hand_towel_hair_interaction
    criticality: hard
    evaluator: physics_judge
```

---

## 7. Hard Gate + Soft Reward

原则：确定性规则优先。能用规则确定的判定（OCR 对 SKU/价格、ffprobe 技术指标）不消耗 VLM judge，且直接压低 Critical FAR。

```text
HardGate =
  ProductIdentityPass         # SKU/Logo 一致性（含 L1a OCR 确定性校验）
  AND CriticalClaimsPass      # hard 级 claim 全部通过（见 §6）
  AND StructuralIntegrityPass # L1a 技术校验：黑帧/静帧/音画缺失/时长越界/字幕越界/音量
  AND Safety/CompliancePass

HardGate=false → Reject

R =
  w_visual*Visual +
  w_motion*Motion +
  w_aesthetic*Aesthetic +
  w_alignment*Alignment +
  w_content*ContentFit
  - λ_cost*Cost - μ_risk*Risk

Best-of-N:
V* = argmax R(V_i), subject to HardGate(V_i)=true
```

> 公式与 GrowthBench（AutoDesign v1.1）§19/§20 对齐：Cost/Risk 罚项与 Novelty/Diversity 探索步（70/20/10 流量）在 GrowthBench 中定义，此处为 judge 侧简化公式；上线实现以 GrowthBench 为准。

---

## 8. 电商评价体系建议

> 编号约定：本节 L1-L8 是本报告局部编号，与 GrowthBench（AutoDesign v1.1 §11）的 L1-L6 并存。两者共用 "L#" 记号，落地实现以 GrowthBench 编号为准，映射见下表。

1. L1 Technical Validity
2. L2 Generation Quality
3. L3 Product Fidelity
4. L4 Shot Intent
5. L5 Interaction & Physics
6. L6 Selling Point Evidence
7. L7 Content Effectiveness
8. L8 Business Outcome

| 本报告 L1-L8 | GrowthBench L1-L6 | 说明 |
|---|---|---|
| L1 Technical Validity | L1 Hard Gate（L1a 确定性校验） | ffprobe / OCR / 黑帧 / 时长 |
| L2 Generation Quality | L3 Creative Quality | 通用 judge 主战场 |
| L3 Product Fidelity | L2 Grounding | SKU / 事实 / Claim-Evidence |
| L4 Shot Intent | L2 + L3 | 跨层 |
| L5 Interaction & Physics | （GrowthBench 缺口，仅 L1b"商品变形"） | 建议回填至 L3 或 L1b |
| L6 Selling Point Evidence | L2 + L4（Selling Point Clarity / Proof Strength） | |
| L7 Content Effectiveness | L4 Persuasion + L5 Platform Response | |
| L8 Business Outcome | L6 | |

通用 Video Judge 主要覆盖本表 L2-L5（对应 GrowthBench L3 Creative Quality + L2 Grounding）；企业真正应长期沉淀的是 L3、L4、L6-L8（对应 GrowthBench L2 Grounding + L4 Persuasion + L5/L6 在线层）。

---

## 9. Gold Set

不要只有“爆款/好视频”。

建议：
- Gold
- Silver
- Bad
- Hard Negative

每个样本同时保存：
- pointwise score
- pairwise preference
- claims/QA
- failure tags
- timestamp evidence
- expert reason
- human adoption
- online outcome

---

## 10. Judge 自身评测

核心指标：
- Spearman / Kendall
- Pairwise Accuracy
- Critical False Accept Rate
- Critical False Reject Rate
- Claim F1
- Temporal Localization
- Calibration
- Best-of-N Uplift
- Repair Success Rate
- Cost / Latency
- Judge 版本治理（judge_version / rubric_version 记录 + replay scoring + IRR 验收，见 GrowthBench §19.1）
- Online CTR/CVR/Retention correlation

**最核心的生产指标不是离线总分，而是：Human acceptance@1 + Critical FAR + Cost per accepted shot。**

---

## 11. 90 天路线

### 0-30 天
- 统一 evaluator interface
- Technical（L1a 确定性规则）/ Product / General Quality / Claim Alignment 四类 evaluator
  - General Quality 起步：VisionReward（rubric）或 VideoReward
  - 原子 Claim 验证：ETVA
  - Best-of-N baseline：VideoReward
  - 维度注册表参考：VBench-2.0
- 100-300 个专家 Gold samples（仅作 sanity check；Gate 阈值校准需更多数据，样本量纪律见 GrowthBench §26.1）
- Best-of-4

### 31-60 天
- 时间戳 Evidence
- Physics / PQSG
- Failure taxonomy
- Repair Agent

### 61-90 天
- Pairwise + Hard Negative
- Gate threshold calibration
- 轻量领域 ranker / reward head
- 接真实上线数据

---

## 12. 最终判断

长期目标应定义为：

**E-commerce Video Evaluation Plane**

而不是单个 E-commerce VideoScore。

```text
Video Judge =
  Claim Compiler
+ Judge Router
+ Specialist Judges
+ Evidence Grounding
+ Meta Judge
+ Preference Calibration
+ Repair Loop
```

Judge 最终必须回答三件事：
1. 这个 Shot 能不能用？
2. 为什么不能用，证据在哪里？
3. 下一轮到底要改什么？

只有这样，才能形成：

**Generate → Judge → Diagnose → Repair → Regenerate → Learn**

---

## 参考资料

1. VideoAlign / VideoReward — https://github.com/KlingAIResearch/VideoAlign
2. VisionReward — https://github.com/zai-org/VisionReward
3. MJ-VIDEO — https://github.com/aiming-lab/MJ-Video
4. ETVA — https://github.com/guankaisi/ETVA
5. VideoPhy-2 — https://arxiv.org/abs/2503.06800
6. PQSG — https://github.com/atinpothiraj/pqsg
7. VQ-Insight — https://github.com/xuanyuzhang21/VQ-Insight
8. VR-Thinker — https://vr-thinker.github.io/（Paper: https://arxiv.org/abs/2510.10518；Weights: https://huggingface.co/qunwang13/vrthinker）
9. DeScore — https://github.com/KlingAIResearch/DeScore
10. VBench — https://github.com/Vchitect/VBench
11. T2V-CompBench — https://arxiv.org/abs/2407.14505
12. LOVE — https://github.com/IntMeGroup/LOVE
13. UnifiedReward — https://github.com/CodeGoat24/UnifiedReward
14. SG-PVR — https://arxiv.org/abs/2606.11838
15. VQQA — https://yiwen-song.github.io/vqqa/
16. VIGOR — https://arxiv.org/abs/2603.16271
17. Awesome Reward Models for Video Generation — https://github.com/chrisliu298/awesome-rm-for-video-generation
18. VideoScore2 — https://github.com/TIGER-AI-Lab/VideoScore2
19. Video-R1 — https://github.com/tulerfeng/Video-R1
20. WorldVQA — https://github.com/MoonshotAI/WorldVQA
21. Wan-R1 — https://arxiv.org/abs/2603.27866

---

## 修订记录

- **v1.0（2026-08-21）**：初稿。
- **v1.1（2026-08-21，评审修订）**：
  - 事实核查修正：§3.8 VR-Thinker repo 链接（原 `qunzhongwang/vr-thinker` 404）改为项目页 + arXiv + HF 权重；§4 Wan-R1 补链接并注明电商约束为应用引申（论文实验对象为迷宫求解与机器人导航）；§4 VQQA 补论文链接；
  - §3 各条目补齐 Paper/arXiv 编号；§3.2 补 VisionRewardDB-Video 数据集名；§3.4 ETVA Spearman 补对照（既有指标约 31）；新增 §3.14 补充条目（VideoScore2、Video-R1、WorldVQA、VBench++）；
  - §8 增加 L1-L8 ↔ GrowthBench L1-L6 映射表，明确编号约定（落地以 GrowthBench 编号为准）；
  - §5 架构图新增 Evidence Judge 与 Technical/L1a 节点，与 §6 evaluator 名对齐；§7 定义 StructuralIntegrityPass、补确定性规则优先原则、R 公式与 GrowthBench §19/§20 对齐；
  - §10 补 judge 版本治理指标；§11 Phase 0-30 具体化开源选型并注明 Gold samples 用途边界（sanity check，阈值校准另需数据）；§2 演进图注明趋势示意、非严格时间序。

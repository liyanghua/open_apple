# 首镜保护区审核：证据已完成，暂不建议合成 v4

日期：2026-09-28。范围：d037 授权的首镜 s01 源帧 0–37；仅本地分类证据，不是新修复样片。

## 结论

工具和证据输出已通过规格、代码审查；但这版分类没有找到足够的原片结构保留区域，不能据此宣称解决了木纹模糊或桌垫亮边缺口。**不建议把这版绿色区域批准为正式修复遮罩，也没有生成 v4。**

每帧编辑区共 12,869 像素。红色风险区（含防漏字保护边）12,001 像素；绿色“可能可保留”仅 12–65 像素，平均 32.32 像素，占编辑区 0.251%。绿色很零散，没有形成足以修复当前纹理损失的连续区域。这个比例不是全片素材复用率。

**这是当前保守启发式分类的结果，不是真实可恢复像素的上限。** 分类依赖原片与既有模型候选的颜色、梯度一致性，以及时间统计；模型候选本身的纹理损失可能让真实干净结构也无法通过一致性检查。没有足够独立证据时，不应靠放宽阈值制造“通过”。

## 怎么看

每行三列：左为原片，中为原片上的区域标记，右为 d032 已有模型候选。右列不是新修复结果。

- 红色：疑似旧字或描边风险，包含 2 像素安全边，不是精确文字真值。
- 绿色：可能可保留的原片像素，**尚未批准，不能自动回混**。
- 黄色：不确定区域，不可当作干净背景。
- 未着色区域：原编辑遮罩外，不在这轮提案范围内。

所有 38 帧静态对照已检查。未见明显完整字形被标绿，但极少量绿色像素尚无独立“无文字/无阴影”证明。连续动态播放尚未完成视觉验收；播放器格式和帧数校验通过不等于动态质量通过。

## 局部动态对照（仅诊断）

1.267 秒，38 帧，30fps，无声；H.264/yuv420p，1186×234。画面有“仅提案、非修复视频”标识。

![首镜保护区诊断，不是 v4](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/overlay-diagnostic.mp4)

## 全部 38 帧审核图

图片保留原生局部像素尺度，每张最多 5 帧。点击图片可细看。

### 源帧 0–4

![源帧 0–4 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-00-proposal.png)

### 源帧 5–9

![源帧 5–9 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-01-proposal.png)

### 源帧 10–14

![源帧 10–14 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-02-proposal.png)

### 源帧 15–19

![源帧 15–19 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-03-proposal.png)

### 源帧 20–24

![源帧 20–24 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-04-proposal.png)

### 源帧 25–29

![源帧 25–29 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-05-proposal.png)

### 源帧 30–34

![源帧 30–34 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-06-proposal.png)

### 源帧 35–37

![源帧 35–37 保护区提案](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/contact-07-proposal.png)

## 验证与范围

- 代码：`3142a3015eda21f3c89cbc0e5d271e97e04dfded`，独立分支 `codex/temporal-caption-repair`，未合并主线。
- 新增测试 26 项通过；已有遮罩/时序/费用回归 136 项 + 1 subtest 通过。规格审查、独立质量审查通过证据阶段；质量审查另独立运行 25 项测试，真实素材测试由主代理验证。
- 非阻塞维护项：分类常量目前与报告一致，但代码存在重复数字，后续应统一引用参数表，避免未来修改产生漂移。本轮未以此改变算法。
- 真实证据工具执行 4.992 秒（不包含开发、测试与人工审核时间）。
- 源片、原遮罩、5 组已批准豆包 TTS 的 7 个文件哈希全部未变；费用账本哈希未变。
- 新增模型调用 0；新增服务费用 0；未修改 s06、其他镜头、原片、TTS 或正式素材清单。
- [机器报告](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/report.json) / [视觉审查记录](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/visual-review.json)。
- 标签文件名为 `unapproved-label-proposals.npz`；`proposal_only=true`、`approved_for_restore=false`、`accepted_for_production=false`。

## 下一步建议（待确认，未执行）

建议先选首帧、中间帧、末帧各一帧，人工标明“确定没有旧字的桌垫亮边和木纹”，验证这些结构能否在固定编辑区内形成有意义的保留区域。此步仍只做证据、不合成、不付费；人工标记也不能证明被旧字遮住的背景真实内容。

如果三帧验证仍不足以改善，应该承认既有候选的纹理质量限制，再单独讨论新候选或不同修复方法及其费用；不能重复叠加调色、自动放宽遮罩或直接批量。整体 assets 阶段仍未通过。

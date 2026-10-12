# 首镜去字 v2：旧字已移除，接缝仍需优化

2026-09-28，d032 单次授权。仅首镜约 1.27 秒，不是 13.2 秒全片。

## 实际结果

已查看全部 38 帧局部图及中段全画幅三列对照，未再看到可辨识旧字幕，
也未看到上一轮的灰色输入块原样保留。旧字幕下方已变为生成的背景。
但字形遮罩边界仍有色差、纹理不连续和硬接缝，不能标记为合格素材。

无损 master 的 38 帧所有非遮罩 RGB 均与原片完全相同；H.264 审核代理
不承诺像素完全相同。内容精确对位及正常/慢速动态播放尚未完成可验证验收，
因此不宣称无闪烁或时序合格。`accepted_for_production=false`，等用户审核反馈。

## 审核入口

![首镜去字测试 v2](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v2/review/review.mp4)

三列从左到右：原片 / 模型原始候选 / 仅遮罩内回贴。

![三列对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v2/review/comparison.mp4)

[半速对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v2/review/comparison-slow.mp4)

## 这次实际修改

唯一生成输入变化：原遮罩内的 RGB 预填 127。源片、遮罩范围、提示词、seed、
模型、帧映射、服务端 preprocess=false 和硬合成策略保持原样。灰色只是
模型输入，不作为最终遮盖底板。v1 原始结果与 d030 账本保持不变。

依据：[官方 VACE 输入定义](https://github.com/ali-vilab/VACE/blob/main/UserGuide.md#31-vace-recognizable-inputs)。
这证明修正输入后本例去字结果改善；不能推广为所有镜头已可稳定去字，也不能
据此宣称已核实 fal 全部内部预处理行为。

代码 `7fe2813`，独立代码审查通过。相关完整回归 126 项 + 1 subtest 通过。
新增测试先出现 3 项预期失败，修正后 4 项针对性测试通过。

## 本次运行

- 原片 38 帧，输入补至 81 帧，输出取回中间 38 帧；720×1280、30fps、无音频。
- 本地准备 5.391 秒；上传加提交 17.415 秒。
- 一次生成请求 `01a0e629-07e1-7f92-9781-ccfc1fa36d7e`，预算记录 `020d75060348`。
- 两次同任务恢复调用分别为 3.744 秒（IN_PROGRESS）及 6.736 秒（完成并下载）。
- 本地合成、无损校验和对照输出 7.796 秒。
- 未独立记录服务端推理/排队耗时，上述工具耗时不可相加冒充端到端耗时。
- 候选 SHA-256：`e2346ec5a1b18e4f8e1f6cb3fb2bd9ef377a4186dbbe717c64000d50f32305df`。
- 本轮只提交一次；未换模型、扩大遮罩、重做 s06、生成口播或合成全片。

## 费用与下一步

目录估算 $0.405，$0.50 预占转为待结算承诺，实际账单未知。
项目承诺 $5.5012，剩余 $2.9988，15 笔结算未知。d032 已消耗，任务已完成，
无需再查询，更不能再次 submit。

下一步建议先研究不扩大遮罩的本地边界/色差匹配，使用现有候选，不立即再付费
生成。还需验证桌沿对位与动态稳定性。任何更大编辑范围或新增模型试验单独确认。

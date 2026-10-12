# 首镜去字 v3：局部衔接修复对照

2026-09-28。用户已认可 v2 的去字效果，本轮按 d034 继续无新增推理的本地优化。
这是 **1.27 秒首镜诊断片**，不是 13.2 秒全片，也没有替换已确认的口播或素材清单。

## 先看结果

旧字仍未出现；部分边界色差减轻，但放大后仍有木纹模糊补丁和残余轮廓。
部分帧的桌垫亮边存在小缺口/台阶，不能凭颜色匹配认定几何对位已解决。
本版保留为诊断候选，**尚不放行批量或全片**。去字效果认可和完整素材验收分开记录。

![首镜去字 v3](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v3/review/review.mp4)

下面左侧 v2，右侧 v3；均未叠加新字幕、没有音频，便于看原字幕位置的修补质量。

![v2 / v3 对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v3/review/v2-v3-comparison.mp4)

![中段局部：左 v2，右 v3](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v3/review/v2-v3-mid.png)

[原片 / 模型候选 / v3 三列对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v3/review/comparison.mp4) · [三列半速对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/masked-temporal-caption-v3/review/comparison-slow.mp4)

## 本轮改动及边界

- 复用 d032 同一候选，SHA-256 `e2346ec5a1b18e4f8e1f6cb3fb2bd9ef377a4186dbbe717c64000d50f32305df`。
- 在原字形遮罩内做谐和边界颜色匹配，仅以遮罩外原片与候选的差异约束修正；不采样含旧字的遮罩内原像素。
- 遮罩保持 12,869 像素，未扩大、羽化、模糊、缩放或跨帧平均；区外重新使用原片。
- 没有新模型调用、外传、s06 生成、TTS 重做或全片合成。v2 全部文件保留。

## 验证记录

38 帧、720×1280、30 fps。全部 38 帧无损 master 的遮罩外 RGB 与源片逐像素相等。
有损 MP4 仅用于观看，不宣称它逐像素相等。源片、遮罩和 5 组 TTS 的 7 个保护输入哈希未变。

已人工查看全部 38 帧原尺寸局部图、中段全画幅和 v2/v3 同帧对照，未见可辨旧字。
本次没有完成可验证的连续动态播放验收，故不宣称无闪烁、时序或内容对位通过。

局部处理、验证和基础对照输出共 **15.518 秒**，不含代码开发、测试、人工检查和额外 v2/v3 对照制作。
求解最多 311 次迭代，最大残差 `9.997e-7`；这些是数值收敛证据，不是画质分数。

代码版本 `2df11f3`，独立分支 `codex/temporal-caption-repair`，未合并脏主线。
新增集成测试先出现 3 项预期失败，再修正；针对性 10 项通过。
完整相关回归 **136 项 + 1 subtest** 通过，128.42 秒。
独立代码审核无阻塞问题；额外 20 个不规则、带孔和分离遮罩与直接矩阵求解对照通过。

## 费用和下一步

本轮新增服务调用和模型费用均为 0。此前 d032 的结算仍未知，不能因此把历史费用写为零；不变更预算账本。

请重点比较原字幕位置的木纹补丁和桌垫亮边。单纯颜色衔接改善有限，下一项需解决的是候选纹理/几何质量，
而不是继续叠加调色或把数值测试当作验收。若要改变遮罩范围、启动新的生成或处理其余镜头，需明确下一步范围和预算。

实现规范：[d034 局部边界修复](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/.worktrees/temporal-caption-repair/docs/masked-caption-boundary-refinement.md)。

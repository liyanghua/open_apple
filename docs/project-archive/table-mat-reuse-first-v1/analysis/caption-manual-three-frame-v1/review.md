# 首镜三帧结构核定

2026-09-28 · d039 · 仅审核证据，不是 v4

## 结论先行

**收紧遮罩有局部价值，但不足以单独解决当前的模糊补丁和亮边缺口。不建议把这次手工圈选直接扩展到 38 帧或全片。**

首帧、中间帧、末帧均已在原生尺度及 3 倍最近邻放大图中逐一目视检查。以下“手工标注”由代理根据真实图像选择坐标，不是用户已批准的精确分割，也不是新模型推理。

三个关键事实：

1. 有无字木纹小缝隙，但零碎、不连续。绿色示例框 85 像素，其中 80 像素落在原编辑遮罩 M 内（0.622% M）；另外 5 像素本来在 M 外。**这是本轮保守圈选的示例，不是所有可恢复像素的总数或上限，也不能和上一轮自动分类的 0.251% 直接比较准确率。**
2. 蓝色框中的清晰木纹、白色亮边及字间上方小缝隙全部在 M 外。这些像素本来就受原帧保护，不能算作这轮“新恢复”的面积。
3. 黄色框标出了亮边与字幕接近或交叠的观察区域。随着镜头运动，亮边从末字附近移向“真的绝”附近。被字形/描边覆盖处不能直接回贴原像素，否则旧字也会回来。

这次没有证明绿色区域绝对不含抗锯齿/阴影混色；没有制作可用于生产的保护遮罩，也没有验证全 38 帧的连续性。

## 图例

- **绿框 G1**：目视未见白色字形的小木纹示例；待审，不自动恢复。
- **蓝框 B1/B2/B3**：已在 M 外的干净结构对照；不需要新增恢复。
- **黄框 Y1**：亮边与文字接近/交叠的存疑区；这是观察框，不是扩大后的编辑区。

所有图片只是原图的放大和方框标记。没有修补、补绘、锐化或调色。精确坐标见 [标注记录](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/annotations.json)，坐标基于 395×170 原始局部图，而不是放大图。

## 首帧 0 · 0.000 秒

亮边处在字幕右上方，末字附近已经需要谨慎区分描边和桌沿。绿框仅为“这”上方一小段木纹，不能提供整条字幕背景。

![首帧标注](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/annotated-00-3x.png)

[无标记原图放大](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/source-00-3x.png)

## 中间帧 19 · 0.633 秒

亮边向字幕右半部分靠近。“的/绝”附近的字形、暗色描边与亮边结构不能只用亮度区分；蓝色亮边示例本来就在编辑区外。

![中间帧标注](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/annotated-19-3x.png)

[无标记原图放大](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/source-19-3x.png)

## 末帧 37 · 1.233 秒

“真/的/绝”周围的遮挡最值得关注。框内白色既包含字幕笔画，也包含桌垫亮边；当前原帧本身没有暴露完整、连续的字下背景。

![末帧标注](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/annotated-37-3x.png)

[无标记原图放大](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-manual-three-frame-v1/source-37-3x.png)

## 对修复路径的判断

| 问题 | 收紧遮罩能否解决 | 本轮证据 |
|---|---|---|
| 少量干净木纹被纳入编辑区 | 能减少部分不必要替换，仍需精确复核 | G1 有 80 个像素落在 M 内 |
| 字幕直接盖住的木纹 | 不能靠回贴同帧恢复 | 原片该位置含字形/描边 |
| 被旧字打断的桌垫亮边 | 不能只靠亮度分类或缩小 M | 三帧亮边位置与文字重叠情况不同 |
| 模型候选内部的纹理软化 | 不能靠增加几块零散原像素充分解决 | 本轮未找到可覆盖主要缺陷的连续结构区域 |

建议把后续优化重点转到 **“字幕区内的背景结构重建”**：先明确桌沿/亮边应该如何连续，再评估木纹补全质量，而不是继续叠加调色或扩大手工圈选。具体算法、是否复用其他帧或需要新候选仍需单独设计和验证；本轮不声称已实现，不默认新增模型调用或费用。

## 验证与当前边界

- 三张无标记放大图与既有证据的原片列逐像素一致（仅最近邻 3 倍复制）。
- 三张标注图的变化只在指定方框内；原片和历史样片均未更改。
- 源片、原遮罩和 5 组 TTS 共 7 个受保护文件哈希不变；费用账本不变。
- 新增模型调用 0；新增服务费用 0；没有生成 v4，没有修改 s06、其他镜头或正式素材清单。
- 只核定 3 帧；不据此宣称其他 35 帧或连续动态审核通过。
- 未修改生产代码，未重跑开发测试；本轮验证是图像等价性、坐标/遮罩交集及输入完整性检查。
- assets 仍未通过，绿色像素未获用户批准。依据字幕替换技能，保留旧字风险未排除前不能直接回贴。

[上一轮完整 38 帧原片/分类/模型对照](~/Desktop/open_source_vedio_gen_projects/OpenMontage-main/projects/table-mat-reuse-first-v1/analysis/caption-structure-review-v1/review.md)

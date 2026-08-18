# 镜头参考机制与素材匹配证据设计

## 目标

镜头映射页让用户同时判断两件事：输出镜头借鉴了参考爆款的什么机制，以及自有素材为什么适合承担该镜头。界面不把结构借鉴伪装成逐镜复制，也不允许参考视频进入成片素材路径。

## 核心模型

每条 `scene_plan.metadata.source_mapping[]` 在现有自有素材映射字段之外，记录以下参考证据：

```yaml
scene_id: sc01
reference_evidence:
  mode: direct_segment | structural_only | none
  reference_scene_id: reference-1        # direct_segment 时必填
  reference_interval:                    # direct_segment 时必填
    start_seconds: 0.0
    end_seconds_exclusive: 2.4
  mechanism: "动作与结果成对，快速建立产品证明"
  rationale: "该机制适合本镜头的冲突钩子意图"
source_path: projects/.../inputs/source/owned.mp4
source_interval:
  start_seconds: 1.0
  end_seconds_exclusive: 3.6
source_fit: "自有素材完整包含防刮动作和结果"
mapping_reason: "用自有测试片段实现参考中的证明机制"
originality_note: "只复用证明结构，画面、产品和文案均来自本项目"
```

状态含义：

- `direct_segment`：有可靠的参考分段和时间区间，可以播放对应参考片段。
- `structural_only`：只确认结构或机制对应，不声称存在具体参考片段关系。
- `none`：没有可靠参考证据，明确展示未建立关系。

## 工作台布局

每个输出镜头使用一个未嵌套卡片的结构：

1. 顶部显示镜头编号、镜头内容、成片时间和镜头意图。
2. 中部为稳定的两列对照区。
3. 左列标题为“参考机制”。`direct_segment` 时播放限制在参考区间内的原视频；`structural_only` 时展示机制和结构标签；`none` 时展示明确空状态。
4. 右列标题为“自有素材匹配”。播放当前 `source_path/source_interval`，并展示素材内容与适用能力。
5. 底部统一展示“映射结论”和“原创边界”，说明两列为什么能形成当前镜头。

桌面端两列等宽；窄屏按“参考机制 → 自有素材匹配 → 映射结论”的顺序纵向排列。播放器使用固定宽高比，动态文字不能改变媒体区域尺寸。

## 数据投影

`backlot.operator_state` 将 reference analysis 中的分段信息与 `reference_evidence.reference_scene_id` 对齐，生成左侧播放器需要的 `preview_url`、`poster_url`、起止时间和说明。右侧继续使用 `source_media_review` 与已有 source mapping。

旧项目兼容规则：

- 有旧版 `reference_basis` 但没有逐镜证据时，投影为 `structural_only`。
- 不按镜头序号或时间比例自动猜测参考片段。
- 旧项目仍能看到现有映射理由，不阻塞工作台打开。

## 约束与校验

`cinematic-fast` scene mapping validator 增加以下语义约束：

- `direct_segment` 必须包含有效 `reference_scene_id` 和有序、有限的 `reference_interval`。
- 参考区间必须位于已分析参考视频时长内，并匹配已解析的 reference scene。
- `structural_only` 必须包含非空 `mechanism` 和 `rationale`，不得伪造播放器区间。
- `none` 不得携带参考区间。
- 所有模式仍要求自有素材路径来自已验证的 `source_media_review`。
- `reference_media_usage` 必须保持 `analysis_only`，参考路径不得进入 assets、edit 或 render。

## 测试

测试覆盖：

- operator state 正确投影三种参考证据状态。
- schema 对新增字段进行严格验证。
- UI 合同包含左右列、两类播放器和三种空状态。
- validator 接受有效 direct/structural 映射，拒绝越界区间、缺失引用、伪造区间和 reference source path。
- `table-mat-mix-v6` 旧 artifact 显示为 `structural_only`，不会被错误标为逐镜参考片段。
- 桌面两列和窄屏单列均无溢出或重叠。

## 非目标

- 不自动生成新的参考镜头对应关系。
- 不允许用户选择参考视频作为成片素材。
- 不在本次改动中重新运行项目的付费模型或生成样片。

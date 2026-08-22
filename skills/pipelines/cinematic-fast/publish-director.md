# Publish Director - Cinematic Fastline

Read the complete `skills/pipelines/cinematic/publish-director.md` and
`skills/meta/fastline.md` before acting. Package the verified local render,
metadata and QA evidence under the project workspace. This stage never uploads
to Douyin, WeChat Channels, Xiaohongshu or another external platform without a
separate explicit authorization.

## Publish gate（三态语义，评审缺口 #3）

final-scope `evaluation_report` 是发布前置，三种状态分别处理：

1. **`status == "fail"`（fatal L1a：SKU/价格/参数/敏感词）→ 一律阻止。**
   向用户呈现失败项并停止；任何决策记录都不得放行（publish checkpoint
   写入同样被硬性拒绝，见 `lib/checkpoint.py` publish gate）。
2. **`status == "revise"`（可修复 L1a 失败）→ 用户显式确认后放行。**
   把失败项逐条列给用户；只有用户明确确认才可发布，并追加 decision_log
   条目作为审计证据：`category: "downgrade_approval"`，`subject` 固定为
   `"Publish with fixable L1a failures"`，`reason` 列出失败项。未确认不得
   推进。
3. **optimization 门禁（仅 `optimization_policy.enabled=true` 的项目）**：
   publish 前必须同时满足 `evaluation_report.hard_gate.pass == true`、
   `evaluation_report.optimization.passed == true` 且
   `optimization_run.status == "passed"`；任一不满足即阻止（未达标的最佳
   候选可以展示给用户，但不得标记为自动通过）。policy 未启用
   （`enabled=false` / 项目无 policy）时保持原行为。

`creative_advisory` 首期是信息项，不进发布硬门；`video_judge` 不可用时
（无 `DASHSCOPE_API_KEY`）不得宣称自动达标，也不得启用 optimization 门禁。

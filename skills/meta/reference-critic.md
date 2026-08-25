# Reference Critic（参考片批判）

在 reference 分析之后、proposal 之前，对参考片做一次**批判**，而不是直接复刻。

## 核心原则

> Reference is Evidence, not Prescription —— 参考片是证据，不是处方。

参考片的天花板可能不高（硬切、无故事、花字朴素、钩子功能化）。忠于参考片 =
高保真地把平庸生产出来。本 skill 强制 Agent 显式判断参考片的**质量天花板**，并
把每个机制分类为 KEEP / IMPROVE / REPLACE / DO_NOT_COPY。

## 产出

写入 `research_synthesis.reference_critique`（schema `research_synthesis`）：

```json
{
  "reference_ceiling": "medium",
  "keep": ["第一秒直接给动作", "近景动作证明"],
  "improve": ["钩子加冲突/反常识", "加入故事结构", "花字动效"],
  "replace": ["卖点清单式叙事 → beat map", "硬切 → 有意图的转场"],
  "do_not_copy": ["品牌/水印/头像/账号", "参考片原字卡布局", "逐镜画面顺序"]
}
```

- `reference_ceiling`：`high`（可直接对标）/ `medium`（需局部升级）/ `low`（仅借结构）。
- `keep`：值得保留的机制（写清楚"保留什么 + 为什么"）。
- `improve`：薄弱点（写清楚"弱在哪 + 升级方向"）。
- `replace`：需要替换的做法（写清楚"替换成什么"）。
- `do_not_copy`：绝不照抄的元素（品牌/水印/身份/逐镜表达）。

## 硬规则

1. 必须先定 `reference_ceiling`，再谈方向。不得跳过。
2. `improve` / `replace` 至少各 1 条（否则等于"参考片无懈可击"，几乎不可能）。
3. 每个 `improve` 必须能在下游落地（脚本/分镜/花字/转场中的某一层），不能只写
   "更好看"这种不可执行的判断。
4. `do_not_copy` 至少含：品牌识别、水印、账号身份、原文案（原创边界）。

## 下游消费

- proposal-director 读 `reference_critique`：3 个 concept 必须**明确继承 keep、
  改进 improve、替换 replace**，且不能触碰 `do_not_copy`。
- script/scene/caption/transition 各自把对应的 `improve/replace` 落地成可执行选择。

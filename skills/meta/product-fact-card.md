# Product Fact Card / ProductBible（产品事实卡收集，生产前硬门）

生产前由用户填写 SKU/价格/参数 + 产品主张 + 视觉真实性约束，落盘
`artifacts/product_facts.json`，供：
- `technical_validator` 的 L1a 事实类检查（sku/price/params）从 `skip` 变 `pass`；
- `fact_continuity_rules` 生成「事实和连续性 + 可声称边界 + 视觉约束」规则。

## 时机

- **单任务复刻**：idea/proposal 阶段、开始 research 之前。
- **多任务（batch）复刻**：`create_candidate_batch` 建批之前弹一次，全批共享
  一张卡（写入批根 `artifacts/product_facts.json`，`batch_fork` 会复制给每个候选）。

## 硬门（不可跳过）

生产前**必须**至少填齐 SKU/价格/参数三者之一 + `product_name`。缺卡的批次
不得进入付费生成（agent 应停止并升级，而不是静默继续）。只有「纯素材预览/
无付费调用的 dry-run」才允许跳过。

## 收集内容（结构化提问）

依次问用户：

1. **SKU / 型号**：如 `TM-2mm`。
2. **价格**：如 `69元`。
3. **关键参数**：逐条，如 `厚度 2mm`、`尺寸 60×120cm`。
4. **产品主张（claims）**：逐条，每条给 `status`：
   - `authorized`（可直接声称，有出处）
   - `needs_evidence`（仅在有画面/检测证据时声称，不外推）
   - `forbidden`（禁止声称，如"全网最低价"）
5. **视觉真实性（visual_identity）**：
   - `must_preserve`（必须保留：包装颜色、logo、产品形态）
   - `allowed_variation`（允许变化：角度、景别、光照）
   - `forbidden`（禁止：变色、变形、遮挡 logo）
6. **出处**：每项来源（用户填写 / 商品详情页 / 官方 / 检测报告）。

## 落盘

```json
{
  "version": "1.0",
  "product_name": "透明桌垫",
  "sku": "TM-2mm",
  "price": "69元",
  "params": ["厚度 2mm", "尺寸 60×120cm"],
  "claims": [
    {"claim": "0甲醛", "status": "needs_evidence", "evidence": "检测报告"},
    {"claim": "全网最低价", "status": "forbidden"}
  ],
  "visual_identity": {
    "must_preserve": ["透明材质", "无 logo 遮挡"],
    "forbidden": ["变色", "变形"]
  },
  "provenance": {"sku": "用户填写", "price": "用户填写", "claims": "官方/检测报告"},
  "filled_by": "user",
  "filled_at": "2026-08-24T00:00:00Z"
}
```

写入路径：`artifacts/product_facts.json`（经 `write_artifact_atomic`，schema 名
`product_facts`）。

## 下游使用

- `lib.product_facts.fact_continuity_rules(card)` → 生成 creative_control_plan 的
  `fact_continuity.rules`（含 claims 可声称边界 + visual_identity 视觉约束）。
- `lib.product_facts.check_text_facts(text, card)` → script 前向约束（价格/SKU 一致）。
- `technical_validator` 自动加载卡片 → L1a 事实检查 + invalid 卡片进 hard_gate。

## 校验语义（提醒）

L1a 的 sku/price/params 是「查冲突」不是「查存在」：只要求片子里**出现时不能
是错的**。claims 的 `forbidden`/`needs_evidence` 由 `fact_continuity_rules` 转成
导演总控单规则，在生成时约束 + 人工审核，代码层不硬拦"外推"。

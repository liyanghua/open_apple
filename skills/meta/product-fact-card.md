# Product Fact Card（产品事实卡收集）

生产前由用户填写 SKU/价格/参数的权威值 + 出处，落盘
`artifacts/product_facts.json`，供 `technical_validator` 的 L1a 事实类检查
（sku/price/params）从 `skip` 变为 `pass`，使 coverage 达标、去掉每批
`downgrade_approval` 手动放行。

## 时机

- **单任务复刻**：idea/proposal 阶段、开始 research 之前。
- **多任务（batch）复刻**：`create_candidate_batch` 建批之前弹一次，全批共享
  一张卡（写入批根 `artifacts/product_facts.json`，`batch_fork` 会复制给每个候选）。

## 收集内容（结构化提问）

依次问用户：

1. **SKU / 型号**：如 `TM-2mm`（字母+数字+连字符格式）。
2. **价格**：如 `49.9元` / `¥49.9`。
3. **关键参数**：逐条，如 `厚度 2mm`、`尺寸 60×120cm`、`耐温 200℃`。
4. **出处**（可选）：每项来源（用户填写 / 商品详情页 / 官方）。

**允许跳过**：用户说「暂不提供」→ 不写卡片（或只写 `product_name`），L1a 保持
`revise`，发布前需 `downgrade_approval` 手动放行。

## 落盘

```json
{
  "version": "1.0",
  "product_name": "透明桌垫",
  "sku": "TM-2mm",
  "price": "49.9元",
  "params": ["厚度 2mm", "尺寸 60×120cm", "耐温 200℃"],
  "provenance": {"sku": "用户填写", "price": "用户填写", "params": "商品详情页"},
  "filled_by": "user",
  "filled_at": "2026-08-24T00:00:00Z"
}
```

写入路径：`artifacts/product_facts.json`（经 `write_artifact_atomic`，schema 名
`product_facts`）。

## 校验语义（提醒）

填卡后，L1a 的 sku/price/params 三项是「查冲突」不是「查存在」：只要求片子里
**出现时不能是错的**，不要求必须出现。所以填了卡、片子里没乱写 → 三项 pass。

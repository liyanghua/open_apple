# 产品事实卡（Product Fact Card）设计 v0.1

> 目标：解决 L1a 因 `expected_facts` 为空导致的「事实检查 skip → coverage 不足 → 永远 revise」问题。
> 定位：生产前收集 SKU/价格/参数的权威值，喂给 `technical_validator` 的 `expected_facts`。
> 范围：早期极简版，只做「Agent 弹卡收集 → 落盘 → 接线 validator」，不做 Backlot 表单 UI。

## 1. 卡片制品（`product_facts.json`）

```json
{
  "version": "1.0",
  "product_name": "透明桌垫",
  "sku": "TM-2mm",
  "price": "49.9元",
  "params": ["厚度 2mm", "尺寸 60×120cm", "耐温 200℃"],
  "provenance": {
    "sku": "用户填写",
    "price": "用户填写",
    "params": "商品详情页"
  },
  "filled_by": "user",
  "filled_at": "2026-08-24T00:00:00Z"
}
```

字段语义（对应 `tools/analysis/technical_validator.py` 现有逻辑）：
- `sku`：商品编号/型号，匹配 `[A-Za-z]{2,}-?[0-9][A-Za-z0-9\-]{3,}`。
- `price`：价格，匹配 `\d+(\.\d{1,2})?\s*(元|块|RMB|¥|￥)`。
- `params`：关键参数的自然语言表述列表，逐项匹配前 8 字符。
- `provenance`：每项出处（用户填写 / 商品页 / 官方），满足审计要求。

## 2. 弹卡时机与形式

| 场景 | 时机 | 形式 |
|---|---|---|
| 单任务复刻 | idea/proposal 阶段（research 前）| Coding Agent 结构化提问：SKU / 价格 / 参数（可「暂不提供」跳过）|
| 多任务（batch）复刻 | 建批前弹一次，全批共享 | 同上，填一次写入批根，候选只读引用 |

- 用户跳过：卡片不生成或字段为空 → L1a 保持 `revise`，走 `downgrade_approval`（不阻塞生产）。

## 3. 数据流

```
用户发起复刻（单/批）
  → Agent 弹事实卡，用户填 / 跳过
  → 落盘 artifacts/product_facts.json（单任务）或 批根（多任务，候选只读引用）
  → sample/compose 的 technical_validator 读 product_facts → expected_facts
  → L1a sku/price/params 3 项 skip→pass
  → coverage 7 → 10（≥9）→ 可 pass
```

## 4. 收益

1. 单次填卡、多批复用（同一商品后续批直接引用）。
2. L1a 从 `revise` 变 `pass`，去掉每批 `downgrade_approval` 手动放行。
3. 事实真校验：片子里的 SKU/价格/参数写错会被 L1a 抓出（fatal）。
4. 为「自动选择/自动排名候选」铺路（可靠事实 + 可靠 VLM 评分是前置条件）。

## 5. 明确不做（保持简单）

- Backlot 表单 UI（先 Agent 结构化弹卡）。
- 逐参数细粒度 provenance / 参数匹配算法升级。
- 多商品事实库管理（先单商品）。

## 6. 实现拆分（后续）

1. `schemas/artifacts/product_facts.schema.json`（含 provenance）。
2. 接线：`technical_validator` 从 `product_facts.json` 读 `expected_facts`（替换硬编码空 `{}`）。
3. 弹卡：在 `cinematic-fast` 的 proposal/executive-producer 流程加一步「收集事实卡」（Agent 结构化提问）。
4. 批级共享：batch 建批时生成/引用一张卡，`batch_fork` 候选只读引用。

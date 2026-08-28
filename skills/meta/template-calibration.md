# 模板动作域标定（Template Calibration）

> 适用：任何「新模板出片」——标定是准入链第一步（readiness：未标定=阻断，策略 C）。
> 链路：`calibrate_template.py`（VLM/人工）→ 标定产物合并 → planner 预检 →（子集契约/换序）→ 出片。

## 1. 标定对象与域

每个 slot（镜头位）选唯一动作域（素材可证明的语义动作）：
防油易擦拭 / 防刮 / 无甲醛检测 / 桌角对齐-挤压不变形 / 自动铺开对齐 / 餐桌场景。

## 2. VLM 标定（推荐路径）

```bash
python -m scripts.calibrate_template --list                     # 未标定清单
python -m scripts.calibrate_template --template <tid> --mode vlm  # 单张
python -m scripts.calibrate_template --mode vlm --all            # 批量（36 张 ≈ 5 分钟）
```

- **Prompt v2 关键约束**（必须保留）：① 同域 ≤2 槽；② 相邻槽不同域；③ 语义优先、分布均衡（首尾 hook/cta 优先真实语义）；④ 只输出结构化 JSON（ordinal/domain/confidence/reason）；
- **阈值 0.85**：≥0.85 auto-accept，<0.85 标记 human-check（meta.low_conf）；
- 批量结果验证：本舱 35/35 成功，域均衡约束让 15/20 从 COMPRESS → DIVERSIFY_LIMITED（单提示词改进有效）。

## 3. 标定产物与接线（已固化）

- `lib/template_calibrations.py`：三节文件（`_CALIBRATIONS` / `_CALIBRATION_META` / `_GENERATED_ROWS`）——**重写文件必须保留三节**（write_calibration 曾踩丢节坑）；
- 口播行统一入口 `rows_for_template(tid)`：命名表优先 → 按标定动作域生成（VLM 模板零接线）；
- 标定合并：`SLOT_ACTION_BY_TEMPLATE.setdefault` 于模块加载时并入。

## 4. 标定后判断链

```
容量判级（capacity_verdict，显式表为可信源）
  ├─ DIVERSIFY_LIMITED → 可直接出片（试产）
  ├─ COMPRESS → planner 严格子集（可行 → rp.compression 契约）或换序改写（-c3/-c4）
  └─ MARK_GAP → 素材缺口账单（第 4 域/窗口容量扩容）
```

## 5. 聚簇修复（本轮）

- `--repair-swap`：H1-类（相邻同域）自动换槽修复（合成+实测通过）；
- **S2'-类（占比 >25%）换槽不可修**（换槽不改计数）→ 走 planner 子集 / 换序 / 素材（22 即此类，backlog）；
- 修复写回后必须重验：重建 → 语义 0 → reuse 报告。

## 6. 反例速查

| 症状 | 根因 |
|---|---|
| 语义门报「跨域 claim」（VLM 表） | 口播行与标定动作错位（接线）→ rows_for_template 兜底 + 不变量 18 |
| 容量判级与预期不符 | 未标定（关键词回退）→ 先 `--list` 确认 |
| 标定文件重写后 import 失败 | _GENERATED_ROWS 节丢失 → 三节重建 |
| swap 无解 | 检查是否 S2'-类（计数问题）非 H1-类 |

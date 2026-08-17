---
name: ecommerce-viral-remix
description: 使用参考视频的抽象结构和自有真实素材，制作原创电商商品短视频。适用于抖音、视频号、小红书的爆款复刻、商品混剪、真实测试型广告和同类短视频再创作。
---

# 电商爆款复刻

## Source caption policy (1.0.1)

自有烧录字幕只有在 rights、copy、claim 均审核通过后才可保留；参考视频
字幕禁止进入成片。生成层不得重复保留的源字幕；被拒绝 claim 必须采用局部
crop/mask 或已批准 replacement，并在逐镜中记录 action、interval 和 reason。

严格执行 `pipeline_defs/cinematic-fast.yaml`，并先读取当前阶段 director。

1. 校验建单输入、版权确认和付费素材授权。参考素材只能用于分析，自有素材才可进入成片。
2. 对参考与自有素材实际探测、抽帧和观看；持久化分析结果，后续阶段不得重复全量分析。
3. 提炼钩子、节奏、信息密度、证明结构和转场方法，提供三个原创方案，不逐镜复制。
4. 生成逐镜映射、完整口播、字幕和资产计划；所有镜头必须绑定真实素材时间段或明确缺口。
5. 在创意锁审批前不得调用付费生成；审批后只生成 10-15 秒样片。
6. 样片通过后完成精剪和成片；变更按 `no_render`、`mux_only`、`full_render` 路由并触发必要重审批。
7. 运行完整 QA：黑帧、冻结帧、字幕安全区、音频峰值、分辨率、帧率、编码和准确时长。
8. 输出到 `projects/<project-id>/renders/final.mp4`，外部发布需要单独授权。

使用 `profiles/home-protection.yaml` 处理桌垫、防护垫等家居商品；透明桌垫首单可参考 `examples/transparent-table-mat.yaml` 的输入结构，不复用其成片内容。

# OpenReel Timeline V2 Pilot

日期：2026-09-10  
范围：银离子毛巾 Source-led 候选的版本化精剪闭环

## 已验证路径

1. 从服务端 canonical `EditorialTimeline` 创建 child editorial session。
2. OpenReel actions 通过 bridge 转换为带 `base_generation_id`、`base_timeline_hash`、操作序号和幂等键的 typed `EditDelta`。
3. 执行镜头替换、分割和字幕时间调整；素材仅能来自 server-issued approved catalogue，事实范围不匹配时 fail-closed。
4. 生成独立版本目录下的 preview 和 final 文件，并写入服务端 alignment、L1a、final QA 报告。
5. 只有 preview 通过且人工批准、final 三项门全部通过时才允许 promote。
6. promote 使用 ProjectCommitStore 更新 delivery pointer；既有 `renders/final.mp4` 保持不变。

## 自动化证据

- `tests/integration/test_source_led_editorial_timeline.py`：验证替换/分割/字幕改时、preview → approval → final → promote、旧交付保护。
- 定向回归：179 passed。
- 更广回归：518 passed，1 skipped（既有环境跳过）。
- Task 9/10 bridge、Studio shell、gallery/API、feature flag 与 build manifest 回归：95 passed。

## 发布边界

- `OPENMONTAGE_EDITORIAL_TIMELINE_V2=0` 时隐藏 `/studio` 与 editorial gallery API，现有 `/p` 单条工作台保持可用。
- 首期只允许锁定 `render_runtime=remotion` 的候选；HyperFrames/FFmpeg 候选显示不支持原因，不创建 V2 session。
- 受控构建通过 `make editorial-editor-build` 生成来源 revision、LICENSE 和 bundle SHA-256 manifest。

## 尚需人工验收

- 在真实银离子毛巾候选上打开 `/studio/<batch>/edit/<candidate>`，确认浏览器中能看到真实视频、口播、BGM、字幕与事实绑定。
- 选择一个实际 approved asset 做替换，完成 preview 审核后再执行 final/promote。
- 通过后再将 feature flag 开放到四商品、16 条批量生产。

# VACE 字幕区重建：本项目调用说明

## 2026-09-28 修正试验 d032（当前）

用户已明确批准同模型单次试验、预留 $0.50，仍纳入原总预算 $8.50。
上一轮 d030 已完成且视觉失败，不得再次提交或覆盖历史。

本次只修改一项：在原字形遮罩内把送模 RGB 预填为 127。官方 VACE
UserGuide 的 src_video 约定缺失区域为中灰；旧输入保留字形 RGB 且关闭
preprocess，与该约定不同。此差异已证实，但不能断言是失败唯一原因。

- `masked_caption_composite.prepare` 显式使用 `input_preprocessing=vace_gray127`，
  生成 version=2 契约；81 帧逐帧检查区内 RGB=127、区外与原帧完全相同。
- `vace_caption_candidate` 使用 approval_ref=d032；费用 operation 为
  `s01_wan_vace14b_gray127_once`。新审批独立单次 claim，不复用 d030。
- 同一 fal endpoint、种子、提示词、steps、preprocess=false、帧数和遮罩不变。
  保留安全审核。只上传首镜与遮罩，无新商品图/TTS，无自动重试。
- 最终合成仍从原片复制区外像素，灰色输入不得作为成片或遮盖底板。
- d032 未获首镜效果审核前，禁止批量、s06 重做和全片合成。

证据：[官方输入定义](https://github.com/ali-vilab/VACE/blob/main/UserGuide.md#31-vace-recognizable-inputs)、
[官方预处理代码](https://github.com/ali-vilab/VACE/blob/main/vace/annotators/inpainting.py)。
以下 d030 说明保留作历史，不是当前可再次执行的授权。

能力核验日期 2026-09-26；价格于 2026-09-28 再次核验，仍为 720p 按 16fps 折算 $0.08/秒。只适用于已批准的 s01 试验（d030），不是批量授权。

## 使用前

- 通过 registry 的 `masked_caption_composite` 准备素材，通过 `vace_caption_candidate` 提交，不写临时 API 调用脚本。
- 固定 fal endpoint `fal-ai/wan-vace-14b/inpainting`；先检查文档批准的源片/字形掩码哈希、首镜契约、单次预算预占和审批。
- 源 38 帧补成 81 帧；前补 21、后补 22，仅取候选 `[21,59)`；保持 720×1280/30fps，无音频，不跨镜头。
- 字形掩码白色生成、黑色保留。使用同步的 `mask_video_url`，不使用会自动追踪显著对象的 `mask_image_url`。

## 提示词边界

这不是改产品或换桌面。已核对旧字幕遮挡区域：斜向深色木质桌沿、局部木纹及下方暖色背景。提示词描述原场景连续性，要求重建字幕及阴影下的背景、保持原镜头运动与桌沿连续，不引入新物体或新文字，不改颜色/材质。

中文意图：移除遮罩内的烧录文字与阴影，重建其下被遮挡的桌沿/木纹/背景，保持每一帧的可见几何、光照和运动。生成背景不作为产品性能证据。

使用设计中固定的 30 steps、seed20260926、guidance5、unipc、shift5、acceleration none、720p9:16/30fps。禁用自动抽帧/插帧、prompt expansion、preprocess；开启 safety checker。除首镜与遮罩外不传其他参考。

## 上传、请求和费用

- fal-client 1.0.3 的 `SyncClient.upload_file` 已本地检查支持 `lifecycle=StorageSettings(expires_in=86400)`；对视频和遮罩分别设置。SDK 会转换为 `expiration_duration_seconds=86400`，不能直接把字典当成 `StorageSettings`。
- 沿用项目的 `FAL_KEY` / `FAL_AI_API_KEY` 别名支持；独立工作区运行时从原项目安全加载配置，不复制或打印密钥。
- 提交设置 `X-Fal-Store-IO:0` 和输出24小时过期偏好；不承诺远端零留存。
- 仅一次推理 POST；durable intent/request ID 先落盘，提交不确定不能再 POST。只恢复同一请求。
- 按官方16fps计费口径，81/16×$0.08=$0.405，预占至多$0.50；账户实际结算未知时不能填零。
- 原内容若被服务拒绝，保留原因并停止，不通过换端点/关闭审核/修改输入规避服务限制。

## 验收

模型返回 81 帧并不代表内容对位；剪回38帧后，仅掩码内取候选，区外从源帧直接复制。FFV1主文件逐帧校验区外RGB完全相同，再逐帧及正常播放检查残字、桌沿、木纹闪烁。不叠新字幕或TTS遮掩问题。候选失败仍须如实记录，无自动重试、无全片。

## 一手来源

- [fal 模型/API](https://fal.ai/models/fal-ai/wan-vace-14b/inpainting/api)
- [fal 定价](https://fal.ai/models/fal-ai/wan-vace-14b/inpainting)
- [官方 VACE](https://github.com/ali-vilab/VACE)
- [Wan2.1-VACE-14B Apache-2.0](https://huggingface.co/Wan-AI/Wan2.1-VACE-14B/blob/main/LICENSE.txt)
- [Hugging Face Wan/VACE 掩码说明](https://huggingface.co/docs/diffusers/api/pipelines/wan)
- [fal-client upload_file/lifecycle](https://fal-ai.github.io/fal/client/fal_client.html)
- [fal 数据保留](https://fal.ai/docs/documentation/model-apis/media-expiration)

# 可复用生产品牌契约

在 cinematic-fast / Remotion 的 scene、asset、edit、compose、QA 阶段执行已批准毛巾品牌规范时读取。本文件提供确定性技术约束，不代替 Agent 的叙事、镜头或审核判断。历史两条成片的批准只证明其指定版本外观，不补造机器检查。

## 品牌 profile 与兼容边界

调用 `lib.production_brand.make_towel_brand_profile()` 生成现有 `brand_profile` schema 的兼容扩展：保留 `version/profile_id/font`，增加 `font.files` 和 `production`。继续用 `lib.brand_profile.merge_brand_defaults` 填缺省与处理已有 production lock；品牌规范变更仍须走现有批准/版本流程，不能借新字段覆盖已锁定选择。

默认固定位置（1080×1920）：logo right72/top96/width120；核心词标题 left72/top220，64px/700，单行2–4字；下划线与文字固有宽度相同，高8、间距22、#4874CB；逐字口播字幕38px/top1470/left72/right72。品牌层和字幕是独立持续层，切镜仅使入镜视频淡入5帧；出镜视频保留不透明底片及对应源素材 handle。

默认展示 recipe：原动作3–5秒（生成请求默认4秒）、正文剪辑1.8–2.6秒。hook/tail 可用更合适剪点。其他结构明确传入自己的 `recipe={id,raw_action_seconds:[min,max],body_cut_seconds:[min,max]}`，覆盖整个时长区间；不能把故事、关系、情景剧都压成8秒，也不能自动拉伸素材或加速口播凑模板。

## 字体身份与外观

strict 默认 family=`Microsoft YaHei`。必须提供400与700各一份真实字体资产：`{path,src,sha256,weight}`。`path` 相对于项目目录（或绝对路径），`src` 相对于 Remotion public 目录；二者必须是相同字节。文件可用且 SHA-256 与批准版本相同后，预检通过 Pillow/FreeType 读取内部 family/style、检查 regular/bold 和缺字；名字/扩展名或CSS font-family 都不算身份认证。中文 family 别名“微软雅黑”可接受。浏览器再 fetch 实际 public 文件、校验同一哈希，加载 FontFace 的400/700，关闭合成粗体，加载失败阻止渲染。

400与700都必须是直立 normal 字形；内部字体元数据为 italic/oblique 的文件不能用相同 family 和 weight 冒充正体。预检对其他已明确批准的 family 同样验证其真实身份；使用 Arial 等合成测试素材的通过结果，不构成微软雅黑身份或正式 PLAYBOY VI 认证。

找不到真实字体时，strict 明确 blocked；不得改用其他字体并写“微软雅黑已认证”。`make_towel_brand_profile(strict=False)` 只保留已验收 legacy 的 `Arial, "Microsoft YaHei", STHeiti, sans-serif` 外观，机器字体身份保持 `not_run`，整体 `degraded`，不能当新 strict 批量生产的解锁证据。本机/许可证的具体可用性仍由资产提供方确认，此工具不下载或替用户授权字体。

## 实际入口与 props

实际可调用入口：`remotion-composer/src/brand/entry.tsx`，composition id `ProductionBrand`。既有 `Root.tsx` 无需修改。主线 atelier entry 也可直接导入 `ProductionBrandFilm` 或 `ProductionBrandComposition`，将真实 JSON props 传入；不得只复制写死的示例。

```bash
cd remotion-composer
npx remotion render src/brand/entry.tsx ProductionBrand /absolute/project/renders/final.mp4 --props=/absolute/project/artifacts/production_brand_props.json --public-dir=/absolute/project
```

JSON包含：

- `profile`：上述完整品牌 profile。
- `width,height,fps,durationInFrames`：实际输出元数据；入口据此计算 metadata，不硬编码8秒。
- `logoSrc` 与 `footage`：真实本地 public 资源映射，例如 `{clip01:"assets/video/clip01.mp4"}`。
- `scenes[]`：`id,footageKey,fromFrame,durationInFrames,sourceInSeconds,sourceDurationSeconds,playbackRate,cropScale,role`。`role` 为 `hook/body/tail`；场景区间连续不重叠、完整覆盖成片。组件自动多保留每个出镜镜头5帧，预检校验源素材足够覆盖此handle；不得把已有重叠时间轴未经转换传入。
- `titles[]`：`{fromFrame,text}`，第一个从0开始，后续节点持续至下一标题，最后到片尾。
- `captions[]` 与 `words[]`：均为 `{text,startMs,endMs}`，`timingSource="measured_word_timestamps"`。使用最终真实TTS测量时间，不得填写按字数估算的伪时间。字幕串与完整测量口播串须一致（仅忽略标点/空格）；字幕为单行，过长则由Agent按真实语义与时间分段。
- `audio` 可选：`{narrationSrc,bgmSrc?,bgmVolume?}`，内部直接加载实际音轨。若由既有主线在渲染后混音，省略该字段，最终音轨QA仍须执行。字幕/末词时轴必须与最终音频保持一致。
- `recipe` 可选：当前叙事结构的明确节奏覆盖，不限制总时长。

最后一句必须完整包含“PLAYBOY，让日常更有质感。”；最后测量词的 endMs 到片尾至少0.4秒。增加片尾与素材覆盖以满足尾音，不能裁掉句尾去追目标秒数。独立ASR/人工听审仍验证音频确实说了这句话；输入时间轴预检不等同于独立内容识别。

每段字幕除文字拼接一致，还必须覆盖它对应的实测词时间区间，允许一帧的显示量化误差。字幕已消失而句尾仍在发音时不能通过；粗粒度词时间戳不足以支持更细的字幕分段时，先补充实测词边界，不按字数插值。输出 width、height、durationInFrames 必须为正整数。

## 预检和最终证据

```python
from lib.production_brand import preflight_production_brand
report = preflight_production_brand(props["profile"], props, project_dir=project_dir)
# 将 report 写到本 run 的 artifacts，和具体 props/dependency hashes 一起送 QA。
```

结果为 `{version,profile_id,status,strict_ready,scope,checks}`；整体 `passed/blocked/degraded`，单项 `pass/fail/not_run/error` 与结构化 `evidence`。`scope=production_brand_preflight`。每项检查ID稳定：input_contract、font_files、font_identity、logo_asset、text_geometry、speech_timeline、slogan、speech_tail、shot_rhythm、shot_timeline。

`text_geometry` 是固定字体文件度量与CSS行框预检，包含每个标题/字幕的时间区间与矩形、越界、同时存在的文字重叠、logo周围16px净空。logo_asset检查图片可解码和源宽度不少于展示宽度。无法确认背景复杂程度、视觉对比度、商品关键细节遮挡，也不能用这些预检替代最终画面审查。

在实际浏览器检查标题/字幕变化、切镜开始/中点/结束及末帧时调用导出的 `collectBrandDomEvidence(document)`，保留逐帧结果；需要浏览器驱动导入或暴露这个函数。它读取真实DOM bounds、font-loading状态与实际字体SHA，并检查越界/相互重叠/下划线等宽。不得只测一帧后声称整片通过。最终成片的字体加载、逐帧布局、解码、音轨、依赖哈希与人工视觉/内容批准，由现有QA汇总器汇总，预检不自行批准交付。

## 修复规则

字体缺失/hash漂移：定位实际资产与批准版本，补齐或回退到明确的legacy历史重现；strict任务保持blocked。缺字：使用覆盖实际中文的已批准字体，不依赖浏览器系统回退。标题越界/重叠：Agent缩成真正的2–4字核心词；字幕越界：按口播时间拆句，保留完整内容。logo背景不清：调整已批准镜头裁切/干净区，经画面检查确认，不生成变体logo。尾音不足：延长尾段和总时长。切镜闪黑：核对连续排程、5帧不透明出镜handle及源文件可用范围，不给品牌层套淡出。

旧的短横线、品牌文字中栏和“规格核对”式结尾不再是此profile的生产规范，标记为 superseded；已批准旧视频保持其原版本记录。

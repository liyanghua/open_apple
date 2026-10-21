# 自有实拍视频参考入池与火山存储上传

2026-10-16。研发分支：`codex/owned-reference-video`。用户已授权先补齐工程能力，再恢复禾沐-米咖沿边顺抚镜头。

## 目标与接口

保留当前 Seedance、预算、幂等与审核机制，增加两项工具能力，不把实拍素材伪装为AI产物。

1. `reference_media.provenance_kind="owned_live_action"` 显式选择实拍来源校验。`source_provenance_ref` 绑定所有者、当前媒体哈希、原始文件引用与所有权授权；裁片额外绑定原片区间和变换说明。所有权授权与“向某服务发送这些字节”的授权分别核对。
2. 注册 `reference_video_upload`，提供 `list_buckets`、`upload` 操作，通过官方TOS SDK使用现有AK/SK。上传必须指定已有桶、区域、当前文件和版本绑定的外传授权；只写内容寻址对象，生成短时GET签名引用及来源/可用性证据。

默认/历史生成视频继续要求原始生成任务、模型、账号及哈希回执。未知来源类型、所有者或哈希不一致、失效URL、缺少用途/接收方授权均阻断。实拍裁片不能填造生成任务号；本版裁片只支持无变速的时间截取，区间及原片/裁片时长必须相符。

## 上传约束

- 不新建桶、不扩大ACL、不使用FAL、HeyGen或其它未授权托管。必须明确选择现有桶；无可用桶/权限时报告资源缺口。
- 内容寻址键绑定SHA-256；已有同哈希/长度对象可复用，冲突不能覆盖。上传后HEAD核验元数据、长度，再通过禁止重定向的签名HTTPS GET核验完整字节及SHA-256，保存引用有效期及操作证据。该可用性证据不等于方舟模型已接受参考。
- `dry_run` 完全离线。真实上传前检查本地路径、媒体格式、授权和SDK配置；不在日志、错误或git文档输出密钥或签名URL。
- 上传工具不提交生成、不替调用方改变预算或参考类型。存储费用未结算时保持未知，不写为零。

## 验证与接入

先写失败契约测试，再实现。覆盖实拍接受/生成来源回归、错误所有权/哈希/裁片区间、来源类型伪装、权限缺失、路径逃逸、上传幂等/冲突、远程核验失败、过期URL及脱敏。

独立分支检查通过并完成代码复核后接入主线。随后只读查询同账户桶；存在适用桶且授权满足时上传已批准的42–44秒裁片，恢复严格参考预检。预检、最低计费和原父预算均满足后，最多生成一次4秒素材（新增视频上限10元），输出3秒预览等待用户审核，不直接替换完整片。

## 调用与记录

### 方舟托管路径（无需自建TOS桶）

现有方舟API Key可通过注册工具 `ark_reference_upload` 将本地二进制视频传至官方 Files API：`POST /api/v3/files`，`purpose=user_data`，不传 `tos`。文件保存到方舟默认托管空间，本流程默认保留25小时，为官方最少一天的限制预留传输时差。原始文件ID只是Files ID，不得拼成 `asset://`。

上传前原子记录当前账号指纹、媒体哈希与 `uploading` 状态。未知POST结果必须停下对账，不能再次POST；已知文件ID后使用GET查询恢复。仅当查询返回 `active` 和可读取的 `download_url`，且URL实际签名有效期、HTTPS主机、完整字节数和SHA-256均通过验证时，才能形成既有 `remote` 与 `availability` 证据。文件保留期不等于下载URL有效期。若账号接口不返回可验证链接，保持未完成；不可伪造素材ID、URL或有效期。

该路径复用 `volcengine_ark` 外传授权，不增加其它接收方。Files上传和Seedance视频输入是两个官方接口的组合，实际模型是否接受须在既有生成流程核验，不提前声称已被Seedance支持。

官方依据：[上传本地文件](https://docs.volcengine.com/docs/ark/upload-files-api?lang=zh)、[查询文件与临时下载地址](https://docs.volcengine.com/docs/ark/search-files-api?lang=zh)。

### 同账户TOS路径

可选依赖：`pip install -r requirements-media-upload.txt`（官方 `tos==2.9.3`）。凭据只在本机配置 `VOLC_ACCESSKEY`、`VOLC_SECRETKEY`；不得写入提交。至少需要指定对象前缀的 `tos:PutObject`、`tos:GetObject`，列桶另需 `tos:ListBuckets`。

只读操作：`{"operation":"list_buckets","region":"cn-beijing"}`。上传操作还需要 `project_dir`、项目内 `input_path`、`bucket`、`purpose`、`authorization_ref:{path,sha256}`，有效期 `expires_seconds` 为300–86400秒，默认3600秒。授权JSON应为 `status:"approved"`、`approved_by:"user:…"`，并以数组绑定 `media_sha256`、`purposes` 和 `recipients:["volcengine_tos"]`。由注册表调用，不写临时网络脚本。

实拍来源JSON：`kind:"owned_live_action"`、`owner_id:"user:…"`、`media_sha256`、`source_original_ref:{path,sha256}`、`ownership_authorization_ref:{path,sha256}`。所有权授权要求 `status:"approved"`、`approved_by` 与 `owner_id` 一致，并通过 `owned_source_sha256` 数组覆盖原片。裁片增加 `source_interval_seconds:[start,end]`、`transform_description`，媒体声明中的 `parent_media_ref` 必须与原片一致。

将完整上传回执保存到项目受控运行数据，并把 `availability` 单独保存为JSON。媒体声明的 `remote` 使用回执中的URL和有效期，再增加 `availability_evidence_ref:{path,sha256}` 指向该JSON，供既有参考预检核对。签名链接不进入git、公开报告或控制台；过期后对同一哈希对象再次调用工具可重新签名和GET复验，不重新PUT。远端超时后下一次仍先HEAD；存储费用为待结算。桶ACL和策略属于独立配置，HEAD/GET成功不证明桶策略为私有，本工具不修改它们。

官方接口依据：[TOS Python SDK](https://pypi.org/project/tos/)、[列桶](https://docs.volcengine.com/docs/TorchObjectStorage/ListbucketsPythonSDK?lang=en)、[文件上传](https://docs.volcengine.com/docs/TorchObjectStorage/OrdinaryuploadPythonSDK?lang=zh)。

## 首次接入观察（2026-10-21）

沙发垫实拍裁片已通过方舟Files二进制上传，查询为active，但当前账户返回中没有可验证的 `download_url`。因此“文件已上传”和“Seedance可用的连续视频参考”仍是两个状态，后者本次未达成；TOS路径因本地未配置所需AK/SK和桶而未实际上传。不得把工具契约测试通过写成上述两种存储路径都已在账户实测成功。

本次镜头实际使用本地抽取的三张实拍动作关键帧加两张商品参考图，继续通过已批准的Seedance 2.5生成新动态视频；这不是连续视频条件输入。生成成功不等于商品一致性通过：新片包边结构及离手时点失败，只导出了无声动作诊断片，未替换完整成片。具体状态见[首镜修订执行记录](sofa-cushion-touch-shot-revision-20261016.md#12-执行记录与当前放行结论2026-10-21)。

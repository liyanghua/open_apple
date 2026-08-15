# Backlot 项目工作台

Backlot 默认项目页是面向一线运营的全中文只读工作台。它展示项目总进度、当前任务、
预计时间、下一步以及九个业务阶段，不展开原始制作数据。

- 运营页：`/p/<project-id>`
- 诊断页：`/diagnostics/p/<project-id>`
- 运营状态：`/api/v2/projects/<project-id>/operator-state`
- 运营更新：`/api/v2/projects/<project-id>/events`

Milestone 1 状态为 `internal/trial`。当前版本只支持查看；内容编辑、身份认证、项目权限
和 Agent 对话将在后续里程碑开放。

## 本地运行

```bash
python -m backlot open <project-id>   # start server if needed + open browser
python -m backlot open                # library view (all projects)
python -m backlot serve --port 4750   # run the server in the foreground
```

## 状态更新

`watchfiles` 监听 `projects/` 下的变化并通过 SSE 通知浏览器刷新。旧工程看板仍在诊断页
保留，供开发和排障使用。

| Board element | Disk source |
|---|---|
| identity / rail order | `project.json` + `pipeline_defs/<type>.yaml` |
| stage states, gates, versions | `checkpoint_<stage>.json` + `history/` |
| script card / modal | `artifacts/script.json` |
| filmstrip cards | `scene_plan × script × asset_manifest` join |
| generating shimmer, activity | `events.jsonl` (written by `BaseTool` instrumentation) |
| cost meter | checkpoint `cost_snapshot` |
| renders | `renders/*.mp4` (+ root-level mp4 heuristic) |

Projects without checkpoints degrade gracefully to a "what the watcher
found" view — media, snapshots, renders.

**Replay**: a completed run can be scrubbed end-to-end (▶ REPLAY RUN on the
board) — reconstructed from checkpoint history and event timestamps.

Try it without a real production:

```bash
python scripts/backlot_simulate_run.py          # live demo run (~1 min)
python -m backlot open backlot-demo-run
```

Design doc: `internal/design/LIVING_STORYBOARD.md`.

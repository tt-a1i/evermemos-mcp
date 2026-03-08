# evermemos-mcp 演示手册（Phase 4）

[English](03-demo-playbook.md) | [简体中文](03-demo-playbook.zh-CN.md)

本手册用于 Memory Genesis 2026 的 3-5 分钟提交视频演示。

## 1. 演示目标

- 展示跨 session 记忆恢复能力
- 展示 `space_id` 隔离（coding/chat/study 三场景）
- 展示引用可追溯（timestamp + snippet + type + score）
- 展示 `fetch_history` 的时间线核验能力
- 展示 `forget` 的 best-effort 删除语义

## 2. 关键原则

- EverMemOS Cloud v0 写入是异步：先 `202 queued`，后续才可检索
- 视频演示不要做“现场写入后立刻召回”
- 正确流程：**预加载 -> 等待提取 -> 现场 recall/briefing**

## 3. 演示前准备

1. 配置 Cloud 环境变量（`.env`）
2. 执行预加载脚本（建议提前 5-10 分钟）
3. 确认 3 个空间至少各有 1 条可召回结果

```bash
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 4. 3-5 分钟脚本建议

### Part A（30-45 秒）：问题与定位

- AI 客户端每次新会话会失忆
- 我们提供 MCP 记忆层，不改客户端也能获得长期记忆

### Part B（45-60 秒）：空间发现与路由

1. 调用 `list_spaces`
2. 看到 `coding:*`, `chat:*`, `study:*` 三类空间
3. 说明 `space_id` 是唯一隔离键

### Part C（60-90 秒）：`recall` 实时演示

1. `recall(query="FastAPI PostgreSQL", space_id="coding:demo-app")`
2. 展示结果中的 `memory_type/snippet/timestamp/score`
3. 切换到 `chat:daily` 再 `recall`，证明不会串味

### Part D（45-60 秒）：`briefing` 实时演示

1. `briefing(space_id="coding:demo-app")`
2. 展示 `summary + highlights[]`
3. 强调 profile/episodic/event_log 分层来源

### Part E（30-45 秒）：`forget` 可控删除

1. 先用 `fetch_history` 展示目标 `memory_id` 在时间线里确实存在
2. 调用 `forget(memory_ids=[...])`
3. 优先再次执行 `fetch_history`，再按需用 `recall` 补充确认目标是否消失
4. 如果 Cloud 返回 `ok` 但目标仍可见，把它表述为当前 Cloud 限制，而不是 MCP 路由失败

## 5. 演示命令清单

```bash
# 预加载
uv run python scripts/demo_preload.py --wait --check-status

# 现场走查（list/recall/briefing，可选 forget）
uv run python scripts/demo_live_walkthrough.py
```

## 6. 常见故障与处理

- recall 为空但 pending_count > 0：说明提取仍在排队；应查看 `recall.lifecycle`，不要把 provisional/fallback 结果当成 searchable
- remember 返回了 request_status 但 found=false：状态记录可能还没可查，稍后再试（不影响异步写入已排队）
- Cloud 网络抖动：重跑 recall，或在视频中展示错误语义（UPSTREAM_UNAVAILABLE）
- list_spaces 不完整：先执行一次 preload，再 list_spaces
- `forget` 返回 `ok` 但目标仍能被 recall：当前 Cloud 的 targeted delete 可能没有真正作用到选中的 memory ID，应按上游限制处理，并用 appendix 证据替代强行 live 演示成功

## 7. 评分点映射

- 创新性：MCP 通用记忆层 + `space_id` 路由
- 技术深度：7 个 tools 闭环 + 错误语义 + 引用字段
- 用户价值：跨会话连续性、可查、可复盘、可验证

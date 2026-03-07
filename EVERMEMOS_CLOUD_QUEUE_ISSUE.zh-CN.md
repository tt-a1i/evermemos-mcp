# EverMemOS Cloud 异步提取过慢问题记录

> 最后更新：2026-03-07，基于实测数据（非推测）。

## 结论

- 当前问题**主要不是 `evermemos-mcp` 没按官方文档接入**。
- 主要异常点在 **EverMemOS Cloud 的异步提取队列 / `request_status` 状态推进**。
- 我们已通过 `metadata_fallback` / `pending_message` / `conversation-meta` 镜像把产品体验兜住，但**正式 memory extraction 在 15+ 分钟后仍停留在 `queued`**。

## 问题现象

- `POST /api/v0/memories` 成功返回 `request_id`（HTTP 202），但很久后 `GET /api/v0/status/request` 仍是：
  - `status: queued`
  - `found: false`
  - `message: Request is still being processed in the queue`
- 同时：
  - `conversation-meta` 可以立即更新
  - `recall` 只能依赖 `pending_message` 或 `metadata_fallback`
  - `episodic_memory` / `event_log` / 正式 `profile` 长时间不出现

## 实测验证（2026-03-07）

### 实验设计

- 向全新空间 `space::chat:curl-diag` 写入一条含身份+偏好的消息：
  > "My name is Alex and I prefer dark mode and TypeScript."
- 参数：`flush=true`, `role=user`
- 使用 `curl` 直接调用 Cloud API（绕过 MCP 层），排除本地代码干扰
- 写入时间：`08:05:23 UTC`，`request_id: 02177287072345...`

### 多时间点对照结果

| 时间点 | request_status | search results | profile | episodic | pending_messages |
|--------|:-:|:-:|:-:|:-:|:-:|
| T+0s (08:05) | queued, found:false | — | — | — | — |
| T+30s | queued, found:false | 0 | — | — | 0 |
| T+90s | queued, found:false | 0 | — | — | 0 |
| T+3.5min | queued, found:false | 0 | — | — | 0 |
| T+8.5min | queued, found:false | 0 | 0 (空 profiles) | 0 | 0 |
| T+15.5min (08:45) | queued, found:false | 0 | 0 (空 profiles) | 0 | 0 |

### 关键发现

1. **`flush=true` 无效** — 写入时设置了 `flush=true`，15.5 分钟后仍无任何提取产出
2. **`request_status` 没有推进** — 始终 `queued` + `found: false`，无中间状态
3. **search 和 fetch 全部为空** — profile=0, episodic=0, 没有任何正式记忆生成
4. **`pending_messages` 也为空** — search 返回的 `pending_messages: []`，意味着消息甚至未出现在 pending 列表中
5. **空间注册正常，MCP 路径下 metadata mirror 可立即生效** — 本次 `curl` 直连实验可确认 group/space 可被上游接受；另外我们在 MCP 路径的独立 live 验证里，`conversation-meta` 写入可立即生效。但这组 `curl` 实验本身不直接验证 metadata mirror。

### 之前的 flush 对照实验

对两条短消息分别做 live 写入：

- `chat:diag-noflush-...`：`flush=false`
- `chat:diag-flush-...`：`flush=true`

在 `t+0s` 和 `t+20s`：

- 两边 `request_status` 都仍是 `queued`
- 两边 `conversation-meta` 都立刻写入成功
- 两边 `recall/briefing` 都只能依赖 `metadata_fallback`

## 官方文档对照

### 官方文档明确支持的语义

- `POST /api/v0/memories` 成功后返回 `queued`
- 提取是异步的
- `flush=true` 的文档语义是 "Force boundary trigger"
- quickstart/cookbook 也把它描述成 "先写入，再等待索引/提取"

### 官方文档没有承诺的部分

- 没有说明 `request_status` 多久必须从 `queued` 变成 `success`
- 没有 searchable 的 SLA
- 没有说明 `flush=true` 后多久应完成正式提取
- 没有保证短消息一定会在很短时间内形成正式 profile / episodic / event memory

## 判责边界

### 我们的责任

- 正确调用 `POST /api/v0/memories`（已验证：HTTP 202 成功）
- 正确透传 `flush`（已验证：`flush=true` 明确传递）
- 正确查询 `GET /api/v0/status/request`（已验证：接口正常返回）
- 在上游正式提取未完成时，提供：
  - `pending_message` 提示
  - `conversation-meta` fallback
  - `metadata_mirror` 兜底

### 上游的责任

- 后台 extraction queue 的处理速度
- `queued -> success` 的状态推进
- 正式 memory extraction 的完成与可检索性
- `request_status` 对真实处理进度的可见性与一致性

## 当前可确认的判断

- **不是我们接错 API** — 直接 curl 调用，HTTP 202 成功
- **不是本地 metadata mirror 慢** — conversation-meta 可立即写入
- **不是 `flush=false` 导致** — `flush=true` 同样 15+ 分钟无产出
- **不是短时间观测偏差** — 多时间点持续跟踪至 15.5 分钟
- **`pending_messages` 机制也未生效** — search 返回 pending_messages 始终为空
- **主要是上游队列/提取流水线问题**

## 可反馈官方的简短版本

```text
我们在 EverMemOS Cloud (api.evermind.ai) 的真实集成中观察到以下现象，
想确认这是否属于已知行为或队列积压。

实验条件：
- 向全新 group 写入一条短消息（含身份+偏好信息）
- flush=true，使用 curl 直接调用 POST /api/v0/memories，返回 HTTP 202
- API key 有效（其他端点如 conversation-meta、search 均可正常访问）

观察结果：
1. POST /memories 返回 202 + request_id，消息被接受
2. conversation-meta 可以立即更新
3. GET /status/request 在 15+ 分钟后仍为 queued / found:false
4. GET /memories (profile/episodic) 返回 0 条结果
5. GET /memories/search 返回 0 条结果，pending_messages 也为空
6. flush=true 和 flush=false 表现一致

想了解：
- 从 queued 到 extraction 完成的预期时间范围是多少？
- 单条短消息 + flush=true 是否应该在几分钟内完成提取？
- pending_messages 在 search 中始终为空，这是预期行为吗？
```

## 相关仓库实现位置

| 文件 | 相关功能 |
|------|---------|
| `src/evermemos_mcp/evermemos_client.py` | Cloud API HTTP 调用（`add_message`, `search_memories`, `get_request_status`） |
| `src/evermemos_mcp/memory_service.py` | remember/recall/briefing 业务逻辑及 fallback 策略 |
| `src/evermemos_mcp/space_catalog_service.py` | conversation-meta 读写与空间注册 |

## 备注

- 当前产品层面已经可通过 conversation-meta fallback 稳定答出用户名字（如 "Tom"）
- 但这不代表 EverMemOS 正式提取已经完成
- "现在能答出来"和"上游已经正式处理好"是两件事
- 如果上游确认这是正常行为（如提取需要 30 分钟以上），我们的 fallback 策略需要在用户文档中明确说明预期等待时间

# OpenCode Zen 反代聚合系统 + New-API 调度器状态页

本目录包含将 OpenCode Zen 免费模型接入 New-API 的完整方案：

1. **dispatcher.py** — 流量调度器，轮询分发请求到多个 lane
2. **lane_proxy.py** — 单个 lane 的反向代理，转发到 opencode.ai/zen 上游
3. **docker-compose.yml** — dispatcher + N 个 lane 容器的编排文件

## 架构

```
客户端 / AI Agent
  │
  ▼ POST /v1/chat/completions
New-API (端口 4010)  ← SQLite 数据库，管理渠道/token/分组
  │  渠道 #1: "OpenCode Aggregator"，base_url = http://<host>:4020
  ▼
dispatcher (端口 4020)  ← dispatcher.py
  │  轮询 (round-robin) 分发到可用 lane
  │  管理 cooldown / quota 状态（持久化到 /logs/lane-state.json）
  │  提供 /status、/dashboard、/health、/v1/models 端点
  ▼
lane-01 ~ lane-24 (端口 4011~4034)  ← lane_proxy.py
  │  鉴权、模型别名映射、图片检测路由
  │  每个 lane 走不同的出口代理（实现 IP 轮换）
  ▼
https://opencode.ai/zen/v1/chat/completions  （上游）
```

## 核心组件说明

### dispatcher.py

- **端口**: 4020（环境变量 `PORT`）
- **职责**: 接收来自 New-API 的请求，轮询分发到各 lane
- **状态管理**: 
  - lane 级别 cooldown（网络错误、限流）
  - 模型级别 cooldown（某个模型在该 lane 上 quota 耗尽）
  - 状态持久化到 `/logs/lane-state.json`，重启后恢复
- **统计**: 每个 lane 记录 requests/success/errors 计数
- **自动恢复**: lane 从 COOLDOWN 恢复到 READY 时自动清零统计
- **Dashboard**: 内置 HTML 状态页（`/dashboard`），实时显示各 lane 状态
- **端点**:
  - `GET /status` — JSON 状态数据（供 New-API 前端页面调用）
  - `GET /dashboard` — HTML 可视化页面
  - `GET /health` — 健康检查
  - `GET /v1/models` — 聚合所有 lane 的模型列表
  - `POST /v1/chat/completions` — 转发请求（与 GET 共用 `do_POST = do_GET`）

### lane_proxy.py

- **端口**: 4011~4034（环境变量 `PORT`）
- **职责**: 接收 dispatcher 转发的请求，转发到 opencode.ai/zen 上游
- **模型别名**: 支持 `opencode/`、`961-zen/`、`HK-OC/`、`936-OC/` 前缀映射
- **图片路由**: 检测请求中的图片内容，自动路由到多模态模型（`mimo-v2.5-free`）
- **代理出口**: 每个 lane 使用不同的 HTTPS_PROXY 实现出口 IP 轮换
- **上游**: `https://opencode.ai/zen/v1`（环境变量 `UPSTREAM`）

### docker-compose.yml

- 定义 1 个 dispatcher + N 个 lane 容器（当前 20 个：01-08, 11-20, 23-24）
- lane-09/10/21/22 保留未启动（对应 ADSL 线路已下线）
- 所有容器挂载 `dispatcher.py` / `lane_proxy.py` 为只读（`:ro`），改代码后 restart 即可生效
- 每个 lane 的代理出口指向 192.168.9.4:7101~7124（iKuai ADSL 出口）
- 容器内还运行 `opencode serve --pure`（端口 18001），lane_proxy.py 作为前置代理

## 支持的模型

```
big-pickle
deepseek-v4-flash-free
mimo-v2.5-free          （多模态，支持图片输入）
ling-3.0-flash-free
nemotron-3-ultra-free
north-mini-code-free
laguna-s-2.1-free
```

## New-API 中的接入

在 New-API 管理界面创建一个渠道：

| 字段 | 值 |
|------|-----|
| 类型 | OpenAI Compatible (type=1) |
| 名称 | OpenCode Aggregator |
| Base URL | `http://<dispatcher-host>:4020` |
| 密钥 | `sk-1111`（与 dispatcher 的 `API_KEY` 一致）|
| 模型 | `opencode/big-pickle,opencode/deepseek-v4-flash-free,...` |

Token 分组设为 `opencode`，渠道分组也设为 `opencode`。

## 在 New-API 前端新增的页面

本仓库在 New-API 前端新增了「调度器状态」页面，用于在管理界面查看各 lane 的实时状态。

### 涉及的文件

**后端（Go）:**
- `controller/dispatcher_status.go` — 新增 `GetDispatcherStatus` handler，代理 dispatcher 的 `/status` 端点
- `router/channel-router.go` — 新增路由 `GET /api/channel/dispatcher/status`
- 通过环境变量 `DISPATCHER_STATUS_URL` 配置 dispatcher 地址（默认 `http://127.0.0.1:4010/status`）

**前端（React/TypeScript）:**
- `web/src/features/dispatcher-status/index.tsx` — 状态页面组件
- `web/src/routes/_authenticated/dispatcher-status/index.tsx` — 路由（需要管理员权限）
- `web/src/features/channels/components/drawers/sections/dispatcher-status-section.tsx` — 渠道抽屉中的状态卡片
- `web/src/features/channels/api.ts` — `getDispatcherStatus()` API 函数和类型定义
- `web/src/hooks/use-sidebar-data.ts` — 侧边栏新增「调度器状态」菜单项

### 页面效果

- 访问 New-API 管理界面的 `/dispatcher-status` 路径
- 或在侧边栏点击「调度器状态」菜单
- 每 5 秒自动刷新
- 显示每个 lane 的：状态（READY/COOLDOWN/QUOTA_EXHAUSTED）、请求数/成功数/错误数、恢复倒计时

## 部署到新服务器

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh

# 2. 克隆本仓库
git clone https://github.com/stevenwang288/new-api.git
cd new-api

# 3. 启动 New-API（默认 SQLite，端口 3000）
docker compose up -d

# 4. 如需 OpenCode Zen 反代聚合（可选）：
cd opencode-zen-docker
#    编辑 docker-compose.yml，修改代理出口地址
#    确保每台机器装了 opencode 二进制
docker compose up -d

# 5. 在 New-API 管理界面（http://<host>:3000）添加渠道，指向 dispatcher 端口
```

> **注意**: lane 数量不固定。你可以按实际线路数量增减 docker-compose.yml 中的 lane 定义。最少 1 个 lane 即可工作。每条 lane 需要一个独立的出口代理（用于 IP 轮换），如果不需要 IP 轮换，可以所有 lane 共用同一个代理。

## 历史修复记录

- **2026-08-15**: 修复 dispatcher.py 的 `min(..., 4096)` 请求体截断 bug（导致大请求 JSON 损坏，返回 400 invalid json）和 `Retry-After` 变量名 NameError

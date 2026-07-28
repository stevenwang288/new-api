# 961 部署说明

## 目标

在 `192.168.9.61` 运行带 dispatcher 状态观测功能的 New API。New API 使用 `3000` 端口，dispatcher 使用 `4010` 端口并管理 12 个 lane（`4011` 至 `4022`）。

## 已验证版本

- New API 镜像：`new-api-961:lane-observability`
- 容器：`new-api-961`
- 数据目录：`/opt/new-api-961/data`
- Compose 文件：`/opt/new-api-961/docker-compose.yml`
- dispatcher 状态：`http://127.0.0.1:4010/status`

## 功能

- `/quota-status`：显示当前用户额度和轮询参与状态。
- `/dispatcher-status`：管理员查看 dispatcher 总体状态及 12 个 lane。
- 渠道编辑器高级设置：显示请求数、成功数、错误数、暂停原因和恢复倒计时。
- 状态面板每 5 秒刷新一次。
- 浏览器只请求 New API，dispatcher 地址由后端代理，不暴露给浏览器。

## 发布流程

1. 在 Linux amd64 环境构建后端：

   ```bash
   GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o new-api-linux .
   ```

2. 构建前端：

   ```bash
   cd web
   bun run typecheck
   bun run build
   ```

3. 使用 `Dockerfile.runtime`，以现有 `calciumion/new-api:latest` 为运行时基础，覆盖 `/new-api` 和 `/web/dist`。
4. 将镜像导入 961，更新 `/opt/new-api-961/docker-compose.yml` 的 `image`，然后执行：

   ```bash
   docker compose config --quiet
   docker compose up -d --force-recreate new-api-961
   ```

5. 保留 `/opt/new-api-961/data`、容器名、`3000:3000` 端口和 `unless-stopped` 重启策略。

## 验收

```bash
curl -i http://127.0.0.1:3000/
curl -s http://127.0.0.1:4010/status
docker ps --filter name=new-api-961
docker compose config --quiet
```

管理员登录后应能看到 12 个 lane；当前已验证 `status: ok`、`11/12` 就绪，且一个 lane 正确显示配额耗尽和恢复倒计时。

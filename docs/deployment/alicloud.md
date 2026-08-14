# 阿里云与本地边缘部署

## 拓扑

阿里云 VPC 部署 cloud、experiment、report、TimescaleDB、Redis、Mosquitto、Web 和 Prometheus；本地部署 SUMO-GUI、独立 rsu-service、edge 和 vehicle-agent。云边只开放 MQTT TLS，管理 API 经 HTTPS 反向代理。

两套拓扑都有可校验的 Compose 文件：

```bash
# 阿里云侧
docker compose --env-file .env -f deployment/compose/alicloud-cloud.yml config
docker compose --env-file .env -f deployment/compose/alicloud-cloud.yml up -d

# 本地边缘侧
docker compose --env-file .env -f deployment/compose/local-edge.yml config
docker compose --env-file .env -f deployment/compose/local-edge.yml up -d
```

需要现场 SUMO-GUI 时在本地主机安装 SUMO，并设置
`TRAFFIC_MESSAGE_BUS=mqtt`、`MQTT_HOST`、`MQTT_PORT=8883`、
`MQTT_TLS_ENABLED=true` 和证书路径后执行 `make demo-gui`。CLI 会把真实
TraCI 状态先进入本地 RSU 角色，再通过远端 MQTT 到达边缘和云端，而不是退回内存消息总线。

## 环境变量

复制 `.env.example` 为不提交版本的 `.env`，至少替换 PostgreSQL、MQTT 和 JWT 口令。服务器地址、端口、Token 和证书路径均由环境变量注入，代码不含阿里云 IP 或 AccessKey。

MQTT 客户端实际读取 `MQTT_CA_CERT`、`MQTT_CLIENT_CERT`、
`MQTT_CLIENT_KEY` 和 `MQTT_TLS_INSECURE`；生产环境必须保持
`MQTT_TLS_INSECURE=false`。

## 端口与防火墙

| 端口 | 范围 | 用途 |
|---|---|---|
| 443 | 公网/受控源 | Web 与 REST/WebSocket |
| 8883 | 仅边缘固定出口 IP | MQTT TLS |
| 5432 | VPC 内部 | TimescaleDB/PostgreSQL 协议 |
| 6379 | VPC 内部 | Redis |
| 9090 | 运维 VPN/堡垒机 | Prometheus |

开发 Compose 的 1883、5173 和 9090 均绑定 `127.0.0.1`，不能直接复制为公网配置。

Compose 中 `TRAFFIC_MESSAGE_BUS=mqtt`，实验闭环通过 Mosquitto 交换 `RegionalState`、`CloudStrategy` 和 `ExecutionFeedback`。只有离线故障演示才在单次实验中切换到确定性通信仿真器；系统状态接口会分别显示 `connected_transport` 或 `communication_emulator`。

## MQTT 安全

生成 `deployment/mosquitto/passwords` 和 CA/服务端证书，挂载 `mosquitto.cloud.conf`。禁止 `allow_anonymous true` 暴露公网；启用客户端账号分权和主题 ACL。

## 卷、重启与备份

TimescaleDB、Redis、Mosquitto 和 Prometheus 使用命名卷。数据库镜像固定为 `timescale/timescaledb:2.29.1-pg17`，迁移创建 metrics/events/vehicle_trajectories 三个 hypertable 及压缩、保留策略。服务为 `unless-stopped`，应用捕获关闭信号并停止实验、释放 TraCI 和刷新缓冲。数据库每日 `pg_dump`，结果目录对象存储版本化；恢复演练至少每季度一次。

本地 SUMO 端口不暴露公网。云端恢复时边缘先进入 `RECOVERY_SYNC`，不立即强制切相。

本文只说明可部署拓扑。由于当前没有用户授权的真实阿里云主机、域名、证书和公网安全组，本阶段仅完成配置校验与本机 Compose 验收，不宣称已完成真实公网安全验收。

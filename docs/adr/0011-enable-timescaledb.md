# ADR 0011：启用 TimescaleDB

状态：接受（2026-08-06）

## 决策

PostgreSQL 服务固定使用 `timescale/timescaledb:2.29.1-pg17`。Alembic 迁移以幂等方式启用扩展，把 metrics、events 和 vehicle_trajectories 转换为 hypertable，并配置压缩和数据保留策略。

## 结果与恢复

迁移前生成可校验 `pg_dump`；应用仍使用 PostgreSQL 协议和 SQLAlchemy，不把高频车辆逐条同步写库。扩展不可用时 readiness 明确报告状态，而不是静默声称已经启用。

# ATI V0.1 运行手册

## 安全约束

API Key 只通过进程环境变量 `FUYAO_API_KEY` 注入。不要写入 `.env`、YAML、数据库、原始响应、命令参数或日志。轮换密钥后再执行网络任务。

```bash
cd /root/workspace/ati-design
export FUYAO_API_KEY="$ROTATED_FUYAO_API_KEY"
```

## 初始化和验收

```bash
python3 -m ati migrate
python3 scripts/check_data_sources.py --json
python3 -m ati foundation
python3 -m ati quality
```

`foundation` 会分页保存代码表、拉取交易日历和全市场快照。`quality` 必须确认快照时效和代码表覆盖，否则不能发布有效候选。

## 日线和板块数据

```bash
python3 -m ati history --codes 600000.SH,000001.SZ --start 2025-01-01 --end 2026-11-12
python3 -m ati index-catalog --kind industry
python3 -m ati index-members --index-ids <INDEX_ID>
python3 -m ati index-snapshot --index-ids <INDEX_ID>
python3 -m ati index-history --index-ids <INDEX_ID> --start 2025-01-01 --end 2026-11-12
python3 -m ati limit-stats --trade-date 2026-11-12
python3 -m ati l1
```

日线接口按每批最多 10 只代码请求；重复命令按任务业务键跳过，修订数据应使用新范围或新版本键。

## 调度和评价

```bash
scripts/run_ati_scheduled.sh
python3 -m ati evaluate --as-of 2026-11-12 --cost-bps 30
python3 -m ati report
```

调度只在交易日产生五个配置时点的信号。`BLOCKED`、`NO_CANDIDATE` 和 `VALID` 分开保存；不使用上一轮快照冒充当前数据。

## 影子源

影子源默认关闭。完成授权、限流和字段核验后才允许在隔离环境中启用：

```bash
export EASTMONEY_SHADOW_ENABLED=true
python3 -m ati shadow --secids 1.600519
```

影子数据只写 `shadow_observation` 和 `source_batch`，不能直接进入正式因子或候选排序。

## 备份与恢复演练

```bash
python3 -m ati backup --path data/backups/ati-$(date +%Y%m%dT%H%M%S).db
python3 -m ati quality
python3 -m ati restore --from data/backups/ati-<timestamp>.db --to /tmp/ati-restore.db
python3 -m ati quality
```

恢复时使用备份副本配置独立 `ATI_DATABASE_URL`，先执行 `migrate` 和 `quality`，再恢复调度；不要覆盖正在写入的生产数据库。`restore` 默认拒绝覆盖已有目标，只有明确传 `--force` 才替换。

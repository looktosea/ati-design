# ATI V0.1 上线实测准备清单

本文区分“程序能启动”和“数据足以安全发布候选”。API Key 永远不写入文档、`.env`、YAML、SQLite、原始响应路径、命令参数或日志。

## 当前实测状态

最近一次真实验收已经完成：

- 代码表：5,580 条，分页 6 页；
- 全市场快照：5,580 条，代码表与快照覆盖率 100%；
- 行业目录：320 个；样例行业成员：59 只；
- 样例指数历史：450 行；
- 样例个股日线：10 只、4,500 行；
- 五个发布时点调度：均能保存信号，重跑按业务键跳过；
- 当前质量状态：`BLOCKED/DAILY_HISTORY_COVERAGE_LOW`，日线覆盖约 0.18%。

因此当前系统可以上线做数据积累和质量观察，不能把当前样例历史当作全市场正式候选依据。

## A. VPS 和运行时条件

上线前确认：

- Linux VPS，Python 3.11 或更高版本；
- 系统时区或运行时可用 `Asia/Shanghai`；
- NTP/chrony 已同步，系统时间误差可接受；
- 能解析并通过 HTTPS 访问 `fuyao.aicubes.cn`；
- 运行用户对项目目录、`data/`、备份目录有读写权限；
- 原始响应和 SQLite 有足够磁盘空间，并有磁盘使用率告警；
- 进程不会被 OOM killer 终止；
- cron、systemd timer 或等效调度器可每分钟触发一次锁保护脚本；
- 不运行任何券商、下单或账户管理服务。

建议把项目目录、SQLite 数据库、原始响应和备份目录分开规划；备份不能与正在写入的数据库使用同一个临时文件。

## B. 安全和密钥条件

1. 在 Fuyao 控制台撤销此前已经暴露的密钥并创建轮换密钥。
2. 使用 VPS 的 secret manager、systemd `EnvironmentFile`（权限 600）或受控 shell 环境注入：

```bash
export FUYAO_API_KEY="$ROTATED_FUYAO_API_KEY"
```

3. 用 `env | grep`、日志、进程参数和备份扫描确认密钥没有出现在文件或命令行中；不要把密钥直接粘贴到聊天、工单或 shell history。
4. 确认 Fuyao 账号有代码表、全市场快照、历史日线、指数/板块、涨停统计所需权限，并确认限频和数据使用范围。
5. 东方财富影子源默认关闭；只有完成授权、字段口径和限流核验后才设置 `EASTMONEY_SHADOW_ENABLED=true`。

## C. 初始化顺序

在项目目录执行：

```bash
python3 -m ati migrate
python3 scripts/check_data_sources.py --json
python3 -m ati foundation
python3 -m ati quality
```

必须看到：

- `foundation.data_status=VALID`；
- `snapshot_ids_missing_from_universe=0`；
- 质量报告没有 `UNIVERSE_SNAPSHOT_MISMATCH`；
- 快照时效在 15 分钟门槛内。

然后导入历史数据。当前外部股票历史接口按单只代码请求，程序每批最多提交 10 只，批内保留单只原始响应：

```bash
python3 -m ati history \
  --codes 600000.SH,000001.SZ \
  --start 2025-01-01 \
  --end 2026-11-12
```

上线实测前至少完成一组 10 只样本，确认：

- 日线行数约等于有效交易日数；
- `trade_date` 为 `YYYY-MM-DD`；
- OHLC、成交量、成交额单位正确且无整体空值；
- 每只证券的历史批次可追溯；
- 重跑相同业务键不会重复写入。

正式候选前，需要把历史覆盖扩展到批准的研究池。当前质量门控要求日线覆盖率至少 90%；覆盖不足时只允许积累数据和生成诊断，不允许发布有效候选。

## D. 板块和市场上下文

至少导入一个正式采用的行业分类版本：

```bash
python3 -m ati index-catalog --kind industry
python3 -m ati index-members --index-ids <INDUSTRY_INDEX_ID>
python3 -m ati index-snapshot --index-ids <INDUSTRY_INDEX_ID>
python3 -m ati index-history \
  --index-ids <INDUSTRY_INDEX_ID> \
  --start 2025-01-01 \
  --end 2026-11-12
python3 -m ati limit-stats --trade-date 2026-11-12
python3 -m ati l1
```

当前成员是实时成员快照，历史成员回放限制会写入因子解释；不能把今天的成员静默当成多年历史成员。

涨停统计接口当前提供涨停、触及涨停和打开等字段；如果跌停数量没有独立可靠来源，M06 保持不完整，不把缺失转换成零。

## E. 调度上线

使用带锁脚本，避免同一 VPS 并发运行：

```bash
scripts/run_ati_scheduled.sh
```

建议用 systemd timer 或 cron 每分钟触发。调度进程必须继承 secret manager 注入的环境变量；不要让 cron 直接读取项目 `.env`：

```ini
# /etc/systemd/system/ati-schedule.service
[Service]
WorkingDirectory=/root/workspace/ati-design
EnvironmentFile=/etc/ati/ati-runtime.env
ExecStart=/root/workspace/ati-design/scripts/run_ati_scheduled.sh
```

`/etc/ati/ati-runtime.env` 只由运行用户读取（权限 600），放在项目目录之外；其中的 `FUYAO_API_KEY` 仍不进入仓库、日志或命令参数。timer 每分钟触发该 service。

每个交易日应产生 14:30、14:35、14:40、14:45、14:50 五个业务键。重试结果必须是 `SKIPPED`，不能创建第二份信号。非交易日、快照过期、覆盖不足时，结果应为 `BLOCKED` 或 `NO_CANDIDATE`，不能沿用上一轮数据。

## F. 评价和复盘

```bash
python3 -m ati evaluate --as-of YYYY-MM-DD --cost-bps 30
python3 -m ati report
```

1、3、5 日终点按交易日历推进；没有参考价、终点价或公司行为资料时保留 `ENTRY_UNCERTAIN`、`DATA_UNRESOLVED` 等状态，不顺延冒充同一终点。

## G. 质量门控和上线判定

```bash
python3 -m ati quality
```

正式发布前至少满足：

- `status=VALID`；
- 最新快照时效合格；
- 最新代码表与快照覆盖 100%；
- 日线覆盖达到批准阈值；
- 无重复因子键；
- 必需 ST 状态、行业成员、市场统计和因子来源批次完整；
- 调度任务没有未处理 `FAILED`；
- 影子数据没有进入正式候选；
- 无任何自动交易委托。

`NO_CANDIDATE` 表示数据可用但没有通过规则的证券；`BLOCKED` 表示数据不足或不安全。两者必须在监控和报告中分开统计。

## H. 备份、恢复和实测记录

```bash
python3 -m ati backup --path data/backups/ati-$(date +%Y%m%dT%H%M%S).db
python3 -m ati restore \
  --from data/backups/ati-<timestamp>.db \
  --to /tmp/ati-restore.db
ATI_DATABASE_URL=sqlite:////tmp/ati-restore.db python3 -m ati quality
```

每次上线实测记录：时间、代码表数量、快照数量、日线覆盖率、行业/涨停输入、质量结果、信号数量、失败任务和备份路径。原始响应目录必须与数据库备份一起保留，否则无法完整复现来源批次。

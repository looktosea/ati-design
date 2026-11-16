# ATI 审核与客户工作台设计

## 结论

ATI 已形成 Fuyao → 原始批次 → SQLite → 因子 → 信号 → 评价的闭环，依赖少、离线 Demo 可运行，且密钥未写入日志或配置回显。现有测试 12 项全部通过。

当前更适合作为“研究数据底座”，尚不适合直接把信号当作实时交易依据。审核脚本 `python3 scripts/audit_regressions.py` 会在临时数据库中复现下列问题；脚本退出 0 表示所有问题都被复现，不表示系统无 bug。

## 已复现问题

| 编号 | 严重度 | 位置 | 问题与影响 | 精简/修复方法 |
|---|---|---|---|---|
| B01 | 高 | `ati/l1.py:42` | 读取某证券全部日线，没有按 `trade_date < decision_cutoff` 截断。未来数据会泄漏进 MA、ATR、突破和评价。 | SQL 增加截止条件；统一 `as_of` 过滤函数，并为未来行写回归测试。 |
| B02 | 高 | `ati/l1.py:25-32,77` | `run_l1(decision_cutoff=14:30)` 仍选择数据库最大快照（例如 14:50），信号时间与行情时间不一致。 | 查询 `event_time <= cutoff`；没有可用快照时返回 `BLOCKED / NO_SNAPSHOT_AT_CUTOFF`。 |
| B03 | 高 | `ati/l1.py:50` | 板块成员只取全库最大 `valid_from`，可能使用信号日之后的成员快照。 | 取 `max(valid_from) <= cutoff`，同时记录 membership snapshot 时间。 |
| B04 | 中 | `ati/pipeline.py:94-102` | 索引快照任务的幂等键只有 index IDs，第一次成功后永远 `SKIPPED`，无法采集新的时点。 | 业务键加入按分钟截断的快照时点；同一分钟幂等，下一分钟允许新快照。 |
| B05 | 中 | `ati/db/store.py:insert_signal` 与 `signal_candidate` 主键 | `INSERT OR IGNORE` 会让同一 signal 的重算候选静默保留旧行；若改策略后复用 signal id，报告可能混合。 | 信号内容不可变：重算产生新 strategy/registry 版本；或事务内删除并完整替换候选。 |
| B06 | 高 | `ati/quality/report.py:16` | 覆盖率分母使用报价集合。只要报价都在股票池，1/10 的股票池报价也会显示 100%。 | 分母使用股票池集合；同时显示 `quote_universe_coverage` 和报价数量。UI 已按股票池重算展示。 |
| B07 | 高 | `ati/factors.py:132-135` | `I02` 的 `transformed_value` 是字典，排序只累加数字，因此趋势分改变不会影响总分。 | 明确每个因子的标量 score；字典只放 raw/explanation；所有 ACTIVE 因子加入策略权重配置。 |
| B08 | 中 | `ati/db/store.py:21-25` | `job_id = job-{idempotency_key[:48]}` 截断键可能碰撞，不同任务可能共享 job id。 | job id 使用完整 SHA-256 摘要；数据库继续以完整 `idempotency_key` 唯一约束。 |
| B09 | 中 | `ati/config.py`、`ati/l1.py:93-95`、`ati/evaluation.py:13-16` | 配置中的 `primary_horizon`/`aux_horizons` 没有贯穿 pending 与评价，代码固定为 1/3/5。 | CLI、调度器和评价入口统一传入 horizons；兼容 `.env.example` 的配置名。 |
| B10 | 中 | `ati/scheduler.py:13-16` | 定时任务只运行“今天已到”的截点；若 14:30 任务宕机，15:30 恢复时会补跑全部，但没有“迟到采集”标记和告警。 | 增加 cutoff 的 `MISSED/LATE` 状态、最大回补窗口和告警；不要把迟到行情伪装成准时信号。 |

另外，`ati/factors.py:169-173` 已明确说明板块历史成员回放未确认；上线前应让 UI 持续显示此限制。`M02/M04/M05/M07` 等注册为 shadow/unavailable 的因子不应在前端伪装成已验证特征。

## 精简建议

1. **先统一时间语义**：抽出 `DataSlice(as_of, cutoff, source_batches)`，所有行情、日线、成员、涨跌停查询都接收它。这样能同时消除 B01、B02、B03，也减少重复 SQL。
2. **把因子输出分成两层**：`FactorValue` 只保存标量 `score`、validity、coverage；`raw/explanation` 保存 JSON。排序只读取 `score`，避免 B07。
3. **把任务导入统一成模板**：请求、原始响应、质量门控、批次写入、幂等、完成状态由一个 runner 处理；当前 index/history/limit 函数的大量 try/finish 代码可以合并。
4. **把策略参数版本化**：`StrategyPolicy` 同时存 horizons、权重、候选上限和 required factors；不要从 `Settings` 与代码常量各取一份。
5. **把 SQLite 写入放进事务**：一个 signal 的 factors、candidate、rejection、evaluation 初始化应作为同一提交单元，异常时完整回滚。
6. **保留 CLI 作为自动化入口**：客户不需要记忆命令；UI 只读本地库，不从浏览器触发采集或交易，降低误操作。

## 客户 UI

新增命令：

```bash
# 合成数据体验，不读取 data/ati.db，不调用 API
python3 -m ati ui --demo

# 查看本地数据库，只读；默认 http://127.0.0.1:8765
python3 -m ati ui
```

工作台包含：

- **尾盘候选**：信号状态、候选数、行情时间、候选卡片、入选因子引用、风险标签。
- **信号复盘**：1/3/5 交易日切换，区分已评价、等待终点、缺数据和参考价不确定；缺失值不当作 0。
- **数据健康**：股票池报价覆盖、最新行情年龄、失败/阻断任务、检查原因和表记录数。
- **使用指南**：说明数据状态、分数边界、人工交易边界和导出方式。
- **报告导出**：浏览器下载当前信号 JSON；UI 不写数据库、不采集行情、不连接券商。

UI 的 HTTP 服务仅绑定 `127.0.0.1`，使用只读 SQLite 连接、禁止写请求、禁用外部脚本，并对 Host 做本机校验。演示模式与生产库使用临时隔离数据库。

## 验证结果

```text
python3 -m unittest discover -s tests -v  # 14 passed
python3 -m py_compile ati/*.py          # passed
python3 scripts/audit_regressions.py    # B01-B10 correctness checks passed
python3 -m ati demo                     # VALID, 5 candidates, 15 evaluations
```

截至 2026-11-16，B01-B10 已修复：行情、日线和板块成员按决策截点截断，快照无可用时阻断；覆盖率以股票池为分母；I02 输出标量得分；任务键使用 SHA-256；索引快照按分钟时点幂等；信号重算会完整替换候选及其旧评价；评价 horizon 可从配置贯通到 CLI、调度器和评价入口。调度恢复时记录 `ON_TIME/LATE/MISSED` 与迟到秒数，超过 `ATI_MAX_BACKFILL_MINUTES`（默认 30 分钟）直接标记 MISSED，不生成信号；窗口内补跑明确标记 LATE。

回归验证：`python3 -m unittest discover -s tests -v`（14 项通过）、`python3 -m py_compile ati/*.py`、`python3 scripts/audit_regressions.py`（10 项正确行为检查通过）。索引快照的剩余注意点是：默认快照时点按本地 UTC 分钟生成；若供应商提供稳定的源数据时间戳，生产环境应优先通过 `--at` 显式传入该时点。

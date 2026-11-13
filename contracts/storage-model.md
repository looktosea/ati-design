# ATI 存储模型草案 V0.1

目标：支持数据来源追踪、因子复算、候选快照不可变、3 日评价和策略审批。字段名采用 `snake_case`，时间统一带时区；金额为 CNY 元，成交量为股。

## 1. 设计原则

- 原始批次和发布快照只追加，不覆盖；修订数据产生新版本。
- 所有研究结果绑定 `source_batch_id`、`factor_registry_version` 和 `strategy_version`。
- 数据缺失使用状态字段和 `NULL`，不把缺失转换成 0。
- 外部源区分 `fuyao`、`eastmoney_shadow` 和以后新增的供应商；不同口径不静默拼接。
- 任务按自然业务键幂等，重复运行不重复产生因子、发布或评价记录。

## 2. 核心实体

| 实体 | 主键/唯一键 | 用途 |
|---|---|---|
| `source_batch` | `batch_id` | 保存来源、请求、获取时间、时间范围、版本、覆盖和错误 |
| `security_master_snapshot` | `(security_id, valid_from, snapshot_version)` | 股票身份、交易所、名称、上市日、ST 状态及有效区间 |
| `trading_calendar` | `trade_date` | 交易日和交易阶段，供 1/3/5 日推进 |
| `daily_bar` | `(security_id, trade_date, price_version)` | 原始/标准化日线、成交额、成交量和公司行为版本 |
| `intraday_bar` | `(security_id, event_time, source_batch_id)` | 分钟行情；Fuyao/东财影子数据分开保留 |
| `index_master` | `index_id` | 指数、行业、概念目录及分类 |
| `index_membership_snapshot` | `(index_id, security_id, valid_from, snapshot_version)` | 成分和有效区间，避免用今天成员回算历史 |
| `event_record` | `event_id` | 新闻、异动和政策事件原文、发布时间、获取时间、映射版本 |
| `factor_value` | `(factor_id, factor_version, security_id, decision_cutoff)` | 因子原值、变换值、有效性、原因和来源批次 |
| `market_state_snapshot` | `(trade_date, decision_cutoff, state_version)` | 市场环境状态及其输入因子 |
| `strategy_version` | `strategy_version` | 规则、阈值、因子依赖、状态和确认记录 |
| `signal_snapshot` | `signal_id` | 每个发布时点的完整结果、数据状态和策略版本 |
| `signal_candidate` | `(signal_id, security_id)` | 候选、排名、策略触发、证据、风险和因子引用 |
| `signal_evaluation` | `(signal_id, evaluation_policy_version)` | 1/3/5 日参考价、收益、状态和缺失边界 |
| `strategy_proposal` | `proposal_id` | 新旧策略比较、样本、失败结果、审批和生效时间 |
| `job_run` | `job_run_id` | 调度、重试、耗时、覆盖率、错误和幂等键 |

## 3. 关键字段约束

### `source_batch`

```text
batch_id              text primary key
source_name           text not null
endpoint              text not null
requested_at          timestamptz not null
source_available_at   timestamptz null
source_timestamp      timestamptz null
received_at           timestamptz not null
request_id            text null
source_version        text null
coverage_json         jsonb not null
status                text not null  -- SUCCESS/PARTIAL/FAILED/STALE
raw_uri               text not null
content_sha256        text not null
```

### `factor_value`

```text
factor_id              text not null       -- M01..R07
factor_version         text not null
security_id            text null            -- 市场级因子可为空
decision_cutoff        timestamptz not null
raw_value_json         jsonb null
transformed_value_json jsonb null
validity               text not null
missing_reason         text null
coverage               numeric null
data_asof              timestamptz null
source_batch_ids       text[] not null
explanation            text null
```

`validity=VALID` 才能进入已批准的正式规则；`SHADOW` 是因子注册表的策略状态，不能只靠数据库字段推导，计算结果仍要保存。

### `signal_snapshot`

```text
signal_id               text primary key
trade_date              date not null
decision_cutoff         timestamptz not null
published_at            timestamptz not null
strategy_version        text not null
factor_registry_version text not null
data_status             text not null       -- VALID/DEGRADED/BLOCKED/NO_CANDIDATE
data_status_reason      text null
market_asof             timestamptz null
source_batch_ids        text[] not null
created_at              timestamptz not null
```

唯一性建议：`(trade_date, decision_cutoff, strategy_version, factor_registry_version)`。同一键重复运行更新任务状态，不生成第二份有效发布。

### `signal_evaluation`

```text
signal_id                  text not null
evaluation_policy_version  text not null
horizon_days               integer not null  -- 1/3/5
reference_price            numeric null
reference_time             timestamptz null
status                     text not null      -- PENDING/EVALUATED/ENTRY_UNCERTAIN/EXIT_CONSTRAINED/DATA_UNRESOLVED
gross_return               numeric null
net_reference_return       numeric null
max_adverse_move           numeric null
endpoint_trade_date        date null
unresolved_reason          text null
```

同一信号的 1、3、5 日结果分别记录；3 日是主要评价，不由 1/5 日结果覆盖。评价策略版本固定参考延迟、成本、复权和公司行为处理。

## 4. 原始数据和隐私

原始 API 响应存对象存储或受控文件目录，数据库保存 `raw_uri` 和校验和。API Key 不进入 `raw_uri`、请求 URL、错误消息、结构化日志或数据库。请求头由 HTTP 客户端注入，日志只保存 endpoint、状态、request_id 和耗时。

初始保留策略：原始批次和信号快照长期保留；分钟影子数据按磁盘容量和研究需要分层压缩；删除策略必须先确认不影响已发布信号的复现。

## 5. 首轮数据库实现范围

首轮只需实现：`source_batch`、`security_master_snapshot`、`trading_calendar`、`daily_bar`、`factor_value`、`strategy_version`、`signal_snapshot`、`signal_candidate`、`job_run`。分钟影子、事件、评价和提案表可以先建表或保留迁移草案，但接口必须预留版本字段。

不要在第一版把所有 40 个因子拆成 40 张表；因子定义进入注册表，计算结果使用统一 `factor_value`，便于版本比较和新增因子。

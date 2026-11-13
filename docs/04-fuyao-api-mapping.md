# Fuyao API 映射与能力评估 V0.1

核验日期：2026-11-11（Asia/Shanghai）。

本文把用户提供的 Fuyao API 文档与只读请求结果映射到 ATI 因子。密钥已用于本地核验，但没有写入仓库、文档、日志或示例；实际运行应通过环境变量注入。本文不保存任何 API Key。

## 1. 核验结果

接口统一使用 `X-api-key` 请求头和 `ApiResponse` 信封；文档说明时间戳为毫秒 Unix 时间，时区按 Asia/Shanghai。实际只读核验返回 `code=0` 的成功响应。

在核验时：

- A 股代码表返回 5,581 条当前记录，其中 SH 2,319、SZ 2,905、BJ 357。这个数量随上市、退市和接口状态变化，不能写死。
- 全市场行情快照使用 `limit=10000&offset=0` 一次返回 5,581 条，响应约 3.24 秒；这是一次观测，不是 SLA。返回 `timestamp`、价格、涨跌幅、当日高低、成交量和成交额，但不返回名称，名称需与代码表关联。
- 历史日线批量请求成功；单次最多 10 个代码，周期为 `1d`，历史单只接口窗口最长 10 年。
- 指数/板块成分反查、指数行情快照、个股分时新闻、小时热股榜、小时热度飙升榜、涨停统计和当日个股异动原因接口均成功返回结构化结果。

以上验证只证明当前账号和接口能够返回样例数据，不代表每个历史区间、每个交易板块或每个字段在所有日期都有覆盖。

## 2. 端点与 ATI 数据域

| ATI 数据域 | Fuyao 端点 | 状态 | 可支持的工作 | 关键限制 |
|---|---|---|---|---|
| 股票池/名称 | `/api/meta/tickers/list?asset_type=a-share` | 可调用 | 当前 A 股代码、名称、交易所、上市日期 | 没有独立 ST 状态和历史状态字段；名称包含 ST 只能作当前过滤候选，不能代替历史状态表 |
| 当前全市场行情 | `/api/a-share/prices/snapshot` | 可调用，已核验 | M01、M03 的当前部分，I06/I07 的当前快照，流动性和覆盖检查 | 依赖 `timestamp`；无盘口、涨跌停价、明确交易状态；全市场单次请求约 3 秒的观测值 |
| 个股历史行情 | `/api/a-share/prices/historical` | 可调用 | I01–I04、R01、R04 的日线基础 | 仅支持 `1d`；单只查询，窗口最长 10 年 |
| 批量历史行情 | `/api/a-share/prices/historical-batch` | 可调用 | 小批量回测与候选复盘 | 每次最多 10 只，不能直接作为 5,581 只全量历史仓库 |
| 全市场日 K 导出 | `/api/dump/market-dumps/daily-k/download-url` | 文档列出，需登录态 Cookie | 适合全量历史初始化 | 文档描述为 Cookie 下载短时预签名链接，不应假设 API Key 可直接调用；需单独核验权限和自动化方式 |
| 复权事件 | `/api/a-share/corporate-actions/adjustment-factors` | 可调用 | 评价、公司行为和价格可比 | 单次一个标的；事件类型需根据字段推导；也可使用历史行情的 forward/backward |
| 交易日历 | `/api/a-share/calendar/trading-days` | 可调用 | D+1/D+3/D+5、历史窗口 | 单次最多 10 个自然年；以实际返回为准 |
| 行业/概念目录与成员 | `/api/a-share-index/catalog/ths-index-list`、`/constituents/ths-stock-list`、`/constituents/ths-index-list-by-stock` | 可调用，已核验反查 | S01–S06、I01 的行业归属 | 成分接口当前返回的是当前清单；历史成员是否可回放需另核验 |
| 指数/板块行情 | `/api/a-share-index/prices/snapshot`、`/prices/historical` | 可调用 | M、S 的市场和板块背景 | 指数历史文档限制近 5 年且仅 `1d`；概念/行业历史覆盖需逐项核验 |
| 涨跌停/炸板 | `/api/a-share/special-data/limit-up-pool`、`limit-down-pool`、`limit-break-pool`、`limit-up-statistics` | 可调用，文档列出 | M06、情绪诊断和风险说明 | 规则字段和盘中时点需核验；不能仅凭股票池证明当前可成交 |
| 热度/热股 | `/api/a-share/special-data/hot-stock-list`、`skyrocket-list`、历史榜与排名趋势 | 可调用，已核验小时榜 | M01/M06 的情绪代理、解释标签、候选辅助 | 热度为数据源指标，不等同于上涨概率或资金流向；历史可用范围要按接口返回核验 |
| 个股异动原因 | `/api/a-share/special-data/anomaly-analysis-list`、`...-stock` | 可调用，已核验列表 | P 的事件线索、R07 风险提示 | “原因”属于数据源解读，仍需保留原字段、时间和来源，不直接当作政策因子正向加分 |
| 个股分时新闻 | `/api/news/stock/timeline-list` | 可调用，已核验 | P01/P05/P07 的新闻时间线、候选解释 | 主要是个股新闻；政策主题、行业映射和历史去重仍需自己建设 |
| 资金流向 | `/api/a-share/capital-flow/...` | **文档列出但暂未开放外部接入** | 当前不能作为正式 F03–F06 输入 | 只能保留适配接口；不能用文档示例或同花顺客户端能力冒充外部可调用数据 |
| 高频动向 | `/api/a-share/high-frequency/...` | **文档列出但暂未开放外部接入** | 当前不能支撑历史分钟尾盘因子 | 文档注明近 30 个交易日和 1 分钟能力，但端外接口不可用 |
| 结构化资讯事件库 | `/api/news/events/search` | **文档列出但暂未开放外部接入** | 当前不能作为正式 P01–P07 历史事件因子 | 个股新闻可用不等于政策事件库可用 |
| 市场成交额预测 | `/api/a-share/special-data/turnover-prediction-snapshot` | **面向同花顺 AI 客户端** | 当前不纳入 M02 正式输入 | 文档明确不是端外开放接口 |

文档中的“可调用”指端点有外部 REST 契约且本次样例请求成功，不表示已完成数据质量和历史回放验证。

## 3. 当前可实现程度

### 3.1 可以先做的部分

- 当前非 ST 候选池的初步构造：从代码表读取名称和交易所，保留当前名称过滤结果，并把 ST 状态标记为“待独立核验”。
- 全市场当前快照筛选：价格、涨跌幅、日内高低、成交量、成交额、当前 VWAP 代理 `turnover / volume`。
- 日线技术因子：I01、I02、I03、I04、R01、R04，以及基于当前快照的部分 I06、I07。
- 当前市场和板块背景：指数/行业/概念快照、成员反查、热股/飙升榜、涨跌停和异动统计。
- 新闻时间线提示：个股新闻可以进入“事件线索”卡片，但不自动生成政策影响结论。
- 3 日信号评价的日线终点和公司行为处理：历史日线、交易日历、复权事件足够时可实现；尾盘参考入场价格仍需盘中数据或明确降级规则。

### 3.2 不能直接宣称已经支持的部分

- **14:30–14:50 的历史尾盘复盘**：当前外部价格接口只有日线；高频模块文档虽有 1 分钟契约，但标注暂未开放外部接入。没有历史分钟快照，就不能严格回放过去 14:45 看到的排名。
- **尾盘 15 分钟相对强弱、尾盘增量资金和同刻历史量比**：需要分钟价格/成交或等价的历史时点快照。当前不把 F02、F05、I05 变成可用因子。
- **正式主力资金因子**：资金接口未开放外部接入，F03–F06 只能处于待接入状态。热度榜或涨跌停榜不能替代主力资金净额。
- **历史 ST 排除**：当前代码表没有历史风险警示状态。只按今天名称过滤，会造成历史样本偏差；需要用户 API 补充，或建立有时间版本的状态源。
- **历史板块轮动的严格回放**：当前成员反查/成分接口是否提供历史有效区间尚未确认。用今天的成分回算过去会产生成员偏差。
- **可成交性与盘口风险**：当前快照没有盘口五档和明确交易状态，无法准确判断排队、封板或滑点。

## 4. 因子启用分层（按当前 API）

| 层级 | 初始因子/标签 | 当前状态 |
|---|---|---|
| L0 安全与数据 | R02、R05、R06 的可用字段部分，代码/交易所/时间戳检查 | 可做，但交易状态、涨跌停价格仍需补字段 |
| L1 日线基础 | I01、I02、I03、I04、R01、R04 | 可做，先限定为日线研究和当前快照筛选 |
| L1 市场/板块 | M01、M03、M06、S01、S02、S05 的日线/当前部分 | 可做，历史成员和历史指数口径需核验 |
| L1 情绪辅助 | 热股榜、飙升榜、涨停/跌停/炸板、个股异动原因 | 可做为解释和诊断，暂不把热度当胜率 |
| L1 事件观察 | P01、P05、P07 的个股新闻线索 | 可做观察卡片；政策映射先人工确认 |
| L2 资金增强 | F03–F06 | Fuyao 外部接口不可用；东方财富端点可进入影子模式，需先完成口径和稳定性验证 |
| L2 尾盘微观结构 | M02、M04、M05 的同刻版本，F01、F02、F05、I05 的分钟版本 | 东方财富可补当前及约 5 日分钟数据；多年历史仍不可回放 |
| L2 事件增强 | P02–P04、P06 的结构化历史版本 | 等待外部事件库、原文时间和映射版本 |

在 L2 数据未具备前，系统可以做“当前快照 + 日线基础”的候选研究，但界面必须标注：**尾盘因子未完整覆盖、资金因子未启用、政策因子为观察标签**。

## 5. 适配器和缓存设计

不让业务因子直接调用 Fuyao URL。建议建立以下供应商无关接口：

```text
UniverseProvider.current_a_shares()
QuoteProvider.market_snapshot(as_of)
PriceProvider.daily_history(ids, start, end, adjust)
CalendarProvider.trading_days(start, end)
CorporateActionProvider.events(ids, start, end)
IndexProvider.catalog(kind)
IndexProvider.members(index_id, as_of=None)
IndexProvider.snapshot(index_ids, as_of)
SpecialDataProvider.heat(as_of, period)
SpecialDataProvider.limit_stats(trade_date)
NewsProvider.stock_timeline(id, cursor)
CapitalFlowProvider.intraday(id, start, end)       # Fuyao UNAVAILABLE; Eastmoney SHADOW
IntradayProvider.bars(id, start, end)              # Fuyao UNAVAILABLE; Eastmoney SHADOW
EventProvider.events(start, end, filters)           # 当前返回 UNAVAILABLE
```

每个返回值都附带 `source_name=fuyao`、`source_request_id`、`requested_at`、`source_timestamp`、`source_version`、`coverage` 和 `availability_status`。业务层只接受标准字段，不把缺失转换为 0。

缓存和任务建议：

- 代码表、指数目录和成员清单按有效时间缓存，变更生成新快照。
- 每次尾盘运行先取全市场快照并保存原始批次；不要按候选名单事后补取，避免选择偏差。
- 当前全市场快照一次 5,581 条约 3 秒的观测值，可作为 14:30–14:50 的时间预算参考；连续刷新必须限速、重试退避、记录 429，不盲目并发。
- 历史日线优先使用可验证的全量导出或本地仓库；逐只每次最多 10 个批量请求只作为补齐和候选复核。
- 热度榜、异动和新闻只保存原始响应及获取时间；同一事件不因多个榜单重复加分。

## 6. 东方财富补充源的边界

当前 Fuyao 外部能力缺少分钟行情、资金流和结构化政策事件时，可以评估东方财富公开行情接口或其授权数据接口作为独立适配器。已对两个公开 JSON 端点做过小规模只读核验：

- `https://push2.eastmoney.com/api/qt/stock/trends2/get`：对 `1.600519` 返回当日 1 分钟序列；使用 `push2his.eastmoney.com` 和 `ndays=5` 的请求返回了最近 5 个交易日的分钟点。
- `https://push2.eastmoney.com/api/qt/stock/fflow/kline/get`：对 `1.600519` 返回盘中资金流序列；`https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` 返回了日级资金流序列。

这证明了“可以研究补充源”，不证明接口是稳定、授权或永久可用的生产契约。东方财富数据先进入 `SHADOW`，至少完成字段含义、时间延迟、缺失、限流、跨市场代码和连续重复请求测试后，再决定是否进入正式因子。

暂不把网页抓取直接写进核心因子，原因是：

- 页面展示字段不等于稳定 API 契约，可能有延迟、登录要求、字段改名或反爬限制。
- 公开页面与研究使用授权、传播和商业限制需要单独核验；不能因为网页可打开就默认允许长期自动采集。
- 东方财富与 Fuyao 的资金流定义、复权口径、时间戳和板块分类可能不同；使用前必须建立字段映射和交叉核对，不可静默拼接。
- 若只有当前实时数据而没有历史同刻存档，仍不能严格回放过去尾盘信号；从接入日开始保存快照，先做前向验证。

补充源优先级建议：先补分钟价格与累计成交，再补同口径资金方向，最后补历史可回放的政策事件。东方财富历史分钟核验范围约为最近 5 个交易日，不能替代多年尾盘回测；从接入日开始保存快照，前向积累更长样本。任何补充源都保持 `source_name` 和策略版本隔离，先以影子模式运行。

## 7. 补充源适配器草案

```text
EastmoneyIntradayProvider.trends(security_id, start, end)
EastmoneyCapitalFlowProvider.intraday(security_id, start, end)
EastmoneyCapitalFlowProvider.daily(security_id, start, end)
```

Fuyao 的 `thscode` 转东方财富 `secid` 时，初始映射为 SH=`1.<ticker>`、SZ/BJ=`0.<ticker>`；映射结果需用代码表和少量样本核对，不能对所有市场代码无条件套用。东财返回的逗号字符串、字段编号和金额单位在适配器中转换，并保留完整原始行。

建议先覆盖：当前 14:30–14:50 的分钟价格、分钟累计量和盘中资金流；不先覆盖全市场逐只每分钟轮询。对全市场，可先用 Fuyao 一次性快照筛到轻量候选，再对候选和所属板块/指数补取分钟数据；若市场环境因子需要全市场分钟宽度，则要单独评估请求量和限流。

## 8. 当前结论

Fuyao API 足以支撑 ATI 的基础骨架、全市场当前快照、日线候选研究、板块/热度/异动解释以及日线终点评价；配合东方财富公开端点，可以从接入日起补齐当前尾盘分钟和部分资金流观察，但**仍不足以独立完成多年历史的 14:30–14:50 尾盘因子回测**。因此下一阶段在用户确认前，不应把 F 资金因子、分钟尾盘因子或结构化政策因子写成“已验证”。

接入 API 后的第一项工作应是能力自检：实际历史覆盖、字段时间语义、ST 历史状态、板块历史成员、全市场日 K 初始化方式和补充源授权。自检通过后，再决定哪些因子从 `UNAVAILABLE` 转为 `SHADOW` 或 `ACTIVE`。

## 9. 官方文档入口

- [Fuyao API 文档索引](https://fuyao.aicubes.cn/llms.txt)
- [股票行情数据](https://fuyao.aicubes.cn/docs/api-reference/prices/)
- [全市场数据导出](https://fuyao.aicubes.cn/docs/api-reference/market-dumps/)
- [指数与板块数据](https://fuyao.aicubes.cn/docs/api-reference/a-share-index/)
- [主力资金（文档列出但暂未开放外部接入）](https://fuyao.aicubes.cn/docs/api-reference/capital-flow/)
- [高频动向（文档列出但暂未开放外部接入）](https://fuyao.aicubes.cn/docs/api-reference/high-frequency/)
- [资讯事件库（文档列出但暂未开放外部接入）](https://fuyao.aicubes.cn/docs/api-reference/news-events/)
- [热度榜与热股](https://fuyao.aicubes.cn/docs/api-reference/hot-list-data/)
- [涨跌停与炸板](https://fuyao.aicubes.cn/docs/api-reference/limit-up-data/)
- [个股分时新闻](https://fuyao.aicubes.cn/docs/api-reference/news-stock-timeline/)
- [东方财富公开行情分时端点](https://push2.eastmoney.com/api/qt/stock/trends2/get)
- [东方财富公开资金流端点](https://push2.eastmoney.com/api/qt/stock/fflow/kline/get)

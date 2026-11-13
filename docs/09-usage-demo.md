# ATI 使用效果 Demo

这是一个合成数据演示，不读取生产数据库、不调用 Fuyao、不需要 API Key。它展示系统的真实输出结构和状态流转，不代表策略收益或真实胜率。

## 运行

```bash
cd /root/workspace/ati-design
python3 -m ati demo
```

示例输出：

```json
{
  "database": "temporary_demo_only",
  "signal_status": "VALID",
  "candidate_count": 5,
  "candidates": [
    {"security_id": "600000.SH", "rank": 1, "score": 1.75, "evidence": ["I01 valid", "I02 valid", "I03 valid", "I04 valid", "I06 valid"]},
    {"security_id": "600001.SH", "rank": 2, "score": 1.74, "evidence": ["I01 valid", "I02 valid", "I03 valid", "I04 valid", "I06 valid"]}
  ],
  "rejection_count": 35,
  "evaluation": {"as_of_date": "2026-11-19", "updated": 15, "cost_bps": 30},
  "evaluated_count": 15,
  "factor_count": 445
}
```

实际完整输出会列出 5 只候选；这里展示前两只以便阅读。

## 使用人如何理解

1. **数据状态**：`VALID` 表示演示数据满足门控；真实环境如果快照过期、ST 状态未知或日线覆盖不足，会得到 `BLOCKED` 或 `NO_CANDIDATE`。
2. **候选卡片**：每只候选有证券代码、排名、分数和主要证据。证据来自 I01 行业相对强度、I02 趋势结构、I03 回调恢复、I04 突破、I06 VWAP 关系。
3. **未入选原因**：演示中 40 只证券只选前 5 只，其余 35 只记录为 `RANK_LIMIT`；如果缺历史或 ST 状态未知，会记录对应原因。
4. **评价**：每只候选生成 1/3/5 日评价。Demo 在评价终点齐全后产生 15 条 `EVALUATED` 记录；真实环境缺行情时会保留 `PENDING` 或 `DATA_UNRESOLVED`。
5. **人工交易边界**：Demo 只生成研究信号，不连接券商、不下单，也不把分数解释为收益保证。

真实运行时使用：

```bash
python3 -m ati report
```

它会展示当前信号、候选、未入选原因、评价和因子样本。上线条件和质量状态见 [生产实测准备清单](08-production-readiness.md)。

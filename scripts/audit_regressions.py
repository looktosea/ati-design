"""Verify the audited regressions against a temporary database; never contact providers."""
from pathlib import Path
import json
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ati.adapters.fuyao import RawBatch
from ati.config import load_settings
from ati.db.store import Store
from ati.factors import compute_daily_factors, rank_candidates
from ati.l1 import run_l1
from ati.pipeline import snapshot_job_key
from ati.quality.gate import evaluate_snapshot
from ati.quality.report import build_report
from ati.scheduler import due_cutoffs


def main():
    findings = []
    def record(code, reproduced, evidence):
        findings.append(dict(id=code, reproduced=bool(reproduced), evidence=evidence))
    with tempfile.TemporaryDirectory(prefix='ati-audit-') as tmp:
        s = Store('sqlite:///' + str(Path(tmp) / 'audit.db'))
        try:
            s.migrate(ROOT / 'migrations')
            now = datetime(2026, 11, 12, 6, 50, tzinfo=timezone.utc)
            s.insert_source_batch(RawBatch('audit', 'synthetic', '/test', None, now, now,
                                          'SUCCESS', 'audit', 'synthetic://audit', 1, now))
            sid = '600000.SH'
            history = [dict(trade_date=(date(2026, 8, 1)+timedelta(days=i)).isoformat(),
                            close=10+i*.05, high=11+i*.05, low=9+i*.05, open=10+i*.05)
                       for i in range(70)]
            q = dict(security_id=sid, last_price=14, prev_close=13, low=13, high=15,
                     volume_shares=100, turnover_cny=1300, is_st=False)
            before = compute_daily_factors(sid, history, q, now.isoformat())[0]
            after = compute_daily_factors(sid, history + [dict(trade_date='2026-11-13',
                        close=1000, high=1001, low=999, open=1000)], q, now.isoformat())[0]
            record('B01', before['raw_value'] == after['raw_value'],
                   dict(before_asof=before['data_asof'], after_asof=after['data_asof'], cutoff=now.isoformat()))
            s.insert_calendar_rows([{'date':'2026-11-12','is_trading_day':1}], 'audit')
            s.insert_security_rows([{'thscode':sid,'name':'TEST'}], 'audit', 'v1', '2026-11-12T00:00:00+00:00')
            s.insert_snapshot_rows([q], 'audit', '2026-11-12T14:50:00+08:00')
            result = run_l1(s, trade_date='2026-11-12', decision_cutoff='2026-11-12T14:30:00+08:00')
            market_asof = result['signal'].get('market_asof')
            record('B02', market_asof is None or market_asof <= result['signal']['decision_cutoff'], result['signal'])
            s.insert_index_members('A', [{'thscode':sid}], 'audit', valid_from='2026-11-12T00:00:00+00:00')
            s.insert_index_members('B', [{'thscode':sid}], 'audit', valid_from='2026-11-12T00:01:00+00:00')
            with patch('ati.l1.compute_sector_factors', return_value=[]) as capture:
                run_l1(s, trade_date='2026-11-12', decision_cutoff=now.isoformat())
            used = list(capture.call_args.args[2])
            record('B03', used == ['A','B'], dict(imported=['A','B'], used=used))
            settings = load_settings({})
            key = snapshot_job_key(['IDX'], datetime(2026, 11, 12, 6, 50, tzinfo=timezone.utc))
            job, _ = s.begin_job('index_snapshot', key)
            s.finish_job(job, 'SUCCESS')
            same_key = snapshot_job_key(['IDX'], datetime(2026, 11, 12, 6, 50, 30, tzinfo=timezone.utc))
            next_key = snapshot_job_key(['IDX'], datetime(2026, 11, 12, 6, 51, tzinfo=timezone.utc))
            same_job, same_run = s.begin_job('index_snapshot', same_key)
            next_job, next_run = s.begin_job('index_snapshot', next_key)
            record('B04', same_job == job and not same_run and next_run and next_job != job,
                   {'same_minute_idempotent': not same_run, 'next_minute_new_job': next_run})
            signal = dict(signal_id='immutable-test', trade_date='2026-11-12', decision_cutoff='cutoff-test',
                          published_at=now.isoformat(), strategy_version='test', factor_registry_version='test', data_status='VALID')
            s.insert_signal(signal, [dict(security_id='A', rank=1, score=1, eligibility_status='ELIGIBLE')])
            s.insert_signal(signal, [dict(security_id='B', rank=1, score=2, eligibility_status='ELIGIBLE')])
            count = s.conn.execute("select count(*) from signal_candidate where signal_id='immutable-test'").fetchone()[0]
            record('B05', count == 1, dict(candidate_count_after_replacement=count))
            for n in range(1, 10):
                s.insert_security_rows([{'thscode':f'{600000+n}.SH','name':'TEST'}], 'audit', 'v1', '2026-11-12T00:00:00+00:00')
            quality = build_report(s, now=now)
            gate = evaluate_snapshot([q], source_timestamp=None, received_at=now)
            record('B06', quality['universe_coverage'] == 0.1,
                   dict(actual_quote_fraction='1/10', reported=quality['universe_coverage'], missing_timestamp_gate=gate.status))
            fs = [dict(factor_id=fid, factor_version='v', security_id=sid, validity='VALID', transformed_value=value)
                  for fid, value in [('I01',.1),('I02',100.0),('I03',1),('I04',.2),('I06',.3)]]
            score1 = rank_candidates(fs, [q])[0]['score']
            fs[1]['transformed_value'] = -100.0
            score2 = rank_candidates(fs, [q])[0]['score']
            record('B07', score1 != score2, dict(trend_scores=[100,-100], rank_scores=[score1,score2]))
            first, _ = s.begin_job('daily_history', 'x'*48+'A')
            second, _ = s.begin_job('daily_history', 'x'*48+'B')
            record('B08', first != second, dict(distinct_keys_same_job=first != second))
            def broken_dates(store, signal_id):
                return [row[0] for row in store.conn.execute('select horizon_days from signal_evaluation where signal_id=?', (signal_id,))]
            custom_result = run_l1(s, trade_date='2026-11-12', decision_cutoff=now.isoformat(), horizons=(2,4))
            custom_horizons = broken_dates(s, custom_result['signal']['signal_id'])
            record('B09', custom_horizons == [2,4],
                   dict(configurable_horizons='explicit run policy', actual=custom_horizons))
            from ati.scheduler import cutoff_timing
            cutoff = datetime(2026,11,12,14,30,tzinfo=settings.timezone)
            timing = [cutoff_timing(cutoff, cutoff, 30)[0], cutoff_timing(cutoff, cutoff + timedelta(minutes=10), 30)[0], cutoff_timing(cutoff, cutoff + timedelta(minutes=31), 30)[0]]
            record('B10', timing == ['ON_TIME','LATE','MISSED'], dict(timing=timing))
        finally:
            s.close()
    print(json.dumps(findings, ensure_ascii=False, indent=2))
    return 0 if all(item['reproduced'] for item in findings) else 1

if __name__ == '__main__':
    raise SystemExit(main())

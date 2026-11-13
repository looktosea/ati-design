import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from ati.adapters.fuyao import RawBatch
from ati.db.store import Store
from ati.evaluation import advance_evaluations
from ati.l1 import run_l1

class EndToEndTests(unittest.TestCase):
    def test_valid_candidates_rejections_and_evaluation(self):
        s=Store('sqlite:///'+tempfile.mktemp(suffix='.db')); s.migrate('migrations')
        now=datetime(2026,11,11,6,50,tzinfo=timezone.utc)
        s.insert_source_batch(RawBatch('e2e','fuyao','/test',None,now,now,'SUCCESS','e2e','/tmp/e2e',40,now))
        s.insert_calendar_rows([{'date':d,'is_trading_day':1} for d in ('2026-11-11','2026-11-12','2026-11-13','2026-11-16','2026-11-17','2026-11-18')],'e2e')
        quotes=[]; members=[]
        for i in range(40):
            sid=f'{600000+i:06d}.SH'; members.append({'thscode':sid})
            quotes.append({'thscode':sid,'last_price':15+i*.01,'prev_price':14.5+i*.01,'open_price':14.8+i*.01,'high_price':15.2+i*.01,'low_price':14.8+i*.01,'volume':100000,'turnover':1500000,'name':'TEST','is_st':False})
            s.insert_daily_rows([{'thscode':sid,'date':(date(2026,8,1)+timedelta(days=j)).isoformat(),'open':10+j*.05,'high':10+j*.05+.2,'low':10+j*.05-.2,'close':10+j*.05,'prev_close':10+j*.05-.05} for j in range(70)],'e2e')
        s.insert_security_rows([{'thscode':q['thscode'],'name':'TEST'} for q in quotes],'e2e','master-v1',valid_from='2026-11-11T00:00:00+00:00')
        s.insert_snapshot_rows(quotes,'e2e','2026-11-11T06:50:00+00:00')
        s.insert_index_catalog([{'thscode':'IDX.TEST','name':'TEST'}],'e2e',valid_from='2026-11-11T00:00:00+00:00')
        s.insert_index_members('IDX.TEST',members,'e2e',valid_from='2026-11-11T00:00:00+00:00')
        s.insert_limit_stats('2026-11-11',{'up_count':100,'down_count':20,'eligible_count':500},'e2e','2026-11-11T06:50:00+00:00')
        result=run_l1(s,trade_date='2026-11-11',decision_cutoff='2026-11-11T06:50:00+00:00')
        self.assertEqual(result['signal']['data_status'],'VALID'); self.assertEqual(len(result['candidates']),5); self.assertEqual(result['rejections'],35)
        for candidate in result['candidates']:
            for j,d in enumerate(('2026-11-12','2026-11-13','2026-11-16','2026-11-17','2026-11-18')):
                s.insert_daily_rows([{'thscode':candidate['security_id'],'date':d,'open':16,'high':17,'low':15,'close':16+j*.1}],'e2e')
        advance_evaluations(s,as_of_date='2026-11-18')
        self.assertEqual(s.conn.execute("select count(*) from signal_candidate_evaluation where status='EVALUATED'").fetchone()[0],15)
        s.close()

    def test_cli_demo_contract(self):
        from ati.demo import run_demo
        result=run_demo()
        self.assertEqual(result['signal_status'],'VALID'); self.assertEqual(result['candidate_count'],5); self.assertEqual(result['rejection_count'],35); self.assertEqual(result['evaluated_count'],15)

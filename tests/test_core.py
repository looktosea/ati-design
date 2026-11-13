import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from ati.adapters.fuyao import parse_response
from ati.config import load_settings
from ati.db.store import Store
from ati.factors import compute_daily_factors, compute_limit_factor, compute_sector_factors, rank_candidates
from ati.quality.gate import evaluate_snapshot
from ati.quality.report import build_report

MIGRATIONS='migrations'

class CoreTests(unittest.TestCase):
    def store(self):
        path=tempfile.mktemp(suffix='.db'); s=Store('sqlite:///'+path); s.migrate(MIGRATIONS); return s
    def test_secret_redaction(self):
        s=load_settings({'FUYAO_API_KEY':'unit-secret'})
        self.assertNotIn('unit-secret',repr(s)); self.assertNotIn('unit-secret',json.dumps(s.public()))
    def test_envelope_and_quality(self):
        e=parse_response({'code':0,'message':'ok','request_id':'r','data':{'timestamp':1760000000000,'item':[]}})
        self.assertEqual(e.request_id,'r'); self.assertEqual(e.code,0)
        self.assertEqual(evaluate_snapshot([{'security_id':'a'},{'security_id':'a'}]).status,'BLOCKED')
    def test_l1_factor_and_rank(self):
        rows=[]
        for i in range(70):
            d=date(2026,1,1)+timedelta(days=i); c=10+i*.05
            rows.append({'trade_date':d.isoformat(),'open':c-.1,'high':c+.2,'low':c-.2,'close':c,'prev_close':c-.05})
        q={'security_id':'600000.SH','last_price':14,'prev_close':13.8,'high':14.1,'low':13.7,'volume_shares':100000,'turnover_cny':1400000,'is_st':False}
        f=compute_daily_factors(q['security_id'],rows,q,'2026-03-20T06:00:00+00:00',['b'])
        self.assertTrue(all(x['validity']=='VALID' for x in f if x['factor_id'] in {'I02','I03','I04','I06','I07','R01','R04'}))
        f.append({'factor_id':'I01','factor_version':'0.1.0','security_id':'600000.SH','decision_cutoff':'2026-03-20T06:00:00+00:00','validity':'VALID','transformed_value':0.1})
        self.assertEqual(rank_candidates(f,[q])[0]['security_id'],'600000.SH')
    def test_sector_and_limit_contract(self):
        quotes=[{'security_id':f's{i}','last_price':20,'prev_close':19} for i in range(40)]
        histories={}
        for i in range(40):
            histories[f's{i}']=[{'trade_date':(date(2026,1,1)+timedelta(days=d)).isoformat(),'open':10,'high':11,'low':9,'close':10+d*.1,'prev_close':10+(d-.1)*.1} for d in range(10)]
        fs=compute_sector_factors(quotes,histories,{'idx':{f's{i}' for i in range(40)}},{},'2026-01-20T00:00:00+00:00')
        self.assertEqual(len(fs),160); self.assertTrue(all(f['validity']=='VALID' for f in fs))
        self.assertEqual(compute_limit_factor({'up_count':5,'down_count':2,'eligible_count':100},'2026-01-20T00:00:00+00:00')['validity'],'VALID')
    def test_migration_and_quality(self):
        s=self.store(); s.migrate(MIGRATIONS); self.assertEqual(s.conn.execute('select count(*) from schema_migration').fetchone()[0],7)
        self.assertEqual(build_report(s)['status'],'BLOCKED'); s.close()

if __name__=='__main__': unittest.main()

class AdapterContractTests(unittest.TestCase):
    def test_official_history_parameter_shapes(self):
        from urllib.parse import parse_qs, urlparse
        from ati.adapters.fuyao import FuyaoClient
        calls=[]
        class Response:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return json.dumps({'code':0,'message':'ok','data':{'thscode':'600000.SH','timestamp':1760000000000,'item':[]}}).encode()
        def opener(req,timeout):
            calls.append(urlparse(req.full_url)); return Response()
        settings=load_settings({'FUYAO_API_KEY':'unit-secret','ATI_RAW_DATA_DIR':tempfile.mkdtemp()})
        client=FuyaoClient(settings,opener=opener); client.daily_history('600000.SH','2026-01-01','2026-01-02'); client.index_daily_history('000001.SH','2026-01-01','2026-01-02'); client.limit_statistics('2026-01-02')
        stock=parse_qs(calls[0].query); index=parse_qs(calls[1].query); limit=parse_qs(calls[2].query)
        self.assertEqual(stock['interval'],['1d']); self.assertIn('start',stock); self.assertNotIn('start_date',stock)
        self.assertEqual(index['interval'],['1d']); self.assertNotIn('adjust',index)
        self.assertEqual(limit['date'],['2026-01-02'])

    def test_market_snapshot_pagination(self):
        from ati.adapters.fuyao import ApiEnvelope, RawBatch
        from datetime import datetime, timezone
        settings=load_settings({'FUYAO_API_KEY':'unit-secret','ATI_RAW_DATA_DIR':tempfile.mkdtemp()})
        from ati.adapters.fuyao import FuyaoClient
        client=FuyaoClient(settings)
        now=datetime.now(timezone.utc); calls=[]
        def fake(limit,offset):
            calls.append(offset); rows=[{'thscode':f'{offset+i:06d}.SH'} for i in range(2 if offset==0 else 1)]
            data={'item':rows,'total':3}; env=ApiEnvelope(0,'ok',data,None,now,now,{'code':0,'data':data}); batch=RawBatch(str(offset),'fuyao','/snapshot',None,now,now,'SUCCESS',str(offset),'/tmp/x',len(rows),now); return env,batch
        client.market_snapshot=fake
        pages=client.market_snapshot_all(page_size=2)
        self.assertEqual(calls,[0,2]); self.assertEqual(sum(len(x[0].data['item']) for x in pages),3)

    def test_history_auth_failure_is_recorded(self):
        from ati.pipeline import import_daily_history
        s=Store('sqlite:///'+tempfile.mktemp(suffix='.db')); s.migrate(MIGRATIONS)
        settings=load_settings({'FUYAO_API_KEY':'','ATI_RAW_DATA_DIR':tempfile.mkdtemp()})
        with self.assertRaises(RuntimeError):
            import_daily_history(settings,s,['600000.SH'],'2026-01-01','2026-01-02')
        row=s.conn.execute("select status,error_code from job_run where job_name='daily_history'").fetchone()
        self.assertEqual(tuple(row),('FAILED','FuyaoAuthError')); self.assertEqual(s.conn.execute('select count(*) from daily_bar').fetchone()[0],0)
        s.close()

class RegistryTests(unittest.TestCase):
    def test_registry_version_and_statuses(self):
        from ati.registry import load_registry
        r=load_registry('config/factor_registry.yaml')
        self.assertEqual(r.version,'0.1.0'); self.assertEqual(r.status('M01'),'ACTIVE'); self.assertEqual(r.status('F03'),'SHADOW')

    def test_st_status_gate(self):
        from ati.factors import build_rejections
        rejected=build_rejections([],['600000.SH','000001.SZ'],quotes=[{'security_id':'600000.SH','is_st':1},{'security_id':'000001.SZ','is_st':None}])
        self.assertEqual([x['reason_code'] for x in rejected],['ST_EXCLUDED','ST_STATUS_UNKNOWN'])

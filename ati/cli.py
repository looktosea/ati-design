from __future__ import annotations
import argparse, json, os, sys
from .config import ConfigError, load_settings
from .db.store import Store

def main(argv=None):
    p=argparse.ArgumentParser(prog="ati"); sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("migrate"); sub.add_parser("foundation"); sub.add_parser("l1"); sub.add_parser("demo")
    hp = sub.add_parser("history"); hp.add_argument("--codes", required=True, help="comma-separated thscode values; max 10 per request")
    hp.add_argument("--start"); hp.add_argument("--end")
    ip = sub.add_parser("index-catalog"); ip.add_argument("--kind", default="industry")
    mp = sub.add_parser("index-members"); mp.add_argument("--index-ids", required=True)
    sp = sub.add_parser("index-snapshot"); sp.add_argument("--index-ids", required=True)
    ih = sub.add_parser("index-history"); ih.add_argument("--index-ids", required=True); ih.add_argument("--start"); ih.add_argument("--end")
    lp = sub.add_parser("limit-stats"); lp.add_argument("--trade-date")
    sp = sub.add_parser("schedule"); sp.add_argument("--at", dest="at", help="ISO timestamp; default current time")
    ep = sub.add_parser("evaluate"); ep.add_argument("--as-of", dest="as_of") ; ep.add_argument("--cost-bps", type=float, default=30)
    rp = sub.add_parser("report"); rp.add_argument("--signal-id")
    sh = sub.add_parser("shadow"); sh.add_argument("--secids", required=True)
    sub.add_parser("quality")
    bp = sub.add_parser("backup"); bp.add_argument("--path", required=True)
    rp2 = sub.add_parser("restore"); rp2.add_argument("--from", dest="source", required=True); rp2.add_argument("--to", dest="target", required=True); rp2.add_argument("--force", action="store_true")
    args=p.parse_args(argv)
    try:
        settings=load_settings(); store=Store(settings.database_url)
        if args.command == "migrate": store.migrate(); print(json.dumps({"status":"ok","database":settings.database_url}))
        elif args.command == "demo":
            from .demo import run_demo
            print(json.dumps(run_demo(),ensure_ascii=False))
        elif args.command == "foundation":
            from .pipeline import run_foundation
            result=run_foundation(settings,store); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "l1":
            from .l1 import run_l1
            from .registry import load_registry
            store.migrate(); registry=load_registry(); result=run_l1(store,max_candidates=settings.max_candidates,registry_version=registry.version); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "history":
            from .pipeline import import_daily_history
            result=import_daily_history(settings,store,args.codes.split(","),args.start,args.end); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "index-catalog":
            from .pipeline import import_index_catalog
            result=import_index_catalog(settings,store,args.kind); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "index-members":
            from .pipeline import import_index_members
            result=import_index_members(settings,store,args.index_ids.split(",")); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "index-snapshot":
            from .pipeline import import_index_snapshots
            result=import_index_snapshots(settings,store,args.index_ids.split(",")); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "index-history":
            from .pipeline import import_index_history
            result=import_index_history(settings,store,args.index_ids.split(","),args.start,args.end); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "limit-stats":
            from .pipeline import import_limit_statistics
            result=import_limit_statistics(settings,store,args.trade_date); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "schedule":
            from .scheduler import run_due
            at = __import__("datetime").datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else None
            result=run_due(settings,store,at); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "evaluate":
            from .evaluation import advance_evaluations
            result=advance_evaluations(store,as_of_date=args.as_of,cost_bps=args.cost_bps); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "report":
            from .report import signal_report
            result=signal_report(store,args.signal_id); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "shadow":
            from .pipeline import collect_shadow
            result=collect_shadow(settings,store,args.secids.split(",")); print(json.dumps(result,ensure_ascii=False))
        elif args.command == "quality":
            from .quality.report import build_report
            result=build_report(store); print(json.dumps(result,ensure_ascii=False)); return 0 if result["status"]=="VALID" else 3
        elif args.command == "backup":
            import sqlite3
            from pathlib import Path
            Path(args.path).parent.mkdir(parents=True, exist_ok=True)
            target=sqlite3.connect(args.path); store.conn.backup(target); target.close(); print(json.dumps({"status":"SUCCESS","path":args.path},ensure_ascii=False))
        else:
            import sqlite3
            from pathlib import Path
            target_path=Path(args.target)
            if target_path.exists() and not args.force: raise ValueError("restore target exists; use --force only for an explicit replacement")
            target_path.parent.mkdir(parents=True,exist_ok=True)
            source=sqlite3.connect(args.source); target=sqlite3.connect(args.target); source.backup(target); target.close(); source.close(); print(json.dumps({"status":"SUCCESS","source":args.source,"target":args.target},ensure_ascii=False))
        return 0
    except (ConfigError, RuntimeError, ValueError) as exc:
        print(f"ATI error: {exc}", file=sys.stderr); return 2
    finally:
        try: store.close()
        except UnboundLocalError: pass
if __name__ == "__main__": raise SystemExit(main())

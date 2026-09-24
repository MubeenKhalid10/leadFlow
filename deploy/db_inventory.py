"""Read-only inventory of a LeadFlow PostgreSQL database (migration verification).

Usage:  python deploy/db_inventory.py <label> <out.json>

The connection comes from the normal LeadFlow settings (.streamlit/secrets.toml
or the PG_HOST / PG_PORT / PG_DATABASE / PG_USER / PG_PASSWORD / PGSSLMODE
environment variables). The session is READ ONLY, so the server rejects any
write. Records per table: row count, min/max id, size, a fingerprint of every
column of every row, distinct emails, columns, indexes and constraints.
No credentials are printed; sample emails are masked.

Run it once against the source and once against the target, then compare with
deploy/compare_inventory.py.
"""
import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root / image /app
import psycopg2  # noqa: E402
import db  # noqa: E402

TABLES = [
    "master_lists", "master_contacts",
    "bounce_lists", "bounce_emails",
    "mql_lists", "mql_emails",
    "unsub_lists", "unsub_emails",
    "upload_history",
]

label = sys.argv[1] if len(sys.argv) > 1 else "db"
out_path = sys.argv[2] if len(sys.argv) > 2 else None

cfg = db.get_config()
host = cfg["host"]
host_kind = ("supabase-pooler" if "pooler.supabase" in host else
             "supabase" if "supabase" in host else
             "rds" if "rds.amazonaws.com" in host else host)
conn = psycopg2.connect(**db._conn_kwargs())
conn.set_session(readonly=True, autocommit=False)
cur = conn.cursor()
cur.execute("SET TIME ZONE 'UTC'")
cur.execute("SET statement_timeout = '600s'")

res = {"label": label, "host_kind": host_kind, "port": cfg["port"], "dbname": cfg["dbname"],
       "sslmode": cfg["sslmode"], "tls": conn.info.ssl_in_use}
cur.execute("SHOW server_version"); res["server_version"] = cur.fetchone()[0]
cur.execute("SELECT pg_database_size(current_database()), pg_size_pretty(pg_database_size(current_database()))")
res["db_bytes"], res["db_pretty"] = cur.fetchone()

cur.execute("""SELECT table_name FROM information_schema.tables
               WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1""")
res["public_tables"] = [r[0] for r in cur.fetchall()]

tables = {}
for t in TABLES:
    if t not in res["public_tables"]:
        tables[t] = None
        continue
    info = {}
    t0 = time.time()
    cur.execute(f"SELECT COUNT(*), MIN(id), MAX(id) FROM public.{t}")
    info["rows"], info["min_id"], info["max_id"] = cur.fetchone()
    info["count_seconds"] = round(time.time() - t0, 2)
    cur.execute(f"SELECT pg_total_relation_size('public.{t}'), pg_relation_size('public.{t}')")
    info["total_bytes"], info["heap_bytes"] = cur.fetchone()
    # Order-independent content fingerprint of every column of every row.
    t0 = time.time()
    cur.execute(f"SELECT COALESCE(SUM(hashtextextended(x::text, 0)::numeric), 0)::text FROM public.{t} x")
    info["fingerprint"] = cur.fetchone()[0]
    info["fingerprint_seconds"] = round(time.time() - t0, 2)
    if t in ("master_contacts", "bounce_emails", "mql_emails", "unsub_emails"):
        cur.execute(f"SELECT COUNT(DISTINCT email) FROM public.{t}")
        info["distinct_emails"] = cur.fetchone()[0]
    cur.execute("""SELECT column_name, data_type, is_nullable, COALESCE(column_default,'')
                   FROM information_schema.columns WHERE table_schema='public' AND table_name=%s
                   ORDER BY ordinal_position""", (t,))
    info["columns"] = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=%s ORDER BY 1", (t,))
    info["indexes"] = [list(r) for r in cur.fetchall()]
    cur.execute("""SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
                   WHERE conrelid = %s::regclass ORDER BY 1""", (f"public.{t}",))
    info["constraints"] = [list(r) for r in cur.fetchall()]
    tables[t] = info
res["tables"] = tables

# Representative records (first/last by id) — emails masked for the report.
samples = {}
for t in ("master_contacts", "mql_emails"):
    if tables.get(t) and tables[t]["rows"]:
        cur.execute(f"SELECT id, list_id, email FROM public.{t} WHERE id IN (%s, %s) ORDER BY id",
                    (tables[t]["min_id"], tables[t]["max_id"]))
        samples[t] = [[r[0], r[1], (r[2][:2] + "***@" + r[2].split("@")[-1]) if r[2] and "@" in r[2] else "?"]
                      for r in cur.fetchall()]
res["samples"] = samples

cur.execute("SELECT category, COUNT(*) FROM public.upload_history GROUP BY 1 ORDER BY 1")
res["upload_history_by_category"] = dict(cur.fetchall())

conn.rollback()
conn.close()

if out_path:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)

print(f"[{label}] {host_kind}:{res['port']}/{res['dbname']}  PostgreSQL {res['server_version']}  "
      f"TLS={res['tls']}  size={res['db_pretty']}")
print(f"public tables: {', '.join(res['public_tables'])}")
for t, i in tables.items():
    if i is None:
        print(f"  {t:16s} MISSING")
        continue
    extra = f" distinct={i['distinct_emails']:,}" if "distinct_emails" in i else ""
    print(f"  {t:16s} rows={i['rows']:>10,}{extra}  ids={i['min_id']}..{i['max_id']}  "
          f"size={i['total_bytes']/1048576:7.1f} MB  idx={len(i['indexes'])} cons={len(i['constraints'])}  "
          f"count={i['count_seconds']}s")
print("upload_history by category:", res["upload_history_by_category"])

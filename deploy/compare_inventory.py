"""Compare two db_inventory.py outputs (source vs target). Exit code 1 on any mismatch.

Usage:  python deploy/compare_inventory.py source.json target.json
"""
import json
import sys

src = json.load(open(sys.argv[1], encoding="utf-8"))
dst = json.load(open(sys.argv[2], encoding="utf-8"))
print(f"SOURCE {src['label']}: PostgreSQL {src['server_version']} size={src['db_pretty']}")
print(f"TARGET {dst['label']}: PostgreSQL {dst['server_version']} size={dst['db_pretty']}")

bad = 0
fields = ["rows", "min_id", "max_id", "fingerprint", "distinct_emails"]
print(f"{'table':16s} {'src rows':>10s} {'dst rows':>10s}  ids  fingerprint distinct cols idx cons  result")
for t, s in src["tables"].items():
    d = dst["tables"].get(t)
    if s is None or d is None:
        print(f"{t:16s} MISSING on {'source' if s is None else 'target'}")
        bad += 1
        continue
    ok_rows = s["rows"] == d["rows"]
    ok_ids = (s["min_id"], s["max_id"]) == (d["min_id"], d["max_id"])
    ok_fp = s["fingerprint"] == d["fingerprint"]
    ok_dist = s.get("distinct_emails") == d.get("distinct_emails")
    ok_cols = s["columns"] == d["columns"]
    # index/constraint definitions (names + definitions) must match exactly
    ok_idx = sorted(map(tuple, s["indexes"])) == sorted(map(tuple, d["indexes"]))
    ok_con = sorted(map(tuple, s["constraints"])) == sorted(map(tuple, d["constraints"]))
    ok = all([ok_rows, ok_ids, ok_fp, ok_dist, ok_cols, ok_idx, ok_con])
    bad += not ok
    f = lambda b: "ok " if b else "BAD"
    print(f"{t:16s} {s['rows']:>10,} {d['rows']:>10,}  {f(ok_ids)}  {f(ok_fp)}         {f(ok_dist)}      "
          f"{f(ok_cols)} {f(ok_idx)} {f(ok_con)}  {'PASS' if ok else 'FAIL'}")
    if not ok_cols:
        print("   columns src:", s["columns"]); print("   columns dst:", d["columns"])
    if not ok_idx:
        print("   idx src:", s["indexes"]); print("   idx dst:", d["indexes"])
    if not ok_con:
        print("   con src:", s["constraints"]); print("   con dst:", d["constraints"])
ok_samples = src["samples"] == dst["samples"]
ok_hist = src["upload_history_by_category"] == dst["upload_history_by_category"]
print("representative first/last records match:", ok_samples)
print("upload_history by category match:", ok_hist, src["upload_history_by_category"])
bad += (not ok_samples) + (not ok_hist)
print("OVERALL:", "PASS" if bad == 0 else f"FAIL ({bad} problem(s))")
sys.exit(1 if bad else 0)

"""Download Backup: per-category CSVs and the all-categories ZIP hold exactly the tables' columns and
every row; exact record counts in the file names; batching across a large table in bounded memory;
error handling (no file left behind); the download route; and the Database page controls."""

import csv
import datetime as dt
import io
import os
import re
import time
import tracemalloc
import zipfile

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from streamlit.testing.v1 import AppTest

import backup
import db
from conftest import ADMIN, ROOT

CSV_RE = re.compile(r"^LeadFlow_(Master|MQL|Bounce|Unsubscribed)_Backup_(\d+)_records_(\d{4}-\d{2}-\d{2})\.csv$")
ZIP_RE = re.compile(r"^LeadFlow_Backup_(\d+)_records_(\d{4}-\d{2}-\d{2})\.zip$")
DAY = dt.date(2026, 10, 21)
# The tables' own columns, exactly as db.SCHEMA_DDL defines them; a backup must hold these and nothing else.
MASTER_COLUMNS = ["id", "list_id", "email", "first_name", "last_name", "company", "job_title", "industry",
                  "location", "created_at"]
EMAIL_COLUMNS = ["id", "list_id", "email", "created_at"]
MQL_COLUMNS = EMAIL_COLUMNS + ["first_name", "last_name", "company", "job_title"]  # added by db._ensure_mql_details
COLUMNS = {"master": MASTER_COLUMNS, "mql": MQL_COLUMNS, "bounce": EMAIL_COLUMNS, "unsub": EMAIL_COLUMNS}
SEEDED_COUNTS = {"master": 3, "mql": 2, "bounce": 1, "unsub": 3}


@pytest.fixture(autouse=True)
def backup_tmp(tmp_path, monkeypatch):
    """Keep backup files in the test's own folder and forget prepared downloads afterwards."""
    monkeypatch.setattr(backup, "backup_dir", lambda: tmp_path)
    yield tmp_path
    backup._DOWNLOADS.clear()


TRICKY = [  # values that need CSV quoting, plus non-ASCII
    {"email": "ann@acme.com", "first_name": "Ann", "last_name": "O'Neil, Jr.", "company": 'Acme "Labs"',
     "job_title": "CTO\nand founder", "industry": "Software", "location": "Zürich"},
    {"email": "bob@acme.com", "first_name": "Bob"},  # other fields NULL
]


@pytest.fixture
def seeded():
    db.store_records("master", "Master, A", TRICKY)
    db.store_records("master", "Master B", [{"email": "ann@acme.com", "first_name": "Ann B"}])  # same email, 2nd list
    db.store_records("mql", "MQL list", [{"email": "mql1@x.com"}, {"email": "mql2@x.com"}])
    db.store_records("bounce", "Bounces", [{"email": "b@x.com"}])
    db.store_records("unsub", "Unsubs", [{"email": "u1@x.com"}, {"email": "u2@x.com"}, {"email": "u3@x.com"}])


def _db_rows(category):
    """Every row of the category's table straight from the database, as Python values (None = NULL)."""
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {', '.join(COLUMNS[category])} FROM {backup.TABLES[category]} ORDER BY id")
        return cur.fetchall()


def _parse_csv(text):
    rows = list(csv.reader(io.StringIO(text, newline="")))
    return rows[0], rows[1:]


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return _parse_csv(f.read())


def _read_zip(path):
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        return {name: _parse_csv(zf.read(name).decode("utf-8")) for name in zf.namelist()}


def _assert_matches_db(category, header, rows):
    """The CSV holds the table's columns only, and every row with its actual values."""
    assert header == COLUMNS[category]
    db_rows = _db_rows(category)
    assert len(rows) == len(db_rows)
    for got, want in zip(rows, db_rows):
        assert len(got) == len(header)
        for col, g, w in zip(header, got, want):
            if w is None:
                assert g == "", col
            elif isinstance(w, dt.datetime):
                assert dt.datetime.fromisoformat(g) == w, col  # same instant, full precision
            else:
                assert g == str(w), (col, g, w)


def _snapshot():
    with db.get_conn() as conn:
        cur = conn.cursor()
        out = {}
        for t in [*backup.TABLES.values(), "master_lists", "mql_lists", "bounce_lists", "unsub_lists",
                  "upload_history"]:
            cur.execute(f"SELECT md5(string_agg(t::text, '|' ORDER BY t::text)), COUNT(*) FROM {t} t")
            out[t] = cur.fetchone()
    return out


# --------------------------------------------------------------------------- #
# File names and columns
# --------------------------------------------------------------------------- #
def test_backup_filenames_use_the_exact_count_scope_and_date():
    assert backup.backup_filename(1897432, DAY) == "LeadFlow_Backup_1897432_records_2026-10-21.zip"
    assert backup.backup_filename(1900000, DAY, "master") == "LeadFlow_Master_Backup_1900000_records_2026-10-21.csv"
    assert backup.backup_filename(7, DAY, "mql") == "LeadFlow_MQL_Backup_7_records_2026-10-21.csv"
    assert backup.backup_filename(7, DAY, "bounce") == "LeadFlow_Bounce_Backup_7_records_2026-10-21.csv"
    assert backup.backup_filename(7, DAY, "unsub") == "LeadFlow_Unsubscribed_Backup_7_records_2026-10-21.csv"
    with pytest.raises(ValueError):
        backup.backup_filename(1, DAY, "everything")


def test_table_columns_come_from_the_database():
    with db.get_conn() as conn:
        cur = conn.cursor()
        assert {c: backup.table_columns(cur, t) for c, t in backup.TABLES.items()} == COLUMNS


# --------------------------------------------------------------------------- #
# Completeness, exact columns and counts
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("category", list(backup.TABLES))
def test_category_backup_is_its_table_exactly(seeded, backup_tmp, category):
    before = _snapshot()
    result = backup.write_backup(category, day=DAY)

    header, rows = _read_csv(result.path)
    _assert_matches_db(category, header, rows)
    n = SEEDED_COUNTS[category]
    assert result.record_count == len(rows) == n and result.per_category == {category: n}
    assert result.filename == backup.backup_filename(n, DAY, category) and CSV_RE.match(result.filename)
    assert result.media_type == "text/csv" and result.size_bytes == os.path.getsize(result.path)
    assert _snapshot() == before  # read-only
    assert [p.name for p in backup_tmp.iterdir()] == [result.path.name]  # no stray temp files


def test_master_backup_keeps_tricky_values(seeded):
    header, rows = _read_csv(backup.write_backup("master").path)
    ann = next(dict(zip(header, r)) for r in rows if r[header.index("first_name")] == "Ann")
    assert (ann["last_name"], ann["company"], ann["job_title"], ann["location"]) == \
        ("O'Neil, Jr.", 'Acme "Labs"', "CTO\nand founder", "Zürich")
    bob = next(dict(zip(header, r)) for r in rows if r[header.index("first_name")] == "Bob")
    assert bob["company"] == "" and bob["industry"] == ""


def test_all_backup_is_a_zip_of_every_table(seeded):
    before = _snapshot()
    result = backup.write_backup("all", day=DAY)
    assert result.filename == "LeadFlow_Backup_9_records_2026-10-21.zip" and result.media_type == "application/zip"
    assert result.record_count == 9 and result.per_category == SEEDED_COUNTS
    members = _read_zip(result.path)
    assert sorted(members) == sorted(f"{t}.csv" for t in backup.TABLES.values())
    for cat, table in backup.TABLES.items():
        _assert_matches_db(cat, *members[f"{table}.csv"])
    assert _snapshot() == before


def test_all_backup_keeps_empty_categories_as_header_only():
    db.store_records("mql", "Only MQL", [{"email": "a@x.com"}])
    result = backup.write_backup("all", day=DAY)
    assert result.filename == "LeadFlow_Backup_1_records_2026-10-21.zip"
    members = _read_zip(result.path)
    assert members["master_contacts.csv"] == (MASTER_COLUMNS, [])
    assert members["mql_emails.csv"][1][0][2] == "a@x.com"


@pytest.mark.parametrize("scope", ["all", "master"])
@pytest.mark.parametrize("batch_size", [1, 2, 3, 9, 10_000])
def test_every_batch_size_writes_the_final_partial_batch(seeded, scope, batch_size):
    result = backup.write_backup(scope, batch_size=batch_size)
    if scope == "all":
        assert result.record_count == 9
        assert sum(len(rows) for _, rows in _read_zip(result.path).values()) == 9
    else:
        assert result.record_count == SEEDED_COUNTS[scope]
        _assert_matches_db(scope, *_read_csv(result.path))


def test_progress_reports_the_running_count(seeded):
    calls = []
    backup.write_backup("all", batch_size=2, progress=lambda w, e: calls.append((w, e)))
    assert calls[-1] == (9, 9)
    assert [w for w, _ in calls] == sorted(w for w, _ in calls)


def _bulk_insert(n_master):
    """n_master Master contacts plus a few thousand rows in each email category, in SQL."""
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO master_lists (name) VALUES ('Bulk') RETURNING id")
        list_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO master_contacts (list_id, email, first_name, last_name, company, job_title,
                                                    industry, location)
                       SELECT %s, 'person' || g || '@example.com', 'First' || g, 'Last' || g, 'Company ' || (g %% 997),
                              'Title', 'Industry', 'City, Country'
                       FROM generate_series(1, %s) g""", (list_id, n_master))
        for cat, n in (("mql", 3001), ("bounce", 2002), ("unsub", 1003)):
            lists_t, emails_t = db.EMAIL_CATEGORIES[cat]
            cur.execute(f"INSERT INTO {lists_t} (name) VALUES ('Bulk') RETURNING id")
            lid = cur.fetchone()[0]
            cur.execute(f"INSERT INTO {emails_t} (list_id, email) "
                        f"SELECT %s, '{cat}' || g || '@example.com' FROM generate_series(1, %s) g", (lid, n))
    return {"master": n_master, "mql": 3001, "bounce": 2002, "unsub": 1003}


LARGE_ROWS = int(os.environ.get("LEADFLOW_BACKUP_TEST_ROWS", "300000"))


def _measured(scope):
    tracemalloc.start()
    try:
        started = time.perf_counter()
        result = backup.write_backup(scope)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print(f"\n{scope} backup of {result.record_count:,} rows: {elapsed:.1f}s, "
          f"{result.size_bytes / 2**20:.0f} MiB file, {peak / 2**20:.1f} MiB peak Python memory")
    # Peak memory is bounded by one batch (backup.BATCH_ROWS rows), whatever the export's size.
    assert peak < 24 * 2**20
    return result


def test_large_backups_are_complete_and_memory_stays_bounded():
    counts = _bulk_insert(LARGE_ROWS)

    master = _measured("master")
    assert master.record_count == counts["master"]
    assert CSV_RE.match(master.filename).group(2) == str(counts["master"])
    with open(master.path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        assert next(reader) == MASTER_COLUMNS
        n, last = 0, None
        for last in reader:
            n += 1
    assert n == counts["master"] and last[2] == f"person{LARGE_ROWS}@example.com"

    everything = _measured("all")
    assert everything.record_count == sum(counts.values()) and everything.per_category == counts
    assert ZIP_RE.match(everything.filename).group(1) == str(sum(counts.values()))
    with zipfile.ZipFile(everything.path) as zf:
        for cat, table in backup.TABLES.items():
            with zf.open(f"{table}.csv") as raw:
                lines = sum(1 for _ in csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline="")))
            assert lines == counts[cat] + 1  # + header


# --------------------------------------------------------------------------- #
# Empty database and failures: no file, no success
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scope", backup.SCOPES)
def test_empty_scope_raises_and_leaves_no_file(backup_tmp, scope):
    if scope not in ("master", "all"):
        db.store_records("master", "Other", [{"email": "m@x.com"}])  # records elsewhere don't count
    with pytest.raises(backup.EmptyDatabaseError):
        backup.write_backup(scope)
    assert list(backup_tmp.iterdir()) == []


def test_unknown_scope_is_rejected(backup_tmp):
    with pytest.raises(ValueError):
        backup.write_backup("everything")
    assert list(backup_tmp.iterdir()) == []


@pytest.mark.parametrize("scope", ["all", "unsub"])
def test_interrupted_export_leaves_no_file(seeded, backup_tmp, scope):
    def interrupt(written, expected):
        if written >= 2:
            raise ConnectionError("connection lost")
    with pytest.raises(ConnectionError):
        backup.write_backup(scope, batch_size=1, progress=interrupt)
    assert list(backup_tmp.iterdir()) == []


def test_database_error_leaves_no_file(seeded, backup_tmp, monkeypatch):
    monkeypatch.setattr(backup, "_select_sql", lambda table, columns: "SELECT * FROM no_such_table")
    with pytest.raises(Exception, match="no_such_table"):
        backup.write_backup("all")
    assert list(backup_tmp.iterdir()) == []


@pytest.mark.parametrize("scope", ["all", "master"])
def test_short_export_is_rejected_not_named_as_complete(seeded, backup_tmp, monkeypatch, scope):
    # A query that silently drops a row must fail the count check rather than produce a smaller "backup".
    real = backup._select_sql
    monkeypatch.setattr(backup, "_select_sql",
                        lambda table, columns: real(table, columns).replace(" ORDER BY", " WHERE t.id > 1 ORDER BY"))
    with pytest.raises(backup.BackupError, match="incomplete"):
        backup.write_backup(scope)
    assert list(backup_tmp.iterdir()) == []


def test_unreachable_database_raises_and_leaves_no_file(backup_tmp, monkeypatch):
    def down(*a, **k):
        raise db.psycopg2.OperationalError("could not connect")
    monkeypatch.setattr(db, "get_conn", down)
    with pytest.raises(db.psycopg2.OperationalError):
        backup.write_backup("all")
    assert list(backup_tmp.iterdir()) == []


# --------------------------------------------------------------------------- #
# Download route
# --------------------------------------------------------------------------- #
def _client():
    return TestClient(Starlette(routes=backup.routes()))


@pytest.mark.parametrize("scope, name, mime", [
    ("all", "LeadFlow_Backup_9_records_2026-10-21.zip", "application/zip"),
    ("mql", "LeadFlow_MQL_Backup_2_records_2026-10-21.csv", "text/csv"),
])
def test_route_streams_the_file_under_its_exact_name(seeded, scope, name, mime):
    result = backup.write_backup(scope, day=DAY)
    token = backup.register_download(result)
    resp = _client().get(backup.download_url(token))
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == f'attachment; filename="{name}"'
    assert resp.headers["content-type"].startswith(mime)
    assert resp.headers["cache-control"] == "no-store"
    assert int(resp.headers["content-length"]) == result.size_bytes
    assert resp.content == result.path.read_bytes()


def test_route_rejects_unknown_and_expired_tokens(seeded):
    client = _client()
    assert client.get(backup.download_url("not-a-token")).status_code == 404
    result = backup.write_backup("all")
    token = backup.register_download(result, ttl=-1)
    assert client.get(backup.download_url(token)).status_code == 404
    assert not result.path.exists()  # expired backups are deleted


def test_discard_deletes_the_file(seeded):
    result = backup.write_backup("all")
    token = backup.register_download(result)
    backup.discard_download(token)
    assert backup.get_download(token) is None and not result.path.exists()


# --------------------------------------------------------------------------- #
# Database page
# --------------------------------------------------------------------------- #
def _db_page():
    at = AppTest.from_file(str(ROOT / "pages" / "1_Database.py"), default_timeout=60)
    at.session_state["_auth_user"] = dict(ADMIN)
    at.session_state["_auth_restore_attempted"] = True
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _click_backup(at, scope=None):
    if scope:
        at.segmented_control(key="db_backup_scope").set_value(scope)
    next(b for b in at.button if b.key == "db_backup_start").click()
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_page_offers_every_scope_with_its_count(seeded):
    at = _db_page()
    control = at.segmented_control(key="db_backup_scope")
    assert control.value == "all"
    assert list(control.options) == ["All (9)", "Master leads (3)", "MQL (2)", "Bounced (1)", "Unsubscribed (3)"]


def test_page_download_all_prepares_the_zip(seeded):
    at = _click_backup(_db_page())
    ready = at.session_state["db_backup"]
    assert ZIP_RE.match(ready["filename"]).group(1) == "9" and ready["count"] == 9
    assert ready["mime"] == "application/zip"
    assert any("Backup ready: **9 records**" in str(s.value) for s in at.success)
    assert sum(len(rows) for _, rows in _read_zip(ready["path"]).values()) == 9
    # A second backup replaces the first one's file.
    first_path = ready["path"]
    at = _click_backup(at, "bounce")
    assert at.session_state["db_backup"]["path"] != first_path and not os.path.exists(first_path)


@pytest.mark.parametrize("scope", list(backup.TABLES))
def test_page_download_one_category(seeded, scope):
    at = _click_backup(_db_page(), scope)
    ready = at.session_state["db_backup"]
    n = SEEDED_COUNTS[scope]
    assert ready["filename"] == backup.backup_filename(n, dt.date.today(), scope) and ready["mime"] == "text/csv"
    _assert_matches_db(scope, *_read_csv(ready["path"]))


def test_page_empty_category_offers_no_download():
    db.store_records("master", "Only master", [{"email": "m@x.com"}])
    at = _click_backup(_db_page(), "unsub")
    assert "db_backup" not in at.session_state
    assert any("Unsubscribed has no records" in str(i.value) for i in at.info)


def test_page_failed_backup_reports_an_error(seeded, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(backup, "write_backup", boom)
    at = _click_backup(_db_page())
    assert "db_backup" not in at.session_state
    assert any("The backup didn't finish" in str(e.value) for e in at.error)
    assert not at.success

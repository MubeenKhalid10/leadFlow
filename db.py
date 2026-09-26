"""
LeadFlow — PostgreSQL data layer
--------------------------------

Stores the suppression data (Master contact lists and Bounce lists) that used
to be uploaded on every run. Both master and bounce data are organised as
*named lists* so you can keep several imports/campaigns side by side and choose
which ones to suppress against per run.

Tables
------
master_lists      (id, name, created_at)
master_contacts   (id, list_id -> master_lists, email, first_name, last_name,
                   company, job_title, industry, location, created_at)
bounce_lists      (id, name, created_at)
bounce_emails     (id, list_id -> bounce_lists, email, created_at)
mql_lists / mql_emails, unsub_lists / unsub_emails   (same shape as bounce)
upload_history    (category, list_name, file_name, file_size_bytes, rows_in_file,
                   rows_written, rows_skipped, uploaded_by, uploaded_at)

Emails are always stored normalised (trimmed + lower-cased) so suppression and
de-duplication are reliable. Each list de-dupes on (list_id, email).

Configuration
-------------
Connection settings are read in this priority order:
    1. st.secrets["postgres"]   (see .streamlit/secrets.toml)
    2. Environment variables     (PG_HOST/PGHOST, PG_PORT/PGPORT, PG_DATABASE/PGDATABASE,
                                  PG_USER/PGUSER, PG_PASSWORD/PGPASSWORD, PG_SSLMODE/PGSSLMODE)
    3. Local defaults            (localhost:5432, db "leadflow", user "postgres" — dev only)

Nothing here raises on import — connection problems surface through
check_connection() so the UI can show a friendly setup message instead of a
stack trace.
"""

from __future__ import annotations

import functools
import io
import os
import threading
import time
from contextlib import ExitStack, contextmanager

import pandas as pd
import psycopg2
from psycopg2 import pool as _pgpool
from psycopg2.extras import execute_values

try:  # Streamlit is available in the app, but keep db.py importable without it.
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


def _cached(ttl: int, resource: bool = False):
    """Cache a read-only query across reruns (and sessions) when Streamlit is present.

    `resource=True` uses st.cache_resource so large sets are shared by reference
    instead of being pickled/copied on every call. Every write function below
    clears these caches via invalidate_caches().
    """
    def deco(fn):
        if st is None:
            return fn
        cacher = st.cache_resource if resource else st.cache_data
        return cacher(ttl=ttl, show_spinner=False)(fn)
    return deco


DEFAULT_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "dbname": "leadflow",
    "user": "postgres",
    "password": "postgres",
    "sslmode": "",  # e.g. "require" for most cloud providers; blank = driver default
}

# Maintenance database used only to CREATE DATABASE if the target is missing.
_MAINTENANCE_DB = "postgres"

# Two spellings are accepted for each setting: the libpq names (PGHOST, ...)
# and the underscore names used by the Docker/AWS deployment (PG_HOST, ...).
# The first one found wins.
_ENV_MAP = {
    "host": ("PG_HOST", "PGHOST"),
    "port": ("PG_PORT", "PGPORT"),
    "dbname": ("PG_DATABASE", "PGDATABASE"),
    "user": ("PG_USER", "PGUSER"),
    "password": ("PG_PASSWORD", "PGPASSWORD"),
    "sslmode": ("PG_SSLMODE", "PGSSLMODE"),
}


def get_config() -> dict:
    """Resolve connection settings from secrets -> env -> defaults."""
    cfg = dict(DEFAULT_CONFIG)

    # 1) Streamlit secrets ([postgres] section). Accessing st.secrets when no
    #    secrets file exists raises, so guard everything.
    if st is not None:
        try:
            section = st.secrets.get("postgres", None)
        except Exception:
            section = None
        if section:
            for key in cfg:
                if key in section and str(section[key]).strip() != "":
                    cfg[key] = str(section[key])

    # 2) Environment variables override secrets when present.
    for key, env_names in _ENV_MAP.items():
        for env_name in env_names:
            val = os.environ.get(env_name)
            if val is not None and val.strip() != "":
                cfg[key] = val
                break

    return cfg


def _conn_kwargs(dbname: str | None = None) -> dict:
    cfg = get_config()
    kwargs = dict(
        host=cfg["host"],
        port=cfg["port"],
        dbname=dbname or cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        connect_timeout=5,
    )
    if cfg.get("sslmode"):
        kwargs["sslmode"] = cfg["sslmode"]
    return kwargs


# Process-wide connection pool. Opening a fresh TLS connection to a cloud
# Postgres costs several hundred ms; Streamlit reruns the whole script on every
# click, so without a pool each rerun paid that cost several times over.
_POOL_LOCK = threading.Lock()
_POOL: _pgpool.ThreadedConnectionPool | None = None
_POOL_KEY: tuple | None = None
_LAST_USED: dict[int, float] = {}
_IDLE_PROBE_SECONDS = 60  # probe connections idle longer than this before reuse
_POOL_MAX = 8


def _get_pool() -> _pgpool.ThreadedConnectionPool:
    global _POOL, _POOL_KEY
    kwargs = _conn_kwargs()
    key = tuple(sorted(kwargs.items()))
    with _POOL_LOCK:
        if _POOL is None or _POOL.closed or _POOL_KEY != key:
            if _POOL is not None and not _POOL.closed:
                try:
                    _POOL.closeall()
                except Exception:
                    pass
            _POOL = _pgpool.ThreadedConnectionPool(1, _POOL_MAX, **kwargs)
            _POOL_KEY = key
            _LAST_USED.clear()
        return _POOL


def _checkout() -> tuple[_pgpool.ThreadedConnectionPool, psycopg2.extensions.connection]:
    """Get a live connection from the pool, replacing any that went stale."""
    pool_ = _get_pool()
    for _ in range(_POOL_MAX + 1):
        conn = pool_.getconn()
        if conn.closed:
            pool_.putconn(conn, close=True)
            continue
        idle_for = time.time() - _LAST_USED.get(id(conn), 0.0)
        if idle_for > _IDLE_PROBE_SECONDS:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                conn.rollback()
            except Exception:
                pool_.putconn(conn, close=True)
                continue
        return pool_, conn
    # Pool only handed us dead connections; open a fresh one directly.
    return pool_, pool_.getconn()


@contextmanager
def get_conn(dbname: str | None = None, autocommit: bool = False):
    """Yield a psycopg2 connection, committing on success.

    Connections to the configured database come from a shared pool and are
    returned to it afterwards. Pass dbname to open a one-off connection to a
    specific database (used by ensure_database()).
    """
    if dbname:
        conn = psycopg2.connect(**_conn_kwargs(dbname))
        conn.autocommit = autocommit
        try:
            yield conn
            if not autocommit:
                conn.commit()
        except Exception:
            if not autocommit:
                conn.rollback()
            raise
        finally:
            conn.close()
        return

    pool_, conn = _checkout()
    broken = False
    try:
        conn.autocommit = autocommit
        yield conn
        if not autocommit:
            conn.commit()
    except Exception as exc:
        broken = bool(conn.closed) or isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))
        if not autocommit and not broken:
            try:
                conn.rollback()
            except Exception:
                broken = True
        raise
    finally:
        if not broken:
            try:
                conn.autocommit = False
            except Exception:
                broken = True
        _LAST_USED[id(conn)] = time.time()
        try:
            pool_.putconn(conn, close=broken)
        except Exception:
            pass


def _fetch_df(query: str, params=None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame (avoids the pandas+psycopg2 warning)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params or ())
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------- #
# Connection / schema management
# --------------------------------------------------------------------------- #
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS master_lists (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS master_contacts (
    id          BIGSERIAL PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES master_lists(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    first_name  TEXT,
    last_name   TEXT,
    company     TEXT,
    job_title   TEXT,
    industry    TEXT,
    location    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (list_id, email)
);
CREATE INDEX IF NOT EXISTS idx_master_contacts_email ON master_contacts (email);

CREATE TABLE IF NOT EXISTS bounce_lists (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bounce_emails (
    id          BIGSERIAL PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES bounce_lists(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (list_id, email)
);
CREATE INDEX IF NOT EXISTS idx_bounce_emails_email ON bounce_emails (email);

CREATE TABLE IF NOT EXISTS mql_lists (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mql_emails (
    id          BIGSERIAL PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES mql_lists(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (list_id, email)
);
CREATE INDEX IF NOT EXISTS idx_mql_emails_email ON mql_emails (email);

CREATE TABLE IF NOT EXISTS unsub_lists (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unsub_emails (
    id          BIGSERIAL PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES unsub_lists(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (list_id, email)
);
CREATE INDEX IF NOT EXISTS idx_unsub_emails_email ON unsub_emails (email);

CREATE TABLE IF NOT EXISTS upload_history (
    id              BIGSERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    list_name       TEXT,
    file_name       TEXT NOT NULL,
    file_size_bytes BIGINT,
    rows_in_file    INTEGER,
    rows_written    INTEGER,
    rows_skipped    INTEGER,
    uploaded_by     TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_upload_history_category ON upload_history (category, uploaded_at DESC);
"""

# Email-only suppression categories share one schema (<cat>_lists / <cat>_emails).
EMAIL_CATEGORIES = {
    "bounce": ("bounce_lists", "bounce_emails"),
    "mql": ("mql_lists", "mql_emails"),
    "unsub": ("unsub_lists", "unsub_emails"),
}
ALL_CATEGORIES = ("master", "mql", "bounce", "unsub")


def _tables(category: str) -> tuple[str, str]:
    try:
        return EMAIL_CATEGORIES[category]
    except KeyError:
        raise ValueError(f"Unknown email category: {category!r}")


def ensure_database() -> tuple[bool, str | None]:
    """Create the target database if it does not exist.

    Returns (created_or_exists, error_message). Requires the configured user to
    have CREATEDB privilege; if not, we return a helpful message and the caller
    can ask the user to create it manually.
    """
    cfg = get_config()
    # If we can already connect to the target db, nothing to do.
    try:
        with get_conn() as conn:  # noqa: F841
            return True, None
    except psycopg2.OperationalError:
        pass  # fall through and try to create it

    try:
        with get_conn(dbname=_MAINTENANCE_DB, autocommit=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["dbname"],))
            if cur.fetchone() is None:
                # Identifier can't be parameterised; dbname comes from config, not user input.
                cur.execute(f'CREATE DATABASE "{cfg["dbname"]}"')
        return True, None
    except Exception as exc:
        return False, (
            f"Could not automatically create database '{cfg['dbname']}': {exc}. "
            f"Create it once manually, e.g.  createdb {cfg['dbname']}"
        )


# Merge tracking. Every row a merge inserts carries that transaction's now() in
# created_at, so upload_history records the list and that exact timestamp
# (batch_created_at) to find, and revert, the merge's rows later. Only the small
# upload_history table gets new columns; the contact/email tables are unchanged.
_UPLOAD_HISTORY_COLUMNS = {
    "list_id": "INTEGER",
    "batch_created_at": "TIMESTAMPTZ",
    "reverted_at": "TIMESTAMPTZ",
    "link_checked": "BOOLEAN",   # NULL = logged before merge tracking; not yet matched
}
_MERGE_TRACKING_READY = False
_PAST_MERGE_WINDOW = pd.Timedelta(hours=6)


def _ensure_merge_tracking(cur) -> None:
    """Add the upload_history columns if missing (catalog check, so no table lock
    on every page load) and link merges logged before tracking existed."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'upload_history'"
    )
    have = {r[0] for r in cur.fetchall()}
    for col, typ in _UPLOAD_HISTORY_COLUMNS.items():
        if col not in have:
            cur.execute(f"ALTER TABLE upload_history ADD COLUMN IF NOT EXISTS {col} {typ}")
    cur.execute("SELECT 1 FROM upload_history WHERE link_checked IS NULL LIMIT 1")
    if cur.fetchone():
        _link_past_merges(cur)


def _link_past_merges(cur) -> None:
    """Match merges logged before tracking to the rows they inserted.

    A past entry is linked only when its list has a batch of rows sharing one
    insert time, up to 6 hours before the entry was logged, whose size equals the
    rows_written the log recorded. Anything uncertain stays unlinked and so can't
    be reverted. Runs once, under a lock so parallel app tasks don't race.
    """
    cur.execute("SELECT pg_advisory_xact_lock(740212)")
    lists_tables = {"master": ("master_lists", "master_contacts"), **EMAIL_CATEGORIES}
    for cat, (lists_t, _) in lists_tables.items():
        # Names are unique per category; a list created after the upload can't have received it.
        cur.execute(
            f"UPDATE upload_history h SET list_id = l.id FROM {lists_t} l "
            "WHERE h.category = %s AND h.link_checked IS NULL AND h.list_id IS NULL "
            "AND h.list_name = l.name AND l.created_at <= h.uploaded_at",
            (cat,),
        )
    cur.execute(
        "SELECT id, category, list_id, uploaded_at, rows_written FROM upload_history "
        "WHERE link_checked IS NULL ORDER BY uploaded_at, id"
    )
    pending = cur.fetchall()
    for cat, (_, rows_t) in lists_tables.items():
        entries = [e for e in pending if e[1] == cat]
        if not entries:
            continue
        list_ids = sorted({e[2] for e in entries if e[2] is not None and (e[4] or 0) > 0})
        batches: dict = {}
        if list_ids:
            cur.execute(
                f"SELECT list_id, created_at, COUNT(*) FROM {rows_t} "
                "WHERE list_id = ANY(%s) GROUP BY list_id, created_at",
                (list_ids,),
            )
            for lid, created, n in cur.fetchall():
                batches.setdefault(lid, []).append((created, n))
        cur.execute(
            "SELECT list_id, batch_created_at FROM upload_history "
            "WHERE category = %s AND batch_created_at IS NOT NULL",
            (cat,),
        )
        claimed = set(cur.fetchall())
        for hid, _, lid, uploaded_at, written in entries:
            batch = None
            if lid is not None and (written or 0) > 0:
                window = [
                    (created, n) for created, n in batches.get(lid, ())
                    if uploaded_at - _PAST_MERGE_WINDOW <= created <= uploaded_at and (lid, created) not in claimed
                ]
                if window:
                    created, n = max(window)
                    if n == written:
                        batch = created
                        claimed.add((lid, created))
            cur.execute(
                "UPDATE upload_history SET batch_created_at = %s, link_checked = TRUE WHERE id = %s",
                (batch, hid),
            )


def init_db() -> tuple[bool, str | None]:
    """Ensure the database and all tables exist. Returns (ok, error_message)."""
    global _MERGE_TRACKING_READY
    ok, err = ensure_database()
    if not ok:
        return False, err
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(SCHEMA_DDL)
            if not _MERGE_TRACKING_READY:
                _ensure_merge_tracking(cur)
        _MERGE_TRACKING_READY = True
        return True, None
    except Exception as exc:
        return False, str(exc)


def check_connection() -> tuple[bool, str | None]:
    """Lightweight connectivity probe used by the UI."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, None
    except Exception as exc:
        return False, str(exc)


# --------------------------------------------------------------------------- #
# Value helpers
# --------------------------------------------------------------------------- #
def normalize_email(value) -> str:
    """Trim + lower-case an email; empties/placeholders become ''."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    if text in ("", "nan", "none", "null"):
        return ""
    return text


def _clean_field(value):
    """Normalise an optional text field to a trimmed string or None."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in ("nan", "none", "null"):
        return None
    return text


# --------------------------------------------------------------------------- #
# Master lists
# --------------------------------------------------------------------------- #
@_cached(ttl=600)
def get_master_lists() -> pd.DataFrame:
    """Return all master lists with contact counts, newest first.

    Columns: id, name, created_at, contact_count.
    """
    return _fetch_df(
        """
        SELECT l.id,
               l.name,
               l.created_at,
               COALESCE(c.contact_count, 0) AS contact_count
        FROM master_lists l
        LEFT JOIN (
            SELECT list_id, COUNT(*) AS contact_count FROM master_contacts GROUP BY list_id
        ) c ON c.list_id = l.id
        ORDER BY l.created_at DESC, l.name;
        """
    )


def get_or_create_master_list(name: str) -> int:
    """Return the id of the master list with this name, creating it if needed."""
    clean = (name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO master_lists (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING RETURNING id",
            (clean,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM master_lists WHERE name = %s", (clean,))
        return cur.fetchone()[0]


def _log_merge(cur, category: str, list_id: int, upload: dict, rows_written: int, rows_skipped: int) -> None:
    """Record a merge in upload_history inside the same transaction as its rows, so
    batch_created_at (this transaction's now()) matches the rows' created_at."""
    cur.execute(
        """
        INSERT INTO upload_history
            (category, list_name, file_name, file_size_bytes, rows_in_file, rows_written,
             rows_skipped, uploaded_by, list_id, batch_created_at, link_checked)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s > 0 THEN now() END, TRUE)
        """,
        (category, upload.get("list_name"), upload["file_name"], upload.get("file_size_bytes"),
         int(upload.get("rows_in_file", 0)), int(rows_written), int(rows_skipped), upload.get("uploaded_by"),
         list_id, int(rows_written)),
    )


def upsert_master_contacts(list_id: int, records: list[dict], upload: dict | None = None) -> int:
    """Insert/update full contact records into a master list (dedupe by email).

    `records` is a list of dicts with keys: email, first_name, last_name,
    company, job_title, industry, location. Rows with a blank email are skipped.
    Returns the number of rows written (inserted + updated).

    Pass `upload` (file_name, list_name, rows_in_file, rows_skipped, file_size_bytes,
    uploaded_by) to log the merge in upload_history in the same transaction.
    """
    rows = []
    for rec in records:
        email = normalize_email(rec.get("email"))
        if not email:
            continue
        rows.append(
            (
                list_id,
                email,
                _clean_field(rec.get("first_name")),
                _clean_field(rec.get("last_name")),
                _clean_field(rec.get("company")),
                _clean_field(rec.get("job_title")),
                _clean_field(rec.get("industry")),
                _clean_field(rec.get("location")),
            )
        )
    if not rows:
        if upload:
            record_upload("master", upload["file_name"], upload.get("rows_in_file", 0), 0,
                          upload.get("rows_skipped", 0), upload.get("list_name"),
                          upload.get("file_size_bytes"), upload.get("uploaded_by"), list_id=list_id)
        return 0

    conflict = """
        ON CONFLICT (list_id, email) DO UPDATE SET
            first_name = COALESCE(EXCLUDED.first_name, master_contacts.first_name),
            last_name  = COALESCE(EXCLUDED.last_name,  master_contacts.last_name),
            company    = COALESCE(EXCLUDED.company,    master_contacts.company),
            job_title  = COALESCE(EXCLUDED.job_title,  master_contacts.job_title),
            industry   = COALESCE(EXCLUDED.industry,   master_contacts.industry),
            location   = COALESCE(EXCLUDED.location,   master_contacts.location);
    """
    with get_conn() as conn:
        cur = conn.cursor()
        if len({r[1] for r in rows}) == len(rows):
            # COPY into a temp table, then one INSERT..SELECT: the same insert/update
            # rules, in the same order, without a round trip per 5,000 rows.
            cur.execute(
                "CREATE TEMP TABLE _lf_master_in (ord BIGINT, list_id INTEGER, email TEXT, "
                "first_name TEXT, last_name TEXT, company TEXT, job_title TEXT, industry TEXT, "
                "location TEXT) ON COMMIT DROP"
            )
            _copy_rows(cur, "_lf_master_in", ((i, *r) for i, r in enumerate(rows)))
            cur.execute(
                "INSERT INTO master_contacts "
                "(list_id, email, first_name, last_name, company, job_title, industry, location) "
                "SELECT list_id, email, first_name, last_name, company, job_title, industry, location "
                "FROM _lf_master_in ORDER BY ord " + conflict
            )
        else:
            # The same email twice in one call: keep the original batched behaviour exactly.
            execute_values(
                cur,
                "INSERT INTO master_contacts "
                "(list_id, email, first_name, last_name, company, job_title, industry, location) "
                "VALUES %s " + conflict,
                rows,
                template="(%s,%s,%s,%s,%s,%s,%s,%s)",
                page_size=5000,
            )
        if upload:
            _log_merge(cur, "master", list_id, upload, len(rows), upload.get("rows_skipped", 0))
    return len(rows)


@_cached(ttl=600, resource=True)
def get_master_emails(list_ids: list[int]) -> set:
    """Return the set of normalised emails across the given master lists."""
    if not list_ids:
        return set()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT email FROM master_contacts WHERE list_id = ANY(%s)",
            (sorted(set(list_ids)),),
        )
        return {r[0] for r in cur.fetchall()}


@_cached(ttl=600, resource=True)
def get_all_master_emails() -> set:
    """Return ALL normalised emails across ALL master lists (for global dedup).

    Use this before saving new contacts to ensure no email is stored twice
    anywhere in the master database — regardless of which list it belongs to.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT email FROM master_contacts")
        return {r[0] for r in cur.fetchall()}


def _copy_escape(value: str) -> str:
    """Escape a value for PostgreSQL COPY text format."""
    return (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _copy_rows(cur, table: str, rows) -> None:
    """COPY tuples into `table` (text format; None becomes NULL)."""
    buf = io.StringIO()
    for row in rows:
        buf.write("\t".join("\\N" if v is None else _copy_escape(str(v)) for v in row))
        buf.write("\n")
    buf.seek(0)
    cur.copy_expert(f"COPY {table} FROM STDIN", buf)


class EmailProbe:
    """Run several suppression checks against one upload of the same emails.

    The emails are COPYed into a temp table once. Each take_*() returns the stored
    emails that match (as find_existing_*() would) and removes them from the probe,
    so every later check only looks at the emails that survived the earlier ones.
    One pooled connection is held from the first check until close().
    """

    def __init__(self, emails):
        self._pending = emails
        self._stack = None
        self._cur = None

    def _open(self):
        seen = set()
        cleaned = []
        for e in self._pending:
            n = normalize_email(e)
            if n and n not in seen:
                seen.add(n)
                cleaned.append(n)
        self._pending = None
        self._stack = ExitStack()
        conn = self._stack.enter_context(get_conn())
        cur = conn.cursor()
        cur.execute("CREATE TEMP TABLE _lf_probe (email TEXT) ON COMMIT DROP")
        buf = io.StringIO("".join(_copy_escape(e) + "\n" for e in cleaned))
        cur.copy_expert("COPY _lf_probe (email) FROM STDIN", buf)
        cur.execute("ANALYZE _lf_probe")
        self._cur = cur

    def _take(self, table: str, list_ids) -> set:
        if self._cur is None:
            self._open()
        if list_ids:
            self._cur.execute(
                f"DELETE FROM _lf_probe u USING {table} m "
                f"WHERE m.email = u.email AND m.list_id = ANY(%s) RETURNING u.email",
                (sorted({int(i) for i in list_ids}),),
            )
        else:
            self._cur.execute(f"DELETE FROM _lf_probe u USING {table} m WHERE m.email = u.email RETURNING u.email")
        return {r[0] for r in self._cur.fetchall()}

    def take_master(self, list_ids=None) -> set:
        return self._take("master_contacts", list_ids)

    def take(self, category: str, list_ids=None) -> set:
        return self._take(_tables(category)[1], list_ids)

    def close(self) -> None:
        """Release the connection (the temp table goes with the transaction). Safe to call twice."""
        stack, self._stack, self._cur = self._stack, None, None
        if stack is not None:
            try:
                stack.close()
            except Exception:
                pass

    def __del__(self):  # safety net if a run stops before close()
        self.close()


def _find_existing(table: str, emails, list_ids=None) -> set:
    """Return the subset of `emails` that already exist in `table` (optionally only in `list_ids`).

    The emails are streamed into a temporary table with COPY (the fastest way to
    get a large list into Postgres) and joined server-side against the indexed
    email column, so only the matches travel back over the wire. Downloading every
    stored email and comparing locally took ~40 s for 800k rows; this takes a few
    seconds for 100k probe emails.
    """
    seen = set()
    cleaned = []
    for e in emails:
        n = normalize_email(e)
        if n and n not in seen:
            seen.add(n)
            cleaned.append(n)
    if not cleaned:
        return set()

    ids = sorted({int(i) for i in list_ids}) if list_ids else None
    with get_conn() as conn:
        cur = conn.cursor()
        # ON COMMIT DROP: the table lives only for this transaction (get_conn commits on exit).
        cur.execute("CREATE TEMP TABLE _lf_probe (email TEXT) ON COMMIT DROP")
        buf = io.StringIO("".join(_copy_escape(e) + "\n" for e in cleaned))
        cur.copy_expert("COPY _lf_probe (email) FROM STDIN", buf)
        cur.execute("ANALYZE _lf_probe")
        if ids is None:
            cur.execute(
                f"SELECT DISTINCT m.email FROM _lf_probe u JOIN {table} m ON m.email = u.email"
            )
        else:
            cur.execute(
                f"SELECT DISTINCT m.email FROM _lf_probe u JOIN {table} m ON m.email = u.email "
                f"WHERE m.list_id = ANY(%s)",
                (ids,),
            )
        return {r[0] for r in cur.fetchall()}


def find_existing_master_emails(emails, list_ids=None) -> set:
    """Which of `emails` are already stored in master_contacts (all lists, or just `list_ids`)."""
    return _find_existing("master_contacts", emails, list_ids)


@_cached(ttl=600)
def get_global_master_stats() -> dict:
    """Return total unique emails and total lists across all master data.

    Returns a dict with keys: total_lists, total_contacts, unique_emails.
    'unique_emails' counts distinct email values (ignoring list_id).
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM master_lists)            AS total_lists,
                (SELECT COUNT(*) FROM master_contacts)         AS total_contacts,
                (SELECT COUNT(DISTINCT email) FROM master_contacts) AS unique_emails
            """
        )
        row = cur.fetchone()
    return {
        "total_lists": int(row[0]),
        "total_contacts": int(row[1]),
        "unique_emails": int(row[2]),
    }


def get_master_contacts_df(list_ids: list[int], limit: int | None = None) -> pd.DataFrame:
    """Return full contact rows for the given master lists (for preview/export).

    Pass `limit` to cap the number of rows fetched (used for fast previews).
    """
    if not list_ids:
        return pd.DataFrame(
            columns=["email", "first_name", "last_name", "company", "job_title", "industry", "location"]
        )
    query = """
        SELECT email, first_name, last_name, company, job_title, industry, location
        FROM master_contacts
        WHERE list_id = ANY(%s)
        ORDER BY email
    """
    params: list = [list(list_ids)]
    if limit is not None:
        query += " LIMIT %s"
        params.append(int(limit))
    return _fetch_df(query + ";", tuple(params))


def delete_master_list(list_id: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM master_lists WHERE id = %s", (list_id,))


def rename_master_list(list_id: int, new_name: str) -> None:
    clean = (new_name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE master_lists SET name = %s WHERE id = %s", (clean, list_id))


# --------------------------------------------------------------------------- #
# Email-only lists (Bounce / MQL / Unsub) — one generic implementation
# --------------------------------------------------------------------------- #
@_cached(ttl=600)
def get_email_lists(category: str) -> pd.DataFrame:
    """Return all lists of an email-only category with email counts, newest first.

    Columns: id, name, created_at, email_count.
    """
    lists_t, emails_t = _tables(category)
    return _fetch_df(
        f"""
        SELECT l.id,
               l.name,
               l.created_at,
               COALESCE(e.email_count, 0) AS email_count
        FROM {lists_t} l
        LEFT JOIN (
            SELECT list_id, COUNT(*) AS email_count FROM {emails_t} GROUP BY list_id
        ) e ON e.list_id = l.id
        ORDER BY l.created_at DESC, l.name;
        """
    )


def get_or_create_email_list(category: str, name: str) -> int:
    lists_t, _ = _tables(category)
    clean = (name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {lists_t} (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING RETURNING id",
            (clean,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(f"SELECT id FROM {lists_t} WHERE name = %s", (clean,))
        return cur.fetchone()[0]


def upsert_emails(category: str, list_id: int, emails, upload: dict | None = None) -> int:
    """Insert emails into a list (dedupe by email).

    Returns the number of rows actually inserted: emails already in the list
    are skipped by ON CONFLICT and are not counted.

    Pass `upload` (file_name, list_name, rows_in_file, file_size_bytes, uploaded_by)
    to log the merge in upload_history in the same transaction.
    """
    _, emails_t = _tables(category)
    seen = set()
    rows = []
    for value in emails:
        email = normalize_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        rows.append((list_id, email))
    if not rows:
        if upload:
            rows_in_file = upload.get("rows_in_file", 0)
            record_upload(category, upload["file_name"], rows_in_file, 0, max(rows_in_file, 0),
                          upload.get("list_name"), upload.get("file_size_bytes"), upload.get("uploaded_by"),
                          list_id=list_id)
        return 0

    with get_conn() as conn:
        cur = conn.cursor()
        # Rows are already unique, so one INSERT..SELECT from a COPY-loaded temp table
        # inserts and skips exactly what batched VALUES did.
        cur.execute("CREATE TEMP TABLE _lf_emails_in (ord BIGINT, list_id INTEGER, email TEXT) ON COMMIT DROP")
        _copy_rows(cur, "_lf_emails_in", ((i, *r) for i, r in enumerate(rows)))
        cur.execute(
            f"INSERT INTO {emails_t} (list_id, email) "
            "SELECT list_id, email FROM _lf_emails_in ORDER BY ord "
            "ON CONFLICT (list_id, email) DO NOTHING"
        )
        inserted = cur.rowcount
        if upload:
            rows_in_file = upload.get("rows_in_file", 0)
            _log_merge(cur, category, list_id, upload, inserted, max(rows_in_file - inserted, 0))
    return inserted


@_cached(ttl=600, resource=True)
def get_category_emails(category: str, list_ids: list[int]) -> set:
    _, emails_t = _tables(category)
    if not list_ids:
        return set()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT email FROM {emails_t} WHERE list_id = ANY(%s)",
            (list(list_ids),),
        )
        return {r[0] for r in cur.fetchall()}


def find_existing_emails(category: str, emails, list_ids=None) -> set:
    """Which of `emails` are present in the category's email table (all lists, or just `list_ids`)."""
    _, emails_t = _tables(category)
    return _find_existing(emails_t, emails, list_ids)


def get_emails_df(category: str, list_ids: list[int], limit: int | None = None) -> pd.DataFrame:
    """Return emails for the given lists as a DataFrame (for preview)."""
    _, emails_t = _tables(category)
    if not list_ids:
        return pd.DataFrame(columns=["email"])
    query = f"SELECT email FROM {emails_t} WHERE list_id = ANY(%s) ORDER BY email"
    params: list = [list(list_ids)]
    if limit is not None:
        query += " LIMIT %s"
        params.append(int(limit))
    return _fetch_df(query + ";", tuple(params))


def delete_email_list(category: str, list_id: int) -> None:
    lists_t, _ = _tables(category)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {lists_t} WHERE id = %s", (list_id,))


def rename_email_list(category: str, list_id: int, new_name: str) -> None:
    lists_t, _ = _tables(category)
    clean = (new_name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE {lists_t} SET name = %s WHERE id = %s", (clean, list_id))


# Bounce wrappers keep the original API used by app.py.
def get_bounce_lists() -> pd.DataFrame:
    return get_email_lists("bounce")


def get_or_create_bounce_list(name: str) -> int:
    return get_or_create_email_list("bounce", name)


def upsert_bounce_emails(list_id: int, emails) -> int:
    return upsert_emails("bounce", list_id, emails)


def get_bounce_emails(list_ids: list[int]) -> set:
    return get_category_emails("bounce", list_ids)


def find_existing_bounce_emails(emails, list_ids=None) -> set:
    return find_existing_emails("bounce", emails, list_ids)


def get_bounce_emails_df(list_ids: list[int], limit: int | None = None) -> pd.DataFrame:
    return get_emails_df("bounce", list_ids, limit)


def delete_bounce_list(list_id: int) -> None:
    delete_email_list("bounce", list_id)


def rename_bounce_list(list_id: int, new_name: str) -> None:
    rename_email_list("bounce", list_id, new_name)


# --------------------------------------------------------------------------- #
# Live counts, storage statistics and upload history
# --------------------------------------------------------------------------- #
@_cached(ttl=30)
def get_category_counts() -> dict:
    """Exact per-category record counts straight from the database.

    Returns {category: {"lists": n, "rows": n, "unique": n}}. Cached for only
    30 s and cleared by every write, so the numbers always follow the database.
    """
    parts = [
        "(SELECT COUNT(*) FROM master_lists)",
        "(SELECT COUNT(*) FROM master_contacts)",
        "(SELECT COUNT(DISTINCT email) FROM master_contacts)",
    ]
    for cat in ("mql", "bounce", "unsub"):
        lists_t, emails_t = _tables(cat)
        parts += [
            f"(SELECT COUNT(*) FROM {lists_t})",
            f"(SELECT COUNT(*) FROM {emails_t})",
            f"(SELECT COUNT(DISTINCT email) FROM {emails_t})",
        ]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT " + ", ".join(parts))
        row = [int(v) for v in cur.fetchone()]
    out = {}
    for i, cat in enumerate(("master", "mql", "bounce", "unsub")):
        out[cat] = {"lists": row[i * 3], "rows": row[i * 3 + 1], "unique": row[i * 3 + 2]}
    return out


def get_storage_quota_mb() -> int | None:
    """Total storage the database plan allows, from secrets/env. None if not configured."""
    val = os.environ.get("PG_STORAGE_QUOTA_MB")
    if not val and st is not None:
        try:
            val = st.secrets.get("postgres", {}).get("storage_quota_mb")
        except Exception:
            val = None
    try:
        return int(float(val)) if val not in (None, "") else None
    except (TypeError, ValueError):
        return None


@_cached(ttl=30)
def get_storage_info() -> dict:
    """Actual on-disk sizes reported by PostgreSQL (bytes) plus the Master row count."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pg_database_size(current_database()),
                   pg_total_relation_size('master_contacts') + pg_total_relation_size('master_lists'),
                   pg_total_relation_size('mql_emails') + pg_total_relation_size('mql_lists'),
                   pg_total_relation_size('bounce_emails') + pg_total_relation_size('bounce_lists'),
                   pg_total_relation_size('unsub_emails') + pg_total_relation_size('unsub_lists'),
                   (SELECT COUNT(*) FROM master_contacts)
            """
        )
        db_bytes, master_b, mql_b, bounce_b, unsub_b, master_rows = cur.fetchone()
    master_rows = int(master_rows)
    per_million = int(master_b / master_rows * 1_000_000) if master_rows else None
    quota_mb = get_storage_quota_mb()
    return {
        "database_bytes": int(db_bytes),
        "master_bytes": int(master_b),
        "mql_bytes": int(mql_b),
        "bounce_bytes": int(bounce_b),
        "unsub_bytes": int(unsub_b),
        "master_rows": master_rows,
        "bytes_per_million": per_million,
        "quota_bytes": quota_mb * 1024 * 1024 if quota_mb else None,
    }


def record_upload(
    category: str,
    file_name: str,
    rows_in_file: int,
    rows_written: int,
    rows_skipped: int = 0,
    list_name: str | None = None,
    file_size_bytes: int | None = None,
    uploaded_by: str | None = None,
    list_id: int | None = None,
) -> None:
    """Log one file import (who/what/when) into upload_history.

    Used for imports that added no rows; merges that add rows are logged by the
    upsert functions themselves (see _log_merge).
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO upload_history
                (category, list_name, file_name, file_size_bytes, rows_in_file,
                 rows_written, rows_skipped, uploaded_by, list_id, link_checked)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            """,
            (category, list_name, file_name, file_size_bytes, int(rows_in_file),
             int(rows_written), int(rows_skipped), uploaded_by, list_id),
        )


@_cached(ttl=30)
def get_upload_history(category: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Upload log, newest first. Pass a category to filter."""
    query = (
        "SELECT id, category, list_id, list_name, file_name, file_size_bytes, rows_in_file, "
        "rows_written, rows_skipped, uploaded_by, uploaded_at, batch_created_at, reverted_at "
        "FROM upload_history"
    )
    params: list = []
    if category:
        query += " WHERE category = %s"
        params.append(category)
    query += " ORDER BY uploaded_at DESC LIMIT %s"
    params.append(int(limit))
    return _fetch_df(query, tuple(params))


@_cached(ttl=30)
def get_list_merges(category: str, list_id: int, limit: int = 500) -> pd.DataFrame:
    """Merges into one list, newest first (from upload_history)."""
    return _fetch_df(
        "SELECT id, file_name, file_size_bytes, rows_in_file, rows_written, rows_skipped, "
        "uploaded_by, uploaded_at, batch_created_at, reverted_at FROM upload_history "
        "WHERE category = %s AND list_id = %s ORDER BY uploaded_at DESC, id DESC LIMIT %s",
        (category, int(list_id), int(limit)),
    )


@_cached(ttl=30)
def get_merge_counts(category: str) -> dict:
    """{list_id: number of merges into it that haven't been reverted}."""
    df = _fetch_df(
        "SELECT list_id, COUNT(*) AS n FROM upload_history "
        "WHERE category = %s AND list_id IS NOT NULL AND reverted_at IS NULL GROUP BY list_id",
        (category,),
    )
    return {int(r.list_id): int(r.n) for r in df.itertuples()}


def revert_upload(upload_id: int) -> int:
    """Remove exactly the rows one merge added (its list + insert timestamp) and mark
    it reverted. Returns the number of rows removed. Other merges are untouched."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category, list_id, batch_created_at, reverted_at FROM upload_history "
            "WHERE id = %s FOR UPDATE",
            (int(upload_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("This merge no longer exists.")
        category, list_id, batch, reverted = row
        if reverted is not None:
            raise ValueError("This merge has already been reverted.")
        if list_id is None or batch is None:
            raise ValueError("This merge can't be reverted.")
        table = "master_contacts" if category == "master" else _tables(category)[1]
        cur.execute(f"DELETE FROM {table} WHERE list_id = %s AND created_at = %s", (list_id, batch))
        removed = cur.rowcount
        cur.execute("UPDATE upload_history SET reverted_at = now() WHERE id = %s", (int(upload_id),))
    return removed


# --------------------------------------------------------------------------- #
# Cache invalidation
# --------------------------------------------------------------------------- #
_CACHED_READERS = (
    get_master_lists,
    get_email_lists,
    get_master_emails,
    get_all_master_emails,
    get_category_emails,
    get_global_master_stats,
    get_category_counts,
    get_storage_info,
    get_upload_history,
    get_list_merges,
    get_merge_counts,
)


def invalidate_caches() -> None:
    """Drop every cached read so the next call sees fresh data. Cheap; safe to call often."""
    for fn in _CACHED_READERS:
        clear = getattr(fn, "clear", None)
        if clear is not None:
            try:
                clear()
            except Exception:
                pass


def _invalidating(fn):
    """Wrap a write function so the read caches are cleared after it runs."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            invalidate_caches()
    return wrapper


get_or_create_master_list = _invalidating(get_or_create_master_list)
upsert_master_contacts = _invalidating(upsert_master_contacts)
delete_master_list = _invalidating(delete_master_list)
rename_master_list = _invalidating(rename_master_list)
get_or_create_email_list = _invalidating(get_or_create_email_list)
upsert_emails = _invalidating(upsert_emails)
delete_email_list = _invalidating(delete_email_list)
rename_email_list = _invalidating(rename_email_list)
record_upload = _invalidating(record_upload)
revert_upload = _invalidating(revert_upload)

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

Emails are always stored normalised (trimmed + lower-cased) so suppression and
de-duplication are reliable. Each list de-dupes on (list_id, email).

Configuration
-------------
Connection settings are read in this priority order:
    1. st.secrets["postgres"]   (see .streamlit/secrets.toml)
    2. Environment variables     (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD)
    3. Local defaults            (localhost:5432, db "leadflow", user "postgres")

Nothing here raises on import — connection problems surface through
check_connection() so the UI can show a friendly setup message instead of a
stack trace.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

try:  # Streamlit is available in the app, but keep db.py importable without it.
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


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

_ENV_MAP = {
    "host": "PGHOST",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "sslmode": "PGSSLMODE",
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
    for key, env_name in _ENV_MAP.items():
        val = os.environ.get(env_name)
        if val is not None and val.strip() != "":
            cfg[key] = val

    return cfg


@contextmanager
def get_conn(dbname: str | None = None, autocommit: bool = False):
    """Yield a psycopg2 connection, committing on success and always closing.

    Pass dbname to connect to a specific database (used by ensure_database()).
    """
    cfg = get_config()
    conn_kwargs = dict(
        host=cfg["host"],
        port=cfg["port"],
        dbname=dbname or cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        connect_timeout=5,
    )
    if cfg.get("sslmode"):
        conn_kwargs["sslmode"] = cfg["sslmode"]
    conn = psycopg2.connect(**conn_kwargs)
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
"""


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


def init_db() -> tuple[bool, str | None]:
    """Ensure the database and all tables exist. Returns (ok, error_message)."""
    ok, err = ensure_database()
    if not ok:
        return False, err
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(SCHEMA_DDL)
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
def get_master_lists() -> pd.DataFrame:
    """Return all master lists with contact counts, newest first.

    Columns: id, name, created_at, contact_count.
    """
    return _fetch_df(
        """
        SELECT l.id,
               l.name,
               l.created_at,
               COUNT(c.id) AS contact_count
        FROM master_lists l
        LEFT JOIN master_contacts c ON c.list_id = l.id
        GROUP BY l.id, l.name, l.created_at
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


def upsert_master_contacts(list_id: int, records: list[dict]) -> int:
    """Insert/update full contact records into a master list (dedupe by email).

    `records` is a list of dicts with keys: email, first_name, last_name,
    company, job_title, industry, location. Rows with a blank email are skipped.
    Returns the number of rows written (inserted + updated).
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
        return 0

    query = """
        INSERT INTO master_contacts
            (list_id, email, first_name, last_name, company, job_title, industry, location)
        VALUES %s
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
        execute_values(
            cur,
            query,
            rows,
            template="(%s,%s,%s,%s,%s,%s,%s,%s)",
            page_size=5000,
        )
    return len(rows)


def get_master_emails(list_ids: list[int]) -> set:
    """Return the set of normalised emails across the given master lists."""
    if not list_ids:
        return set()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT email FROM master_contacts WHERE list_id = ANY(%s)",
            (list(list_ids),),
        )
        return {r[0] for r in cur.fetchall()}


def get_all_master_emails() -> set:
    """Return ALL normalised emails across ALL master lists (for global dedup).

    Use this before saving new contacts to ensure no email is stored twice
    anywhere in the master database — regardless of which list it belongs to.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT email FROM master_contacts")
        return {r[0] for r in cur.fetchall()}


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
# Bounce lists
# --------------------------------------------------------------------------- #
def get_bounce_lists() -> pd.DataFrame:
    """Return all bounce lists with email counts, newest first.

    Columns: id, name, created_at, email_count.
    """
    return _fetch_df(
        """
        SELECT l.id,
               l.name,
               l.created_at,
               COUNT(e.id) AS email_count
        FROM bounce_lists l
        LEFT JOIN bounce_emails e ON e.list_id = l.id
        GROUP BY l.id, l.name, l.created_at
        ORDER BY l.created_at DESC, l.name;
        """
    )


def get_or_create_bounce_list(name: str) -> int:
    clean = (name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bounce_lists (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING RETURNING id",
            (clean,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM bounce_lists WHERE name = %s", (clean,))
        return cur.fetchone()[0]


def upsert_bounce_emails(list_id: int, emails) -> int:
    """Insert bounce emails into a list (dedupe by email). Returns rows written."""
    seen = set()
    rows = []
    for value in emails:
        email = normalize_email(value)
        if not email or email in seen:
            continue
        seen.add(email)
        rows.append((list_id, email))
    if not rows:
        return 0

    query = """
        INSERT INTO bounce_emails (list_id, email)
        VALUES %s
        ON CONFLICT (list_id, email) DO NOTHING;
    """
    with get_conn() as conn:
        cur = conn.cursor()
        execute_values(cur, query, rows, template="(%s,%s)", page_size=10000)
    return len(rows)


def get_bounce_emails(list_ids: list[int]) -> set:
    if not list_ids:
        return set()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT email FROM bounce_emails WHERE list_id = ANY(%s)",
            (list(list_ids),),
        )
        return {r[0] for r in cur.fetchall()}


def get_bounce_emails_df(list_ids: list[int], limit: int | None = None) -> pd.DataFrame:
    """Return bounce emails for the given lists as a DataFrame (for preview)."""
    if not list_ids:
        return pd.DataFrame(columns=["email"])
    query = "SELECT email FROM bounce_emails WHERE list_id = ANY(%s) ORDER BY email"
    params: list = [list(list_ids)]
    if limit is not None:
        query += " LIMIT %s"
        params.append(int(limit))
    return _fetch_df(query + ";", tuple(params))


def delete_bounce_list(list_id: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM bounce_lists WHERE id = %s", (list_id,))


def rename_bounce_list(list_id: int, new_name: str) -> None:
    clean = (new_name or "").strip()
    if not clean:
        raise ValueError("List name cannot be empty.")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE bounce_lists SET name = %s WHERE id = %s", (clean, list_id))

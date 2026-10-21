"""
LeadFlow — database backup (read-only CSV export)
-------------------------------------------------

Exports the saved records of one category (Master, MQL, Bounce or Unsubscribed)
as a CSV, or all four at once as a ZIP holding one CSV per table
(master_contacts.csv, mql_emails.csv, bounce_emails.csv, unsub_emails.csv). Each CSV
holds exactly the columns of its database table (read from the database, in table
order) and each value as PostgreSQL writes it as text; nothing is added.

A table with more than PART_ROWS records is split into parts (master_contacts_part1.csv,
master_contacts_part2.csv, …), each with the header row, so every file opens completely
in Excel (at most 1,048,576 rows per sheet). A single category that needs parts comes as
a ZIP of them. File names carry the number of records actually written:

    LeadFlow_Master_Backup_<record_count>_records_<YYYY-MM-DD>.csv   (one category)
    LeadFlow_Master_Backup_<record_count>_records_<YYYY-MM-DD>.zip   (one category, in parts)
    LeadFlow_Backup_<record_count>_records_<YYYY-MM-DD>.zip          (all categories)

How it stays small and correct with millions of rows
  * Rows are read through PostgreSQL server-side cursors in batches and written
    straight to a file on disk; at most one batch is ever held in memory.
  * The whole export runs in one REPEATABLE READ, READ ONLY transaction, so every
    table is read from the same snapshot and nothing can be changed by it.
  * Each table's COUNT(*) is taken in that same snapshot and must equal the rows
    written, or the export fails. The file is only given its final name after it
    is complete and flushed to disk; a failed export leaves no file behind.

Serving the file
  Streamlit's st.download_button keeps the whole file in memory, so the finished
  file is served from disk by a small HTTP route (see routes() / asgi_app.py)
  under a random, short-lived token handed out only on the admin-only Database
  page. When the app runs without that route (plain `streamlit run app.py`) the
  page falls back to st.download_button.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import secrets
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import db

BATCH_ROWS = 10_000            # rows fetched from the server per round trip (~15 MB in Python)
PART_ROWS = 1_000_000          # records per CSV file; Excel shows at most 1,048,576 rows (header included)
DOWNLOAD_TTL_SECONDS = 30 * 60  # how long a prepared backup can be downloaded
ROUTE_PATH = "/api/backup/{token}"

# Record table of each category, in the order "all" writes them.
TABLES = {"master": "master_contacts", "mql": "mql_emails", "bounce": "bounce_emails", "unsub": "unsub_emails"}
SCOPES = ("all", *TABLES)
MEDIA_TYPES = {".csv": "text/csv", ".zip": "application/zip"}


class BackupError(Exception):
    """The export did not complete; no backup file was produced."""


class EmptyDatabaseError(BackupError):
    """There are no records to back up."""


@dataclass
class BackupResult:
    path: Path
    filename: str
    record_count: int
    size_bytes: int
    per_category: dict = field(default_factory=dict)

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[Path(self.filename).suffix]


def scope_label(scope: str) -> str:
    return "All" if scope == "all" else db.CATEGORY_LABELS[scope]


def backup_filename(record_count: int, day: dt.date | None = None, scope: str = "all",
                    in_parts: bool = False) -> str:
    """LeadFlow_Backup_<n>_records_<date>.zip for "all"; LeadFlow_<Category>_Backup_<n>_records_<date>.csv
    for one category, or .zip when it is split into parts."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown backup scope: {scope!r}")
    day = day or dt.date.today()
    if scope == "all":
        return f"LeadFlow_Backup_{int(record_count)}_records_{day:%Y-%m-%d}.zip"
    ext = "zip" if in_parts else "csv"
    return f"LeadFlow_{scope_label(scope)}_Backup_{int(record_count)}_records_{day:%Y-%m-%d}.{ext}"


def part_names(table: str, record_count: int, part_rows: int = PART_ROWS) -> list[str]:
    """The CSV file(s) a table is written to: <table>.csv, or <table>_part1.csv, … when it has
    more than part_rows records."""
    if record_count <= part_rows:
        return [f"{table}.csv"]
    return [f"{table}_part{i}.csv" for i in range(1, -(-record_count // part_rows) + 1)]


def backup_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "leadflow_backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def table_columns(cur, table: str) -> list[str]:
    """The table's columns as the database defines them, in table order."""
    cur.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position""",
        (table,),
    )
    cols = [r[0] for r in cur.fetchall()]
    if not cols:
        raise BackupError(f"Table {table} wasn't found in the database.")
    return cols


def _select_sql(table: str, columns: list[str]) -> str:
    # ::text gives each value exactly as PostgreSQL writes it (NULL stays NULL -> empty field).
    cols = ", ".join(f't."{c}"::text AS "{c}"' for c in columns)
    # t."id" is the table's numeric id; a bare "id" would sort the text output column instead.
    order = ' ORDER BY t."id"' if "id" in columns else ""
    return f"SELECT {cols} FROM {table} t{order}"


def _write_table(conn, table, columns, open_part, batch_size, on_rows, part_rows=None) -> int:
    """Stream one table as CSV (header = its column names) into the text file open_part(1) returns,
    moving on to open_part(2), … whenever a file holds part_rows records (None: never).
    Returns the rows written."""
    written = in_part = 0
    part = 1
    f = open_part(part)
    writer = csv.writer(f)
    writer.writerow(columns)
    named = conn.cursor(name=f"lf_backup_{table}")
    named.itersize = batch_size
    try:
        named.execute(_select_sql(table, columns))
        while rows := named.fetchmany(batch_size):
            start = 0
            while start < len(rows):  # a batch can straddle two parts
                if part_rows and in_part == part_rows:
                    f.close()
                    part, in_part = part + 1, 0
                    f = open_part(part)
                    writer = csv.writer(f)
                    writer.writerow(columns)
                chunk = rows[start:start + part_rows - in_part] if part_rows else rows[start:]
                writer.writerows(chunk)
                in_part += len(chunk)
                start += len(chunk)
            written += len(rows)
            on_rows(len(rows))
    finally:
        named.close()
        f.close()
    return written


def write_backup(scope: str = "all", dest_dir: Path | None = None, *, batch_size: int = BATCH_ROWS,
                 part_rows: int = PART_ROWS, progress=None, day: dt.date | None = None) -> BackupResult:
    """Export one category ("master", "mql", "bounce", "unsub") as CSV, or "all" of them as a
    ZIP of one CSV per category, into dest_dir (default: backup_dir()); returns its details.
    A table with more than part_rows records is written as parts (see part_names()); a single
    category in parts comes as a ZIP.

    progress(written, expected) is called after each batch. Raises EmptyDatabaseError when
    there is nothing to export and BackupError (or the database error) when the export fails;
    in both cases no file is left behind.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown backup scope: {scope!r}")
    day = day or dt.date.today()
    cats = list(TABLES) if scope == "all" else [scope]
    dest_dir = Path(dest_dir) if dest_dir else backup_dir()
    fd, tmp_name = tempfile.mkstemp(prefix="leadflow_backup_", suffix=".part", dir=dest_dir)
    os.close(fd)
    tmp_path = Path(tmp_name)
    per_category: dict[str, int] = {}
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL TimeZone = 'UTC'")  # timestamps written the same way on every server
            expected, columns = {}, {}
            for cat in cats:
                columns[cat] = table_columns(cur, TABLES[cat])
                cur.execute(f"SELECT COUNT(*) FROM {TABLES[cat]}")
                expected[cat] = int(cur.fetchone()[0])
            expected_total = sum(expected.values())
            if expected_total == 0:
                where = "your lists" if scope == "all" else scope_label(scope)
                raise EmptyDatabaseError(f"There are no saved records in {where} to back up.")

            written = 0

            def on_rows(n):
                nonlocal written
                written += n
                if progress:
                    progress(written, expected_total)

            # Part names come from the snapshot's counts, which the rows written must match.
            names = {cat: part_names(TABLES[cat], expected[cat], part_rows) for cat in cats}
            zipped = scope == "all" or len(names[scope]) > 1
            if zipped:
                with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    for cat in cats:  # members named after the table: master_contacts.csv or _part1.csv, …
                        def open_member(part, cat=cat):
                            # Past the last expected part only if the table grew, which the count check rejects.
                            name = names[cat][part - 1] if part <= len(names[cat]) else f"{TABLES[cat]}_part{part}.csv"
                            return io.TextIOWrapper(zf.open(name, "w", force_zip64=True), encoding="utf-8", newline="")
                        per_category[cat] = _write_table(conn, TABLES[cat], columns[cat], open_member,
                                                         batch_size, on_rows, part_rows)
            else:
                per_category[scope] = _write_table(
                    conn, TABLES[scope], columns[scope],
                    lambda part: open(tmp_path, "w", encoding="utf-8", newline=""), batch_size, on_rows)
            with open(tmp_path, "rb+") as f:
                os.fsync(f.fileno())

        short = {c: (per_category.get(c, 0), n) for c, n in expected.items() if per_category.get(c, 0) != n}
        if short:
            detail = ", ".join(f"{scope_label(c)}: wrote {w:,} of {n:,}" for c, (w, n) in short.items())
            raise BackupError(f"The export was incomplete ({detail}).")

        final = dest_dir / backup_filename(written, day, scope, in_parts=zipped)
        # A unique stored name, so two backups with the same count and day never collide;
        # the download is still offered under the exact backup_filename().
        stored = dest_dir / f"{final.stem}_{secrets.token_hex(4)}{final.suffix}"
        os.replace(tmp_path, stored)
        return BackupResult(stored, final.name, written, stored.stat().st_size, per_category)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- #
# Prepared downloads, served from disk by the HTTP route
# --------------------------------------------------------------------------- #
@dataclass
class _Download:
    path: Path
    filename: str
    media_type: str
    expires_at: float


_LOCK = threading.Lock()
_DOWNLOADS: dict[str, _Download] = {}
_ROUTE_ENABLED = False


def register_download(result: BackupResult, ttl: float = DOWNLOAD_TTL_SECONDS) -> str:
    """Make a finished backup downloadable for ttl seconds; returns its secret token."""
    purge_expired()
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _DOWNLOADS[token] = _Download(Path(result.path), result.filename, result.media_type, time.time() + ttl)
    return token


def get_download(token: str) -> _Download | None:
    """The prepared backup for token, or None if unknown, expired or its file is gone."""
    purge_expired()
    with _LOCK:
        entry = _DOWNLOADS.get(token)
    return entry if entry and entry.path.exists() else None


def discard_download(token: str | None) -> None:
    """Forget a prepared backup and delete its file."""
    with _LOCK:
        entry = _DOWNLOADS.pop(token, None) if token else None
    if entry:
        entry.path.unlink(missing_ok=True)


def purge_expired(now: float | None = None) -> None:
    """Delete expired backups, plus files in backup_dir() no live download refers to
    (e.g. left by a restarted process or an export that was killed mid-way)."""
    now = time.time() if now is None else now
    with _LOCK:
        expired = [t for t, d in _DOWNLOADS.items() if d.expires_at <= now]
        for token in expired:
            _DOWNLOADS.pop(token).path.unlink(missing_ok=True)
        live = {d.path.name for d in _DOWNLOADS.values()}
    try:
        for path in backup_dir().iterdir():
            if path.name not in live and path.stat().st_mtime < now - DOWNLOAD_TTL_SECONDS:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def download_url(token: str) -> str:
    return ROUTE_PATH.format(token=token)


def route_enabled() -> bool:
    return _ROUTE_ENABLED


async def _download_endpoint(request):
    from starlette.responses import FileResponse, PlainTextResponse

    entry = get_download(request.path_params["token"])
    if entry is None:
        return PlainTextResponse("This backup link has expired. Prepare a new backup on the Database page.",
                                 status_code=404)
    return FileResponse(entry.path, media_type=entry.media_type, filename=entry.filename,
                        headers={"Cache-Control": "no-store"})


def routes() -> list:
    """Starlette routes for st.App (see asgi_app.py). Serving files from disk with a
    Content-Length lets the browser stream them and spot a cut-off download."""
    global _ROUTE_ENABLED
    from starlette.routing import Route

    _ROUTE_ENABLED = True
    return [Route(ROUTE_PATH, _download_endpoint, methods=["GET"])]

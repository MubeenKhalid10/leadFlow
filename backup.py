"""
LeadFlow — database backup (read-only Excel export)
---------------------------------------------------

Exports the saved records of one category (Master, MQL, Bounce or Unsubscribed),
or all four at once, as one Excel workbook (.xlsx). Each category gets its own
sheet holding the columns of its database table (read from the database, in table
order; LeadFlow's own id, list_id and created_at are left out) and each value as PostgreSQL writes it as text.

MQL, Bounce and Unsubscribed records keep the file's own columns in source_data
(JSON). Those are expanded into real columns, after the table's own, in the order
they were uploaded, so the sheet carries every column the user uploaded. A file
header that is the same as a table column gets " (uploaded)" appended.

An Excel sheet holds at most 1,048,576 rows, so a category with more than SHEET_ROWS
records continues on a new sheet in the same workbook: "Master (1)", "Master (2)", …
Every sheet starts with the header row. File names carry the number of records
actually written:

    LeadFlow_Master_Backup_<record_count>_records_<YYYY-MM-DD>.xlsx   (one category)
    LeadFlow_Backup_<record_count>_records_<YYYY-MM-DD>.xlsx          (all categories)

How it stays small and correct with millions of rows
  * Rows are read through PostgreSQL server-side cursors in batches and each sheet's
    XML is streamed straight into the workbook file on disk; at most one batch is
    ever held in memory. (XlsxWriter's low-memory mode took ~14 minutes for 2M
    rows, so the few XML parts of the workbook are written here directly.)
  * Every value is stored as a text cell, so Excel never turns an id into a number,
    drops a leading zero, reformats a date or runs text starting with "=" as a formula.
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

import datetime as dt
import os
import re
import secrets
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

import db

BATCH_ROWS = 10_000            # rows fetched from the server per round trip (~15 MB in Python)
EXCEL_MAX_ROWS = 1_048_576     # rows in one Excel sheet, header included
SHEET_ROWS = EXCEL_MAX_ROWS - 1  # records per sheet, after the header row
EXCEL_MAX_CELL_CHARS = 32_767  # characters Excel keeps in one cell
DOWNLOAD_TTL_SECONDS = 30 * 60  # how long a prepared backup can be downloaded
ROUTE_PATH = "/api/backup/{token}"

# Record table of each category, in the order "all" writes them.
TABLES = {"master": "master_contacts", "mql": "mql_emails", "bounce": "bounce_emails", "unsub": "unsub_emails"}
SCOPES = ("all", *TABLES)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    sheets: list = field(default_factory=list)  # sheet names, in workbook order
    media_type: str = XLSX_MEDIA_TYPE


def scope_label(scope: str) -> str:
    return "All" if scope == "all" else db.CATEGORY_LABELS[scope]


def backup_filename(record_count: int, day: dt.date | None = None, scope: str = "all") -> str:
    """LeadFlow_Backup_<n>_records_<date>.xlsx for "all", LeadFlow_<Category>_Backup_<n>_records_<date>.xlsx otherwise."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown backup scope: {scope!r}")
    day = day or dt.date.today()
    prefix = "LeadFlow" if scope == "all" else f"LeadFlow_{scope_label(scope)}"
    return f"{prefix}_Backup_{int(record_count)}_records_{day:%Y-%m-%d}.xlsx"


def sheet_names(label: str, record_count: int, sheet_rows: int = SHEET_ROWS) -> list[str]:
    """The sheet(s) a category is written to: "<label>", or "<label> (1)", "<label> (2)", … when it
    has more than sheet_rows records."""
    if record_count <= sheet_rows:
        return [label]
    return [f"{label} ({i})" for i in range(1, -(-record_count // sheet_rows) + 1)]


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


# Holds the uploaded columns of MQL / Bounce / Unsub records; exported expanded, not as JSON.
UPLOAD_JSON_COLUMNS = ("source_data", "source_columns")
# LeadFlow's own bookkeeping, not part of any uploaded file: id is used for ordering; none is exported.
INTERNAL_COLUMNS = ("id", "list_id", "created_at")
EXCEL_MAX_COLUMNS = 16_384


def uploaded_columns(cur, table: str) -> list[str]:
    """Every header found in the table's uploaded rows, in the order first uploaded."""
    cur.execute(
        f"""SELECT header FROM (
                SELECT DISTINCT ON (h.header) h.header, t.id, h.prio, h.ord
                FROM {table} t
                CROSS JOIN LATERAL (
                    SELECT value AS header, 0 AS prio, ordinality AS ord
                    FROM jsonb_array_elements_text(COALESCE(t.source_columns, '[]'::jsonb)) WITH ORDINALITY
                    UNION ALL
                    SELECT key, 1, 0 FROM jsonb_object_keys(
                        CASE WHEN jsonb_typeof(t.source_data) = 'object' THEN t.source_data ELSE '{{}}'::jsonb END) AS key
                ) h
                ORDER BY h.header, t.id, h.prio, h.ord
            ) first_seen ORDER BY id, prio, ord"""
    )
    return [r[0] for r in cur.fetchall()]


def category_layout(cur, table: str) -> tuple[list[str], str, tuple]:
    """(header row, SELECT sql, sql params) for one table. Values are ::text, exactly as PostgreSQL
    writes them (NULL stays NULL -> empty cell)."""
    columns = table_columns(cur, table)
    base = [c for c in columns if c not in UPLOAD_JSON_COLUMNS and c not in INTERNAL_COLUMNS]
    parts = [f't."{c}"::text' for c in base]
    headers, params = list(base), []
    if all(c in columns for c in UPLOAD_JSON_COLUMNS):
        taken = set(base)
        for name in uploaded_columns(cur, table):
            header = name
            while header in taken:
                header += " (uploaded)"
            taken.add(header)
            headers.append(header)
            parts.append("t.source_data ->> %s")
            params.append(name)
    if len(headers) > EXCEL_MAX_COLUMNS:
        raise BackupError(f"{table} has {len(headers):,} columns; an Excel sheet holds at most {EXCEL_MAX_COLUMNS:,}.")
    # t."id" is the table's numeric id; a bare "id" would sort the text output column instead.
    order = ' ORDER BY t."id"' if "id" in columns else ""
    return headers, f"SELECT {', '.join(parts)} FROM {table} t{order}", tuple(params)


# --------------------------------------------------------------------------- #
# Minimal streaming .xlsx writer: text cells only, a bold frozen header row
# --------------------------------------------------------------------------- #
_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet {_NS}>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)
_SHEET_START = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet {_NS} {_NS_R}>'
    '<sheetViews><sheetView workbookViewId="0">'
    '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
    '</sheetView></sheetViews><sheetData>'
)
_SHEET_END = "</sheetData></worksheet>"

# Characters XML can't hold (and \r, which XML readers turn into \n) are written as Excel's
# _xHHHH_ escapes; text that already looks like one has its "_" escaped so it reads back as typed.
_NEEDS_ESCAPE = re.compile(r"[&<>\x00-\x08\x0b-\x1f￾￿]|_x[0-9A-Fa-f]{4}_")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f￾￿]")
_LOOKS_ESCAPED = re.compile(r"_(x[0-9A-Fa-f]{4}_)")


def _cell_text(value: str) -> str:
    if not _NEEDS_ESCAPE.search(value):
        return value
    value = _LOOKS_ESCAPED.sub(r"_x005F_\1", value)
    value = _CONTROL.sub(lambda m: f"_x{ord(m.group()):04X}_", value)
    return _xml_escape(value)


def _column_letters(n: int) -> list[str]:
    out = []
    for i in range(1, n + 1):
        letters = ""
        while i:
            i, rem = divmod(i - 1, 26)
            letters = chr(65 + rem) + letters
        out.append(letters)
    return out


def _row_xml(row_number: int, values, letters, style: str = "") -> str:
    cells = "".join(
        f'<c r="{letters[i]}{row_number}"{style} t="inlineStr"><is><t xml:space="preserve">{_cell_text(v)}</t></is></c>'
        for i, v in enumerate(values) if v is not None
    )
    return f'<row r="{row_number}">{cells}</row>'


def _write_workbook_parts(zf: zipfile.ZipFile, sheets: list[str]) -> None:
    """The workbook's index parts, naming sheet1.xml, sheet2.xml, … as `sheets`, in order."""
    n = len(sheets)
    zf.writestr("[Content_Types].xml", (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                  for i in range(1, n + 1))
        + "</Types>"
    ))
    zf.writestr("_rels/.rels", (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    ))
    zf.writestr("xl/workbook.xml", (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook {_NS} {_NS_R}><sheets>'
        + "".join(f'<sheet name={_xml_attr(name)} sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(sheets, 1))
        + "</sheets></workbook>"
    ))
    zf.writestr("xl/_rels/workbook.xml.rels", (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                  for i in range(1, n + 1))
        + f'<Relationship Id="rId{n + 1}" Type="{_REL}/styles" Target="styles.xml"/></Relationships>'
    ))
    zf.writestr("xl/styles.xml", _STYLES)


def _write_table(conn, table, layout, open_sheet, batch_size, on_rows, sheet_rows) -> int:
    """Stream one table into sheets: open_sheet(1) returns a text file for the first sheet's XML,
    open_sheet(2) the next once a sheet holds sheet_rows records. Each sheet starts with the
    header row (the column names). Returns the rows written."""
    columns, sql, params = layout
    letters = _column_letters(len(columns))
    header = _row_xml(1, columns, letters, ' s="1"')
    written = in_sheet = 0
    sheet = 1
    f = open_sheet(sheet)
    f.write(_SHEET_START + header)
    named = conn.cursor(name=f"lf_backup_{table}")
    named.itersize = batch_size
    try:
        named.execute(sql, params)
        while rows := named.fetchmany(batch_size):
            parts = []
            for row in rows:
                if in_sheet == sheet_rows:  # sheet full: the rest continues on a new sheet
                    f.write("".join(parts) + _SHEET_END)
                    parts = []
                    f.close()
                    sheet, in_sheet = sheet + 1, 0
                    f = open_sheet(sheet)
                    f.write(_SHEET_START + header)
                for v in row:
                    if v is not None and len(v) > EXCEL_MAX_CELL_CHARS:
                        raise BackupError(
                            f"A value in {table} (sheet row {in_sheet + 2}) is longer than the "
                            f"{EXCEL_MAX_CELL_CHARS:,} characters an Excel cell can hold, so it can't be backed up "
                            "to Excel without losing part of it.")
                in_sheet += 1
                parts.append(_row_xml(in_sheet + 1, row, letters))
            f.write("".join(parts))
            written += len(rows)
            on_rows(len(rows))
        f.write(_SHEET_END)
    finally:
        named.close()
        f.close()
    return written


def write_backup(scope: str = "all", dest_dir: Path | None = None, *, batch_size: int = BATCH_ROWS,
                 sheet_rows: int = SHEET_ROWS, progress=None, day: dt.date | None = None) -> BackupResult:
    """Export one category ("master", "mql", "bounce", "unsub"), or "all" of them, as one Excel
    workbook in dest_dir (default: backup_dir()); returns its details. Each category has its own
    sheet; one with more than sheet_rows records continues on further sheets (see sheet_names()).

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
    sheets: list[str] = []
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL TimeZone = 'UTC'")  # timestamps written the same way on every server
            expected, columns = {}, {}
            for cat in cats:
                columns[cat] = category_layout(cur, TABLES[cat])
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

            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for cat in cats:
                    # Sheet names come from the snapshot's counts, which the rows written must match.
                    names = sheet_names(scope_label(cat), expected[cat], sheet_rows)

                    def open_sheet(n, cat=cat, names=names):
                        # Past the last expected sheet only if the table grew, which the count check rejects.
                        sheets.append(names[n - 1] if n <= len(names) else f"{scope_label(cat)} ({n})")
                        raw = zf.open(f"xl/worksheets/sheet{len(sheets)}.xml", "w", force_zip64=True)
                        return _BufferedText(raw)

                    per_category[cat] = _write_table(conn, TABLES[cat], columns[cat], open_sheet,
                                                     batch_size, on_rows, sheet_rows)
                _write_workbook_parts(zf, sheets)
            with open(tmp_path, "rb+") as f:
                os.fsync(f.fileno())

        short = {c: (per_category.get(c, 0), n) for c, n in expected.items() if per_category.get(c, 0) != n}
        if short:
            detail = ", ".join(f"{scope_label(c)}: wrote {w:,} of {n:,}" for c, (w, n) in short.items())
            raise BackupError(f"The export was incomplete ({detail}).")

        final = dest_dir / backup_filename(written, day, scope)
        # A unique stored name, so two backups with the same count and day never collide;
        # the download is still offered under the exact backup_filename().
        stored = dest_dir / f"{final.stem}_{secrets.token_hex(4)}{final.suffix}"
        os.replace(tmp_path, stored)
        return BackupResult(stored, final.name, written, stored.stat().st_size, per_category, sheets)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


class _BufferedText:
    """A zip member opened for writing, taking str: encodes to UTF-8 in large chunks."""

    def __init__(self, raw):
        self._raw = raw

    def write(self, text: str) -> None:
        self._raw.write(text.encode("utf-8"))

    def close(self) -> None:
        self._raw.close()


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

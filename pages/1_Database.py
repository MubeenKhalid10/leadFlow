"""
LeadFlow — Database (Master File · MQL · Bounce · Unsub)
--------------------------------------------------------

Seed and maintain the suppression data that the main cleaning page compares
against. Four categories, one tab each:

  * Master File — full contact records (deduped by email globally). New uploads
    are MERGED into the existing data: existing emails are skipped, new ones
    are appended, nothing is ever replaced.
  * MQL / Bounce / Unsub — email-only lists. Every upload is logged with file
    name, record count and date/time (upload history).

All counts shown here are queried live from PostgreSQL (see db.py).
"""

import pandas as pd
import streamlit as st

import Auth as auth
import db
import theme
from dataio import (
    MAX_ARCHIVE_CONTENT_BYTES,
    MAX_COMPRESSED_UPLOAD_BYTES,
    MAX_UNCOMPRESSED_UPLOAD_BYTES,
    auto_map_columns,
    extract_emails_from_file,
    get_upload_size,
    load_file,
    validate_upload,
)
st.set_page_config(
    page_title="LeadFlow — Database",
    page_icon="🗄️",
    layout="wide",
)
theme.inject_theme()
theme.inject_sidebar_title()

# --- Admin-only gate ----------------------------------------------------------
# Only users with the "admin" role (set in Supabase's public.profiles table)
# may view or edit the suppression database.
auth.require_role("admin")
auth.render_user_badge()

st.markdown('<div class="lf-topbar">', unsafe_allow_html=True)
theme.render_topbar(show_how=False)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("## 🗄️ Database")
st.caption(
    "Master File, MQL, Bounce and Unsub data live here as named lists. "
    "The main cleaning page compares uploaded files against whichever categories you pick per run."
)

# --- Ensure the database is reachable ----------------------------------------
_ok, _err = db.init_db()
if not _ok:
    st.error("⚠️ Can't reach the database.")
    with st.expander("How to fix this", expanded=True):
        st.markdown(
            "1. Make sure **PostgreSQL is running**.\n"
            "2. Check your connection settings in `.streamlit/secrets.toml` "
            "(host, port, dbname, user, password).\n"
            "3. See the **README** for full setup steps.\n\n"
            f"**Technical details:** `{_err}`"
        )
        if st.button("🔄 Retry database connection"):
            st.rerun()
    st.stop()

_cfg = db.get_config()
st.caption(f"✅ Connected to **{_cfg['dbname']}** at {_cfg['host']}:{_cfg['port']}")


# ============================================================================ #
# Helpers
# ============================================================================ #
MB = 1024 * 1024

# Standard field -> master_contacts column mapping used when importing masters.
MASTER_FIELD_MAP = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Company": "company",
    "Email": "email",
    "Job Title": "job_title",
    "Industry": "industry",
    "Location": "location",
}

NEW_LIST_LABEL = "➕ Create a new list…"

EMAIL_CATEGORIES = {
    # key: (tab label, icon, description shown above the uploader)
    "mql": ("MQL", "🎯", "Marketing-qualified leads. Only the email column is needed — LeadFlow auto-detects it."),
    "bounce": ("Bounce", "🚫", "Bounce export file(s). Only the email column is needed — LeadFlow auto-detects it."),
    "unsub": ("Unsub", "✋", "Unsubscribe export file(s). Only the email column is needed — LeadFlow auto-detects it."),
}


def fmt_bytes(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:,.1f} TB"


def _to_local(ts):
    """Convert a UTC timestamp to the viewer's browser time zone when known."""
    ts = pd.to_datetime(ts)
    tz = None
    try:
        tz = st.context.timezone
    except Exception:
        tz = None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    try:
        return ts.tz_convert(tz) if tz else ts
    except Exception:
        return ts


def fmt_datetime(ts) -> str:
    if ts is None or pd.isna(ts):
        return "—"
    local = _to_local(ts)
    return f"{local:%d-%b-%Y, %I:%M %p}"


def history_table(category: str | None, limit: int = 200) -> pd.DataFrame:
    """Upload history as a display-ready table (date/time in the viewer's time zone)."""
    hist = db.get_upload_history(category, limit)
    if hist.empty:
        return pd.DataFrame(
            columns=["Category", "List", "File", "File size", "Records in file", "Records added",
                     "Skipped (existing)", "Uploaded by", "Upload date", "Upload time"]
        )
    local = hist["uploaded_at"].map(_to_local)
    return pd.DataFrame(
        {
            "Category": hist["category"].map(lambda c: "Master File" if c == "master" else EMAIL_CATEGORIES.get(c, (c,))[0]),
            "List": hist["list_name"],
            "File": hist["file_name"],
            "File size": hist["file_size_bytes"].map(fmt_bytes),
            "Records in file": hist["rows_in_file"],
            "Records added": hist["rows_written"],
            "Skipped (existing)": hist["rows_skipped"],
            "Uploaded by": hist["uploaded_by"],
            "Upload date": local.map(lambda t: f"{t:%d-%b-%Y}"),
            "Upload time": local.map(lambda t: f"{t:%I:%M %p}"),
        }
    )


def last_upload_text(category: str) -> str:
    hist = db.get_upload_history(category, 1)
    if hist.empty:
        return "No uploads yet"
    row = hist.iloc[0]
    return f"{fmt_datetime(row['uploaded_at'])} · {row['file_name']} ({int(row['rows_written']):,} added)"


def log_upload(category, f, rows_in_file, rows_written, rows_skipped, list_name):
    """Record one file import in upload_history (never blocks the import)."""
    try:
        db.record_upload(
            category=category,
            file_name=f.name,
            rows_in_file=rows_in_file,
            rows_written=rows_written,
            rows_skipped=rows_skipped,
            list_name=list_name,
            file_size_bytes=get_upload_size(f),
            uploaded_by=(auth.current_user() or {}).get("email"),
        )
    except Exception as e:
        st.warning(f"Import succeeded but the upload history could not be written: {e}")


def records_from_master_df(df):
    """Turn an uploaded master DataFrame into contact dicts for db.upsert_master_contacts.

    Returns (records, mapping). If no Email column can be detected, records is None.
    """
    mapping = auto_map_columns(df)
    if "Email" not in mapping:
        return None, mapping
    present = [(std, key) for std, key in MASTER_FIELD_MAP.items() if std in mapping]
    series_list = [df[mapping[std]].astype(object) for std, _ in present]
    keys = [key for _, key in present]
    records = [dict(zip(keys, values)) for values in zip(*series_list)]
    return records, mapping


def pick_target_list(existing_names, key_prefix):
    """Selectbox to choose an existing list or create a new one. Returns the name."""
    choice = st.selectbox(
        "Save into which list?",
        [NEW_LIST_LABEL] + list(existing_names),
        key=f"{key_prefix}_choice",
        help="Pick an existing list to add to, or create a new one.",
    )
    if choice == NEW_LIST_LABEL:
        return st.text_input(
            "New list name",
            value="",
            placeholder="e.g. Q1 2025 Campaign",
            key=f"{key_prefix}_newname",
        )
    return choice


def render_list_manager(category: str, lists_df: pd.DataFrame, count_col: str, noun: str, key_prefix: str):
    """Rename / preview / delete controls, one row per list."""
    if lists_df.empty:
        st.markdown(
            f'<div class="lf-inline-panel">📭 No lists yet. Upload a file above to create your first one.</div>',
            unsafe_allow_html=True,
        )
        return
    total = int(lists_df[count_col].sum())
    st.caption(f"{len(lists_df)} list(s) · {total:,} {noun} total")
    for row in lists_df.itertuples():
        head_l, head_c, head_r = st.columns([5, 2, 2])
        head_l.markdown(f"**{row.name}**")
        head_c.markdown(f"{'👥' if category == 'master' else '✉️'} {int(getattr(row, count_col)):,} {noun}")
        head_r.caption(f"Created {pd.to_datetime(row.created_at):%Y-%m-%d}")
        with st.expander("⚙️ Rename · preview · delete", expanded=False):
            new_name = st.text_input("Rename to", value=row.name, key=f"{key_prefix}_rename_{row.id}")
            act_l, act_r = st.columns(2)
            if act_l.button("💾 Save name", key=f"{key_prefix}_save_{row.id}"):
                try:
                    if category == "master":
                        db.rename_master_list(row.id, new_name)
                    else:
                        db.rename_email_list(category, row.id, new_name)
                    st.success("Renamed.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Rename failed: {e}")
            if act_r.button("👁️ Preview first 20", key=f"{key_prefix}_prev_{row.id}"):
                try:
                    if category == "master":
                        preview = db.get_master_contacts_df([row.id], limit=20)
                    else:
                        preview = db.get_emails_df(category, [row.id], limit=20)
                    st.dataframe(preview, width="stretch")
                except Exception as e:
                    st.error(f"Preview failed: {e}")
            st.markdown("---")
            confirm = st.checkbox(
                f"Yes, permanently delete this list and all its {noun}",
                key=f"{key_prefix}_confirm_{row.id}",
            )
            if st.button("🗑️ Delete list", key=f"{key_prefix}_del_{row.id}", disabled=not confirm):
                try:
                    if category == "master":
                        db.delete_master_list(row.id)
                    else:
                        db.delete_email_list(category, row.id)
                    st.success(f"Deleted '{row.name}'.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")


# ============================================================================ #
# Live counts (queried from the database, never from session/upload state)
# ============================================================================ #
try:
    COUNTS = db.get_category_counts()
except Exception as e:
    st.error(f"Could not read record counts from the database: {e}")
    COUNTS = {c: {"lists": 0, "rows": 0, "unique": 0} for c in db.ALL_CATEGORIES}


def _tab_label(icon, label, cat):
    return f"{icon}  {label} ({COUNTS[cat]['unique']:,})"


tab_master, tab_mql, tab_bounce, tab_unsub = st.tabs(
    [
        _tab_label("🗂️", "Master File", "master"),
        _tab_label("🎯", "MQL", "mql"),
        _tab_label("🚫", "Bounce", "bounce"),
        _tab_label("✋", "Unsub", "unsub"),
    ]
)


# ---------------------------------------------------------------------------- #
# MASTER FILE
# ---------------------------------------------------------------------------- #
with tab_master:
    theme.section_header("01-Master File overview", "Storage")
    m = COUNTS["master"]
    try:
        stor = db.get_storage_info()
    except Exception as e:
        stor = None
        st.warning(f"Storage statistics unavailable: {e}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📧 Total Records (unique emails)", f"{m['unique']:,}")
    c2.metric("📋 Master Lists", f"{m['lists']:,}")
    c3.metric("🗄️ Database Size", fmt_bytes(stor["database_bytes"]) if stor else "—")
    c4.metric("🗂️ Master File Storage", fmt_bytes(stor["master_bytes"]) if stor else "—")

    c5, c6, c7, c8 = st.columns(4)
    if stor and stor["quota_bytes"]:
        free = max(stor["quota_bytes"] - stor["database_bytes"], 0)
        used_pct = min(stor["database_bytes"] / stor["quota_bytes"] * 100, 100)
        c5.metric("💾 Available Storage", fmt_bytes(free), f"{used_pct:.1f}% of {fmt_bytes(stor['quota_bytes'])} used", delta_color="off")
    else:
        c5.metric("💾 Available Storage", "Not configured")
    c6.metric("📐 Est. size per 1M records", fmt_bytes(stor["bytes_per_million"]) if stor and stor["bytes_per_million"] else "—")
    c7.metric("⬆️ Max upload (CSV/XLSX)", fmt_bytes(MAX_UNCOMPRESSED_UPLOAD_BYTES))
    c8.metric("🗜️ Max upload (ZIP/GZ)", fmt_bytes(MAX_COMPRESSED_UPLOAD_BYTES))

    if m["rows"] > m["unique"]:
        st.warning(
            f"⚠️ **{m['rows'] - m['unique']:,} cross-list duplicate email(s) detected.** "
            "The same email exists in multiple master lists. Merges skip existing emails, so this will not grow."
        )
    st.caption(
        f"Sizes are read live from PostgreSQL (`pg_database_size` / `pg_total_relation_size`). "
        f"A ZIP/GZ upload may expand to at most {fmt_bytes(MAX_ARCHIVE_CONTENT_BYTES)} of data. "
        + (
            "Set `storage_quota_mb` under `[postgres]` in secrets.toml (or `PG_STORAGE_QUOTA_MB`) "
            "to your database plan's limit to see available storage."
            if not (stor and stor["quota_bytes"]) else ""
        )
    )

    st.divider()
    theme.section_header("02-Upload Master File → Merge into database", "Merge")
    st.caption(
        "Upload one or more Master files. Records are cleaned and normalised, then **merged**: "
        "emails already in the Master database are skipped and only new contacts are appended. "
        "Existing data is never deleted or replaced."
    )

    master_files = st.file_uploader(
        "Master file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key="master_import_files",
    )
    if master_files:
        st.caption("Selected: " + " · ".join(f"{f.name} ({fmt_bytes(get_upload_size(f))})" for f in master_files))

    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        st.warning(f"Could not load Master lists: {e}")
    master_names = master_lists_df["name"].tolist() if not master_lists_df.empty else []

    master_target = pick_target_list(master_names, "master_target")

    if st.button("🔀  Merge into Master Database", type="primary", key="btn_import_master"):
        clean_name = (master_target or "").strip()
        if not master_files:
            st.error("Please choose at least one file to merge.")
        elif not clean_name:
            st.error("Please enter a name for the list.")
        else:
            upload_errors = [err for f in master_files if (err := validate_upload(f))]
            if upload_errors:
                for err in upload_errors:
                    st.error(err)
            else:
                written_total = 0
                skipped_files = []
                dedup_skipped_total = 0
                before_total = m["unique"]
                try:
                    list_id = db.get_or_create_master_list(clean_name)
                    batch_seen: set = set()
                    for f in master_files:
                        with st.spinner(f"Reading {f.name}…"):
                            fdf = load_file(f)
                        rows_in_file = len(fdf)
                        records, mapping = records_from_master_df(fdf)
                        if records is None:
                            skipped_files.append(f.name)
                            continue

                        # --- Global dedup, server-side --------------------------
                        # Only the emails that already exist anywhere in the Master
                        # database come back (COPY into a temp table + indexed join).
                        with st.spinner(f"Checking {len(records):,} emails against the Master database…"):
                            emails = [db.normalize_email(r.get("email", "")) for r in records]
                            existing = db.find_existing_master_emails(emails)
                        before_dedup = len(records)
                        kept = []
                        for r, e in zip(records, emails):
                            if not e or e in existing or e in batch_seen:
                                continue
                            batch_seen.add(e)
                            kept.append(r)
                        records = kept
                        dedup_skipped = before_dedup - len(records)
                        dedup_skipped_total += dedup_skipped

                        if dedup_skipped > 0:
                            st.info(
                                f"ℹ️ **{f.name}**: {dedup_skipped:,} email(s) already in the Master database "
                                f"(or duplicated in the file) — skipped. {len(records):,} new contacts will be merged."
                            )

                        written = 0
                        if records:
                            with st.spinner(f"Saving {len(records):,} new rows from {f.name}…"):
                                written = db.upsert_master_contacts(list_id, records)
                                written_total += written
                        log_upload("master", f, rows_in_file, written, dedup_skipped, clean_name)
                        del fdf, records, emails, existing

                    if skipped_files:
                        st.warning(
                            "No Email column detected in: "
                            + ", ".join(skipped_files)
                            + " — those files were skipped."
                        )
                    if written_total:
                        st.success(
                            f"✅ Merged **{written_total:,}** new contacts into Master list **'{clean_name}'**. "
                            f"Master database: {before_total:,} → {before_total + written_total:,} records"
                            + (f" ({dedup_skipped_total:,} existing email(s) skipped)." if dedup_skipped_total else ".")
                        )
                        st.rerun()
                    elif not skipped_files:
                        if dedup_skipped_total:
                            st.info(
                                f"All {dedup_skipped_total:,} email(s) already exist in the Master database. "
                                "Nothing new was merged."
                            )
                        else:
                            st.info("No rows with a valid email were found to merge.")
                except Exception as e:
                    st.error(f"Merge failed: {e}")

    st.divider()
    theme.section_header("03-Your Master lists", "Manage Lists")
    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        st.error(f"Could not load Master lists: {e}")
    render_list_manager("master", master_lists_df, "contact_count", "contacts", "m")

    st.divider()
    theme.section_header("04-Upload history", "History")
    try:
        st.dataframe(history_table("master"), width="stretch", hide_index=True)
    except Exception as e:
        st.warning(f"Could not load upload history: {e}")


# ---------------------------------------------------------------------------- #
# MQL / BOUNCE / UNSUB — email-only categories, same UI each
# ---------------------------------------------------------------------------- #
def render_email_category(category: str):
    label, icon, description = EMAIL_CATEGORIES[category]
    cnt = COUNTS[category]

    theme.section_header(f"01-{label} overview", "Overview")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{icon} Total Records", f"{cnt['unique']:,}")
    c2.metric("📋 Lists", f"{cnt['lists']:,}")
    try:
        c3.metric("🕒 Last Upload", last_upload_text(category))
    except Exception:
        c3.metric("🕒 Last Upload", "—")

    st.divider()
    theme.section_header(f"02-Upload {label} file", "Upload")
    st.caption(description + " Emails are normalised and deduplicated; existing data is never replaced.")

    files = st.file_uploader(
        f"{label} file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key=f"{category}_import_files",
    )
    if files:
        st.caption("Selected: " + " · ".join(f"{f.name} ({fmt_bytes(get_upload_size(f))})" for f in files))

    try:
        lists_df = db.get_email_lists(category)
    except Exception as e:
        lists_df = pd.DataFrame()
        st.warning(f"Could not load {label} lists: {e}")
    names = lists_df["name"].tolist() if not lists_df.empty else []

    target = pick_target_list(names, f"{category}_target")

    if st.button(f"📥  Upload into {label}", type="primary", key=f"btn_import_{category}"):
        clean_name = (target or "").strip()
        if not files:
            st.error("Please choose at least one file to upload.")
        elif not clean_name:
            st.error("Please enter a name for the list.")
        else:
            upload_errors = [err for f in files if (err := validate_upload(f))]
            if upload_errors:
                for err in upload_errors:
                    st.error(err)
            else:
                written_total = 0
                skipped_files = []
                try:
                    list_id = db.get_or_create_email_list(category, clean_name)
                    for f in files:
                        with st.spinner(f"Reading {f.name}…"):
                            fdf = load_file(f)
                        rows_in_file = len(fdf)
                        emails = extract_emails_from_file(fdf)
                        if emails is None or emails.empty:
                            skipped_files.append(f.name)
                            continue
                        with st.spinner(f"Saving {len(emails):,} emails from {f.name}…"):
                            written = db.upsert_emails(category, list_id, emails.tolist())
                        written_total += written
                        log_upload(category, f, rows_in_file, written, max(rows_in_file - written, 0), clean_name)
                        del fdf, emails
                    if skipped_files:
                        st.warning(
                            "No Email column detected in: "
                            + ", ".join(skipped_files)
                            + " — those files were skipped."
                        )
                    if written_total:
                        st.success(f"✅ Saved {written_total:,} emails into {label} list '{clean_name}'.")
                        st.rerun()
                    elif not skipped_files:
                        st.info(
                            f"No new emails were added. Every valid email in the file is already in "
                            f"{label} list '{clean_name}' (the upload is still recorded in the history)."
                        )
                except Exception as e:
                    st.error(f"Upload failed: {e}")

    st.divider()
    theme.section_header("03-Upload history", "History")
    try:
        st.dataframe(history_table(category), width="stretch", hide_index=True)
    except Exception as e:
        st.warning(f"Could not load upload history: {e}")

    st.divider()
    theme.section_header(f"04-Your {label} lists", "Manage Lists")
    try:
        lists_df = db.get_email_lists(category)
    except Exception as e:
        lists_df = pd.DataFrame()
        st.error(f"Could not load {label} lists: {e}")
    render_list_manager(category, lists_df, "email_count", "emails", category)


with tab_mql:
    render_email_category("mql")

with tab_bounce:
    render_email_category("bounce")

with tab_unsub:
    render_email_category("unsub")

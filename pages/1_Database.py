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

import html

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
    forget_file,
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
theme.sidebar_nav(auth.current_user(), current="pages/1_Database.py")

st.markdown('<div class="lf-topbar">', unsafe_allow_html=True)
theme.render_topbar(show_how=False)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("## 🗄️ Lead Database")
st.caption(
    "Your saved lead lists. When you clean a file, LeadFlow can skip anyone on these lists — "
    "leads you already have, bounced emails, MQLs and people who unsubscribed."
)

# --- Ensure the database is reachable ----------------------------------------
_ok, _err = db.init_db()
if not _ok:
    st.error("⚠️ **The lead database isn't reachable right now.** Your lists can't be shown or changed until it's back.")
    with st.expander("How to fix this", expanded=True):
        st.markdown(
            "1. Make sure **PostgreSQL is running**.\n"
            "2. Check your connection settings in `.streamlit/secrets.toml` "
            "(host, port, dbname, user, password).\n"
            "3. See the **README** for full setup steps.\n\n"
            f"**Technical details:** `{_err}`"
        )
        if st.button("🔄 Retry database connection", key="retry_db_conn"):
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
    "mql": ("MQL", "🎯", "Leads already marked as marketing-qualified. Only an email column is needed — LeadFlow finds it automatically."),
    "bounce": ("Bounced", "🚫", "Emails that bounced in past campaigns. Only an email column is needed — LeadFlow finds it automatically."),
    "unsub": ("Unsubscribed", "✋", "People who asked not to be contacted. Only an email column is needed — LeadFlow finds it automatically."),
}


def fmt_bytes(n) -> str:
    if n is None or pd.isna(n):
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
                     "Skipped (existing)", "Uploaded by", "Upload date", "Upload time", "Status"]
        )
    local = hist["uploaded_at"].map(_to_local)
    return pd.DataFrame(
        {
            "Category": hist["category"].map(lambda c: "Master leads" if c == "master" else EMAIL_CATEGORIES.get(c, (c,))[0]),
            "List": hist["list_name"],
            "File": hist["file_name"],
            "File size": hist["file_size_bytes"].map(fmt_bytes),
            "Records in file": hist["rows_in_file"],
            "Records added": hist["rows_written"],
            "Skipped (existing)": hist["rows_skipped"],
            "Uploaded by": hist["uploaded_by"],
            "Upload date": local.map(lambda t: f"{t:%d-%b-%Y}"),
            "Upload time": local.map(lambda t: f"{t:%I:%M %p}"),
            "Status": hist["reverted_at"].map(lambda t: "" if pd.isna(t) else f"Reverted {fmt_datetime(t)}"),
        }
    )


def last_upload_text(category: str) -> str:
    hist = db.get_upload_history(category, 1)
    if hist.empty:
        return "No uploads yet"
    row = hist.iloc[0]
    return f"{fmt_datetime(row['uploaded_at'])} · {row['file_name']} ({int(row['rows_written']):,} added)"


def log_upload(category, f, rows_in_file, rows_written, rows_skipped, list_name, list_id=None):
    """Record an import that added no rows in upload_history (never blocks the import)."""
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
            list_id=list_id,
        )
    except Exception as e:
        st.warning(f"Your leads were imported, but this upload couldn't be added to the upload history ({e}).")


def upload_meta(f, rows_in_file, list_name, **extra):
    """What the database logs about a merge (written in the same transaction as its rows)."""
    return dict(file_name=f.name, file_size_bytes=get_upload_size(f), rows_in_file=rows_in_file,
                list_name=list_name, uploaded_by=(auth.current_user() or {}).get("email"), **extra)


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


def uploader_key(base: str) -> str:
    """Widget key for an import uploader. Bumping its version gives Streamlit a new,
    empty widget — the only reliable way to clear a file_uploader."""
    return f"{base}_{st.session_state.get(f'{base}_version', 0)}"


def finish_import(base: str, messages: list, clear_uploader: bool) -> None:
    """Rerun after an import (refreshing the counts), keeping the result messages so
    they still show afterwards. The uploader is emptied only when clear_uploader is
    set, i.e. every selected file was imported; otherwise the files stay for a retry."""
    if clear_uploader:
        st.session_state[f"{base}_version"] = st.session_state.get(f"{base}_version", 0) + 1
    st.session_state[f"{base}_flash"] = messages
    st.rerun()


def show_import_messages(base: str) -> None:
    """Show the messages saved by finish_import (once)."""
    for level, text in st.session_state.pop(f"{base}_flash", []):
        getattr(st, level)(text)


def upload_limits_caption():
    st.caption(
        f"Accepted: CSV, Excel (XLSX/XLS), ZIP or GZ · up to {fmt_bytes(MAX_UNCOMPRESSED_UPLOAD_BYTES)} "
        f"({fmt_bytes(MAX_COMPRESSED_UPLOAD_BYTES)} if compressed). You can select several files at once."
    )


def show_history(category: str) -> None:
    """Upload history table, or a friendly empty state."""
    try:
        table = history_table(category)
    except Exception as e:
        theme.friendly_error("Couldn't load the upload history", "Try refreshing the page.", e)
        return
    if table.empty:
        theme.empty_state("🕒", "No uploads yet", "Your completed uploads will appear here.")
    else:
        st.dataframe(table, width="stretch", hide_index=True)


def pick_target_list(existing_names, key_prefix):
    """Selectbox to choose an existing list or create a new one. Returns the name."""
    choice = st.selectbox(
        "Add to which list?",
        [NEW_LIST_LABEL] + list(existing_names),
        key=f"{key_prefix}_choice",
        help="Pick an existing list to add to, or create a new one. Lists help you keep uploads organised.",
    )
    if choice == NEW_LIST_LABEL:
        return st.text_input(
            "New list name",
            value="",
            placeholder="e.g. Q1 2025 Campaign",
            key=f"{key_prefix}_newname",
        )
    return choice


def fmt_date(ts) -> str:
    return "—" if ts is None or pd.isna(ts) else f"{_to_local(ts):%d-%b-%Y}"


def _delete_list(category, list_id):
    if category == "master":
        db.delete_master_list(list_id)
    else:
        db.delete_email_list(category, list_id)


@st.dialog("Delete this file?")
def confirm_delete_file(category, list_id, name, rows, noun):
    st.markdown(f"**{html.escape(str(name))}** and all **{rows:,} {noun}** in it will be permanently deleted.")
    st.warning("This can't be undone. Its entries stay in the upload history.", icon="⚠️")
    yes, no = st.columns(2)
    if yes.button("🗑️ Delete permanently", key="del_confirm_file", type="primary", width="stretch"):
        try:
            _delete_list(category, list_id)
        except Exception as e:
            theme.friendly_error("Couldn't delete this file", "Nothing was deleted. Please try again.", e)
            return
        st.toast(f"Deleted '{name}' ({rows:,} {noun}).", icon="🗑️")
        st.rerun()
    if no.button("Cancel", key="reset_cancel_delete", width="stretch"):
        st.rerun()


@st.dialog("Revert this merge?")
def confirm_revert(upload_id, file_name, list_name, added, noun, when):
    st.markdown(
        f"This removes the **{added:,} {noun}** that **{html.escape(str(file_name))}** added to "
        f"**{html.escape(str(list_name))}** on {when}."
    )
    st.caption("Leads added by other merges, and leads that were already in the file, are not affected.")
    st.warning("This can't be undone.", icon="⚠️")
    yes, no = st.columns(2)
    if yes.button("↩️ Revert merge", key="del_confirm_revert", type="primary", width="stretch"):
        try:
            removed = db.revert_upload(upload_id)
        except Exception as e:
            theme.friendly_error("Couldn't revert this merge", "Nothing was changed. Please try again.", e)
            return
        st.toast(f"Merge reverted: {removed:,} {noun} removed from '{list_name}'.", icon="↩️")
        st.rerun()
    if no.button("Cancel", key="reset_cancel_revert", width="stretch"):
        st.rerun()


def _table_header(cols, labels):
    for col, label in zip(cols, labels):
        if label:
            col.markdown(f"**{label}**")


def render_files(category, lists_df, count_col, noun, storage_bytes, stored_rows):
    """One row per file (saved list): created date, rows, approximate size, merges, delete."""
    if lists_df.empty:
        theme.empty_state("📭", "No files yet", "Upload a file above to create your first one.")
        return
    try:
        merges = db.get_merge_counts(category)
    except Exception:
        merges = {}
    per_row = storage_bytes / stored_rows if storage_bytes and stored_rows else None
    widths = [4, 2, 2, 2, 1.5, 1.8]
    st.caption(f"{len(lists_df)} file(s) · {int(lists_df[count_col].sum()):,} {noun} total. "
               "Size is the approximate space the file uses in the database.")
    _table_header(st.columns(widths), ["File", "Created", noun.capitalize(), "Size", "Merges", ""])
    for row in lists_df.itertuples():
        rows = int(getattr(row, count_col))
        c = st.columns(widths, vertical_alignment="center")
        c[0].markdown(f"**{html.escape(str(row.name))}**")
        c[1].write(fmt_date(row.created_at))
        c[2].write(f"{rows:,}")
        c[3].write(f"≈ {fmt_bytes(rows * per_row)}" if per_row else "—")
        c[4].write(f"{merges.get(int(row.id), 0):,}")
        if c[5].button("🗑️ Delete", key=f"del_file_{category}_{row.id}", type="primary", width="stretch",
                       help=f"Permanently delete this file and its {rows:,} {noun}. You'll be asked to confirm."):
            confirm_delete_file(category, int(row.id), row.name, rows, noun)


def render_merge_history(category, lists_df, noun):
    """Every merge into one chosen file, with a revert button for each."""
    if lists_df.empty:
        theme.empty_state("🔀", "No files yet", "Merges appear here once you add a file.")
        return
    names = {int(r.id): r.name for r in lists_df.itertuples()}
    list_id = st.selectbox(
        "Choose a file", list(names), format_func=lambda i: names.get(i, str(i)), key=f"merge_file_{category}",
        help="Shows every upload that was merged into this file.",
    )
    try:
        merges = db.get_list_merges(category, list_id)
    except Exception as e:
        theme.friendly_error("Couldn't load the merge history", "Try refreshing the page.", e)
        return
    if merges.empty:
        theme.empty_state("🔀", "No merges recorded for this file", "Merges appear here after you add a file to it.")
        return
    widths = [2.2, 3.5, 1.6, 2.6, 2.4, 1.8]
    _table_header(st.columns(widths), ["Merged on", "File merged", noun.capitalize() + " added", "By", "Status", ""])
    for m in merges.itertuples():
        c = st.columns(widths, vertical_alignment="center")
        added = int(m.rows_written or 0)
        c[0].write(fmt_datetime(m.uploaded_at))
        c[1].write(str(m.file_name))
        c[2].write(f"{added:,}")
        c[3].write(m.uploaded_by or "—")
        if not pd.isna(m.reverted_at):
            c[4].write(f"↩️ Reverted {fmt_date(m.reverted_at)}")
        elif added == 0:
            c[4].write("Nothing added")
        elif pd.isna(m.batch_created_at):
            c[4].markdown("Can't be reverted", help="This merge was recorded before revert was available, and "
                          "its rows couldn't be matched with certainty, so it can't be reverted safely.")
        else:
            c[4].write("✅ In the file")
            if c[5].button("↩️ Revert", key=f"del_revert_{m.id}", type="primary", width="stretch",
                           help=f"Remove the {added:,} {noun} this merge added. You'll be asked to confirm."):
                confirm_revert(int(m.id), m.file_name, names[list_id], added, noun, fmt_datetime(m.uploaded_at))


# ============================================================================ #
# Live counts (queried from the database, never from session/upload state)
# ============================================================================ #
try:
    COUNTS = db.get_category_counts()
except Exception as e:
    theme.friendly_error("Couldn't read your lead counts", "The numbers below may show 0. Try refreshing the page.", e)
    COUNTS = {c: {"lists": 0, "rows": 0, "unique": 0} for c in db.ALL_CATEGORIES}

# At-a-glance dashboard (live database counts + this session's campaign file).
dash = st.columns(5)
dash[0].metric("🗂️ Master leads", f"{COUNTS['master']['unique']:,}",
               help="Total unique leads stored in your main database.")
dash[1].metric("🎯 MQL leads", f"{COUNTS['mql']['unique']:,}",
               help="Leads already marked as marketing-qualified.")
dash[2].metric("🚫 Bounced emails", f"{COUNTS['bounce']['unique']:,}",
               help="Emails that bounced in past campaigns.")
dash[3].metric("✋ Unsubscribed", f"{COUNTS['unsub']['unique']:,}",
               help="People who asked not to be contacted.")
_campaign = st.session_state.get("cleaned_df")
dash[4].metric("📣 Final Campaign", f"{len(_campaign):,}" if _campaign is not None else "—",
               help="Clean leads waiting to be downloaded on the Clean Leads page in this session.")


def _tab_label(icon, label, cat):
    return f"{icon}  {label} ({COUNTS[cat]['unique']:,})"


tab_master, tab_mql, tab_bounce, tab_unsub = st.tabs(
    [
        _tab_label("🗂️", "Master leads", "master"),
        _tab_label("🎯", "MQL", "mql"),
        _tab_label("🚫", "Bounced", "bounce"),
        _tab_label("✋", "Unsubscribed", "unsub"),
    ]
)


# ---------------------------------------------------------------------------- #
# MASTER FILE
# ---------------------------------------------------------------------------- #
with tab_master:
    theme.section_header(
        "01-Overview", "Master leads",
        "Your main database of leads. Anyone in here can be skipped automatically when you clean a new file.",
    )
    m = COUNTS["master"]
    try:
        stor = db.get_storage_info()
    except Exception as e:
        stor = None
        st.warning(f"Storage details are unavailable right now ({e}).")

    c1, c2, _, _ = st.columns(4)
    c1.metric("📧 Leads (unique emails)", f"{m['unique']:,}", help="Each email address is counted once.")
    c2.metric("📋 Lists", f"{m['lists']:,}", help="Named groups your Master leads are saved in.")

    if m["rows"] > m["unique"]:
        st.info(
            f"**{m['rows'] - m['unique']:,} email(s) appear in more than one Master list.** "
            "That's fine — each is counted once, and new uploads never add an email that's already saved."
        )

    with st.expander("💾 Storage & upload limits", expanded=False):
        c3, c4 = st.columns(2)
        c3.metric("🗄️ Database size", fmt_bytes(stor["database_bytes"]) if stor else "—")
        c4.metric("🗂️ Master leads storage", fmt_bytes(stor["master_bytes"]) if stor else "—")

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
    theme.section_header(
        "02-Add leads", "Add leads to your Master database",
        "Upload one or more files. New leads are added; leads already saved (same email) are skipped. "
        "Nothing already in your database is changed or deleted.",
    )

    show_import_messages("master_import_files")
    master_files = st.file_uploader(
        "Master file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key=uploader_key("master_import_files"),
        max_upload_size=MAX_COMPRESSED_UPLOAD_BYTES // MB,
    )
    upload_limits_caption()
    if master_files:
        st.caption("Selected: " + " · ".join(f"{f.name} ({fmt_bytes(get_upload_size(f))})" for f in master_files))

    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        st.warning(f"Couldn't load your Master lists ({e}). You can still create a new one.")
    master_names = master_lists_df["name"].tolist() if not master_lists_df.empty else []

    master_target = pick_target_list(master_names, "master_target")

    if st.button("📥  Add to Master database", type="primary", key="save_import_master",
                 help="Adds only the new leads from your file(s). Leads already saved are skipped."):
        clean_name = (master_target or "").strip()
        if not master_files:
            st.error("Choose at least one file first — drag it into the box above or click **Browse files**.")
        elif not clean_name:
            st.error("Enter a name for the new list, or pick an existing list.")
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
                            forget_file(f)
                            continue

                        # --- Global dedup, server-side --------------------------
                        # Only the emails that already exist anywhere in the Master
                        # database come back (COPY into a temp table + indexed join).
                        with st.spinner(f"Checking {len(records):,} leads against your Master database…"):
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
                                f"**{f.name}**: {dedup_skipped:,} lead(s) are already saved (or repeated in the file) "
                                f"and will be skipped. {len(records):,} new leads will be added."
                            )

                        written = 0
                        if records:
                            with st.spinner(f"Saving {len(records):,} new leads from {f.name}…"):
                                # Logged in upload_history in the same transaction, so it can be reverted.
                                written = db.upsert_master_contacts(
                                    list_id, records,
                                    upload=upload_meta(f, rows_in_file, clean_name, rows_skipped=dedup_skipped),
                                )
                                written_total += written
                        else:
                            log_upload("master", f, rows_in_file, 0, dedup_skipped, clean_name, list_id)
                        del fdf, records, emails, existing
                        forget_file(f)

                    messages = []
                    if skipped_files:
                        messages.append(("warning",
                            "**Some files were skipped** — we couldn't find an email column in: "
                            + ", ".join(skipped_files)
                            + ". Check that each file has a column of email addresses, then try again."
                        ))
                    if written_total:
                        messages.append(("success",
                            f"✅ **Upload complete** — {written_total:,} new leads were added to Master list "
                            f"**'{clean_name}'**. Master database: {before_total:,} → {before_total + written_total:,} leads"
                            + (f" ({dedup_skipped_total:,} already saved, skipped)." if dedup_skipped_total else ".")
                        ))
                    elif not skipped_files:
                        if dedup_skipped_total:
                            messages.append(("info",
                                f"**Upload complete** — all {dedup_skipped_total:,} leads are already in your "
                                "Master database, so there was nothing new to add."
                            ))
                        else:
                            messages.append(("warning",
                                "**No email addresses found.** The file has an email column, but it's empty. "
                                "Check the file and try again."
                            ))
                    # Done = every file had an Email column and at least one valid email.
                    done = not skipped_files and bool(written_total or dedup_skipped_total)
                    if written_total or done:
                        finish_import("master_import_files", messages, clear_uploader=done)
                    for level, text in messages:
                        getattr(st, level)(text)
                except Exception as e:
                    theme.friendly_error(
                        "Upload could not be completed",
                        "Some leads may not have been added. Your file is still selected — check it and click "
                        "the button again (leads that were already added will simply be skipped).",
                        e,
                    )

    st.divider()
    theme.section_header("03-Your files", "Your files", "Every Master file with its size and how many uploads were merged into it.")
    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        theme.friendly_error("Couldn't load your Master files", "Try refreshing the page.", e)
    render_files("master", master_lists_df, "contact_count", "leads",
                 stor["master_bytes"] if stor else None, m["rows"])

    st.divider()
    theme.section_header("04-Merges", "Merge history", "Every upload merged into a file. Revert a merge to remove the leads it added.")
    render_merge_history("master", master_lists_df, "leads")

    st.divider()
    theme.section_header("05-History", "Upload history", "Every file added to your Master database.")
    show_history("master")


# ---------------------------------------------------------------------------- #
# MQL / BOUNCE / UNSUB — email-only categories, same UI each
# ---------------------------------------------------------------------------- #
def render_email_category(category: str):
    label, icon, description = EMAIL_CATEGORIES[category]
    cnt = COUNTS[category]

    theme.section_header("01-Overview", f"{label}", description.split(" Only")[0])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{icon} Emails", f"{cnt['unique']:,}", help="Each email address is counted once.")
    c2.metric("📋 Lists", f"{cnt['lists']:,}")
    try:
        c3.metric("🕒 Last Upload", last_upload_text(category))
    except Exception:
        c3.metric("🕒 Last Upload", "—")

    st.divider()
    theme.section_header(
        "02-Add emails", f"Add to {label}",
        description + " Emails already saved are skipped; nothing is changed or deleted.",
    )

    uploader_base = f"{category}_import_files"
    show_import_messages(uploader_base)
    files = st.file_uploader(
        f"{label} file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key=uploader_key(uploader_base),
        max_upload_size=MAX_COMPRESSED_UPLOAD_BYTES // MB,
    )
    upload_limits_caption()
    if files:
        st.caption("Selected: " + " · ".join(f"{f.name} ({fmt_bytes(get_upload_size(f))})" for f in files))

    try:
        lists_df = db.get_email_lists(category)
    except Exception as e:
        lists_df = pd.DataFrame()
        st.warning(f"Couldn't load your {label} lists ({e}). You can still create a new one.")
    names = lists_df["name"].tolist() if not lists_df.empty else []

    target = pick_target_list(names, f"{category}_target")

    if st.button(f"📥  Add to {label}", type="primary", key=f"save_import_{category}",
                 help="Saves the email addresses from your file(s). Emails already saved are skipped."):
        clean_name = (target or "").strip()
        if not files:
            st.error("Choose at least one file first — drag it into the box above or click **Browse files**.")
        elif not clean_name:
            st.error("Enter a name for the new list, or pick an existing list.")
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
                            forget_file(f)
                            continue
                        with st.spinner(f"Saving {len(emails):,} emails from {f.name}…"):
                            # Logged in upload_history in the same transaction, so it can be reverted.
                            written = db.upsert_emails(category, list_id, emails.tolist(),
                                                       upload=upload_meta(f, rows_in_file, clean_name))
                        written_total += written
                        del fdf, emails
                        forget_file(f)
                    messages = []
                    if skipped_files:
                        messages.append(("warning",
                            "**Some files were skipped** — we couldn't find any email addresses in: "
                            + ", ".join(skipped_files)
                            + ". Check that each file has a column of email addresses, then try again."
                        ))
                    if written_total:
                        messages.append(("success",
                            f"✅ **Upload complete** — {written_total:,} emails were added to {label} list '{clean_name}'."))
                    elif not skipped_files:
                        messages.append(("info",
                            f"**Upload complete** — no new emails were added. Every email in the file is already in "
                            f"{label} list '{clean_name}' (the upload is still recorded in the history)."
                        ))
                    if written_total or not skipped_files:
                        finish_import(uploader_base, messages, clear_uploader=not skipped_files)
                    for level, text in messages:
                        getattr(st, level)(text)
                except Exception as e:
                    theme.friendly_error(
                        "Upload could not be completed",
                        "Some emails may not have been added. Your file is still selected — check it and click "
                        "the button again (emails that were already added will simply be skipped).",
                        e,
                    )

    st.divider()
    theme.section_header("03-Your files", "Your files", f"Every {label} file with its size and how many uploads were merged into it.")
    try:
        lists_df = db.get_email_lists(category)
    except Exception as e:
        lists_df = pd.DataFrame()
        theme.friendly_error(f"Couldn't load your {label} files", "Try refreshing the page.", e)
    try:
        stor = db.get_storage_info()
    except Exception:
        stor = None
    render_files(category, lists_df, "email_count", "emails",
                 stor[f"{category}_bytes"] if stor else None, cnt["rows"])

    st.divider()
    theme.section_header("04-Merges", "Merge history", "Every upload merged into a file. Revert a merge to remove the emails it added.")
    render_merge_history(category, lists_df, "emails")

    st.divider()
    theme.section_header("05-History", "Upload history", f"Every file added to {label}.")
    show_history(category)


with tab_mql:
    render_email_category("mql")

with tab_bounce:
    render_email_category("bounce")

with tab_unsub:
    render_email_category("unsub")

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

A search box above the tabs finds an email in all four categories at once, and the
MQL tab can switch to a paged List view of its records.

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
    group_download_name,
    keyword_regex,
    keyword_terms,
    load_file,
    safe_filename,
    validate_upload,
)
st.set_page_config(
    page_title="Lead Database — LeadFlow",
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

theme.page_header(
    "database", "Lead Database",
    "Search, add and manage your saved lists. Leads on these lists can be removed when you clean a file.",
)

# --- Ensure the database is reachable ----------------------------------------
_ok, _err = db.init_db()
if not _ok:
    st.error("**The lead database isn't reachable right now.** Your lists can't be shown or changed until it's back.",
             icon=":material/error:")
    with st.expander("How to fix this", expanded=True):
        st.markdown(
            "1. Make sure **PostgreSQL is running**.\n"
            "2. Check your connection settings in `.streamlit/secrets.toml` "
            "(host, port, dbname, user, password).\n"
            "3. See the **README** for full setup steps.\n\n"
            f"**Technical details:** `{_err}`"
        )
        if st.button("Retry database connection", key="retry_db_conn", icon=":material/refresh:"):
            st.rerun()
    st.stop()

_cfg = db.get_config()


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

NEW_LIST_LABEL = "+ Create a new list…"

EMAIL_CATEGORIES = {
    # key: (tab label, icon, description shown above the uploader)
    "mql": ("MQL", "ads_click", "Leads already marked as marketing-qualified."),
    "bounce": ("Bounced", "block", "Emails that bounced in past campaigns."),
    "unsub": ("Unsubscribed", "unsubscribe", "People who asked not to be contacted."),
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
            "Status": hist["reverted_at"].map(lambda t: "Added" if pd.isna(t) else f"Undone {fmt_datetime(t)}"),
        }
    )


NO_UPLOADS_TEXT = "No uploads yet"


def last_upload_metric(col, category: str) -> None:
    """'Last upload' metric: just the date (fits the card), with the full detail in its tooltip."""
    try:
        text = last_upload_text(category)
    except Exception:
        col.metric("Last upload", "—")
        return
    if text == NO_UPLOADS_TEXT:
        col.metric("Last upload", "—", help=text)
        return
    col.metric("Last upload", text.split(",")[0].split(" · ")[0], help=text)


def last_upload_text(category: str) -> str:
    hist = db.get_upload_history(category, 1)
    if hist.empty:
        return NO_UPLOADS_TEXT
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
        f"CSV, XLSX, XLS, ZIP or GZ · up to {fmt_bytes(MAX_UNCOMPRESSED_UPLOAD_BYTES)} "
        f"({fmt_bytes(MAX_COMPRESSED_UPLOAD_BYTES)} if compressed) · you can select several files at once"
    )


def show_history(category: str) -> None:
    """Upload history table, or a friendly empty state."""
    try:
        table = history_table(category)
    except Exception as e:
        theme.friendly_error("Couldn't load the upload history", "Try refreshing the page.", e)
        return
    if table.empty:
        theme.empty_state("history", "No uploads yet", "Files you add above will be listed here.")
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


@st.dialog("Delete this list?")
def confirm_delete_file(category, list_id, name, rows, noun):
    st.markdown(f"**{html.escape(str(name))}** and all **{rows:,} {noun}** in it will be permanently deleted.")
    st.warning("This can't be undone. Its entries stay in the upload history.", icon=":material/warning:")
    yes, no = st.columns(2)
    if yes.button("Delete permanently", key="del_confirm_file", type="primary", width="stretch", icon=":material/delete:"):
        try:
            _delete_list(category, list_id)
        except Exception as e:
            theme.friendly_error("Couldn't delete this list", "Nothing was deleted. Please try again.", e)
            return
        st.toast(f"Deleted '{name}' ({rows:,} {noun}).", icon=":material/delete:")
        st.rerun()
    if no.button("Keep it", key="reset_cancel_delete", width="stretch"):
        st.rerun()


@st.dialog("Undo this upload?")
def confirm_revert(upload_id, file_name, list_name, added, noun, when):
    st.markdown(
        f"This removes the **{added:,} {noun}** that **{html.escape(str(file_name))}** added to "
        f"**{html.escape(str(list_name))}** on {when}."
    )
    st.caption("Leads added by other uploads, and leads that were already in the list, are not affected.")
    st.warning("This can't be undone.", icon=":material/warning:")
    yes, no = st.columns(2)
    if yes.button("Undo upload", key="del_confirm_revert", type="primary", width="stretch", icon=":material/undo:"):
        try:
            removed = db.revert_upload(upload_id)
        except Exception as e:
            theme.friendly_error("Couldn't undo this upload", "Nothing was changed. Please try again.", e)
            return
        st.toast(f"Upload undone: {removed:,} {noun} removed from '{list_name}'.", icon=":material/undo:")
        st.rerun()
    if no.button("Keep it", key="reset_cancel_revert", width="stretch"):
        st.rerun()


def render_files(category, lists_df, count_col, noun, storage_bytes, stored_rows):
    """One row per saved list: created date, rows, approximate size, merges, delete."""
    if lists_df.empty:
        theme.empty_state("inbox", "No lists yet", "Add a file above to create your first list.")
        return
    try:
        merges = db.get_merge_counts(category)
    except Exception:
        merges = {}
    per_row = storage_bytes / stored_rows if storage_bytes and stored_rows else None
    widths = [4, 2, 2, 2, 1.5, 1.8]
    st.caption(f"{len(lists_df)} list(s) · {int(lists_df[count_col].sum()):,} {noun} in total. "
               "Size is the approximate space each list uses in the database.")
    heads = ["List", "Created", noun.capitalize(), "Size", "Uploads", ""]
    theme.table_header(f"list_{category}", widths, heads)
    for row in lists_df.itertuples():
        rows = int(getattr(row, count_col))
        c = theme.table_row(f"list_{category}_{row.id}", widths)
        theme.table_cell(c[0], heads[0], row.name, strong=True)
        theme.table_cell(c[1], heads[1], fmt_date(row.created_at))
        theme.table_cell(c[2], heads[2], f"{rows:,}")
        theme.table_cell(c[3], heads[3], f"≈ {fmt_bytes(rows * per_row)}" if per_row else "—")
        theme.table_cell(c[4], heads[4], f"{merges.get(int(row.id), 0):,}")
        if c[5].button("Delete", key=f"del_file_{category}_{row.id}", width="stretch", icon=":material/delete:",
                       help=f"Permanently delete this list and its {rows:,} {noun}. You'll be asked to confirm."):
            confirm_delete_file(category, int(row.id), row.name, rows, noun)


def render_merge_history(category, lists_df, noun):
    """Every merge into one chosen list, with a revert button for each."""
    if lists_df.empty:
        theme.empty_state("history", "No lists yet", "Uploads appear here once you add a file.")
        return
    names = {int(r.id): r.name for r in lists_df.itertuples()}
    list_id = st.selectbox(
        "List", list(names), format_func=lambda i: names.get(i, str(i)), key=f"merge_file_{category}",
        help="Shows every upload that was merged into this list.",
    )
    try:
        merges = db.get_list_merges(category, list_id)
    except Exception as e:
        theme.friendly_error("Couldn't load the merge history", "Try refreshing the page.", e)
        return
    if merges.empty:
        theme.empty_state("history", "No uploads recorded for this list", "Uploads appear here after you add a file to it.")
        return
    widths = [2.2, 3.5, 1.6, 2.6, 2.4, 1.8]
    heads = ["Uploaded", "File", noun.capitalize() + " added", "By", "Status", ""]
    theme.table_header(f"merge_{category}", widths, heads)
    for m in merges.itertuples():
        c = theme.table_row(f"merge_{category}_{m.id}", widths)
        added = int(m.rows_written or 0)
        theme.table_cell(c[0], heads[0], fmt_datetime(m.uploaded_at))
        theme.table_cell(c[1], heads[1], m.file_name, strong=True)
        theme.table_cell(c[2], heads[2], f"{added:,}")
        theme.table_cell(c[3], heads[3], m.uploaded_by or "—")
        if not pd.isna(m.reverted_at):
            theme.table_cell(c[4], heads[4], f"Undone {fmt_date(m.reverted_at)}", icon_name="undo")
        elif added == 0:
            theme.table_cell(c[4], heads[4], "Nothing added")
        elif pd.isna(m.batch_created_at):
            c[4].markdown("Can't be undone", help="This upload was recorded before undo was available, and "
                          "its rows couldn't be matched with certainty, so it can't be undone safely.")
        else:
            theme.table_cell(c[4], heads[4], "In the list", icon_name="check")
            if c[5].button("Undo", key=f"del_revert_{m.id}", width="stretch", icon=":material/undo:",
                           help=f"Remove the {added:,} {noun} this upload added. You'll be asked to confirm."):
                confirm_revert(int(m.id), m.file_name, names[list_id], added, noun, fmt_datetime(m.uploaded_at))


MASTER_SEARCH_LIMIT = 500_000


def render_master_search(result):
    """Master search results grouped by the searched field's value, with downloads for all
    results or one group at a time (named after the group, e.g. Real_Estate.csv)."""
    if not result:
        return
    field, terms = result["field"], result["terms"]
    found = result["df"].rename(columns={v: k for k, v in MASTER_FIELD_MAP.items()})
    found = found[[c for c in MASTER_FIELD_MAP if c in found.columns]]
    if len(found) > MASTER_SEARCH_LIMIT:
        found = found.head(MASTER_SEARCH_LIMIT)
        st.warning(f"More than {MASTER_SEARCH_LIMIT:,} leads match — showing and downloading the first "
                   f"{MASTER_SEARCH_LIMIT:,}. Narrow your search to get the rest.")
    if found.empty:
        theme.empty_state("search_off", "No matching leads",
                          f"No Master lead's {field} matches “{html.escape(', '.join(terms))}”.")
        return

    values = found[field].fillna("").astype(str).str.strip()
    group_series = values.replace("", "Unknown")
    group_counts = group_series.value_counts().to_dict()
    ordered_groups = [k for k, _ in sorted(group_counts.items(), key=lambda x: -x[1])]
    per_term = " · ".join(
        f"<b>{html.escape(t)}</b> {int(values.str.contains(keyword_regex(t), case=False, regex=True).sum()):,}"
        for t in terms
    )
    theme.status_line(
        "success", f"{len(found):,} leads found in {len(ordered_groups):,} {html.escape(field)} groups",
        f"Per search value: {per_term}" if len(terms) > 1 else "",
    )

    safe_field = field.lower().replace(" ", "_")
    all_col, one_sel, one_dl = st.columns([1.2, 1.6, 1.2], vertical_alignment="bottom")
    all_col.caption(f"Downloads as {group_download_name(field, ordered_groups)}")
    all_col.download_button(
        f"Download all ({len(found):,} leads)",
        icon=":material/download:",
        data=lambda df=found: df.to_csv(index=False).encode("utf-8"),
        file_name=group_download_name(field, ordered_groups),
        mime="text/csv", type="primary", key=f"dl_master_search_all_{safe_field}", width="stretch",
    )
    if len(ordered_groups) > 1:
        one_group = one_sel.selectbox("Or download one group", ordered_groups, key=f"master_search_one_{safe_field}",
                                      format_func=lambda g: f"{g} ({group_counts[g]:,} leads)")
        one_df = found[group_series == one_group]
        one_dl.download_button(
            f"Download {one_group} ({group_counts[one_group]:,})",
            icon=":material/download:",
            data=lambda df=one_df: df.to_csv(index=False).encode("utf-8"),
            file_name=group_download_name(field, [one_group]),
            mime="text/csv", key=f"dl_master_search_one_{safe_field}", width="stretch",
        )
    st.dataframe(
        pd.DataFrame({field: ordered_groups, "Leads": [group_counts[g] for g in ordered_groups]}),
        width="stretch", hide_index=True, height=min(35 * (len(ordered_groups) + 1) + 3, 320),
    )


# ============================================================================ #
# Live counts (queried from the database, never from session/upload state)
# ============================================================================ #
try:
    COUNTS = db.get_category_counts()
except Exception as e:
    theme.friendly_error("Couldn't read your lead counts", "The numbers below may show 0. Try refreshing the page.", e)
    COUNTS = {c: {"lists": 0, "rows": 0, "unique": 0} for c in db.ALL_CATEGORIES}


def _tab_label(label, cat):
    return f"{label} ({COUNTS[cat]['unique']:,})"


TAB_NAMES = {"master": "Master leads", "mql": "MQL", "bounce": "Bounced", "unsub": "Unsubscribed"}
TAB_LABELS = {cat: _tab_label(name, cat) for cat, name in TAB_NAMES.items()}
DB_TAB_KEY = "db_tab"
MQL_VIEWS = ("Standard view", "List view")

# Tab labels carry live counts, so a remembered tab can name an old count after an import.
# Point it at the same category's current label instead of falling back to the first tab.
_remembered_tab = st.session_state.get(DB_TAB_KEY)
if _remembered_tab and _remembered_tab not in TAB_LABELS.values():
    for _cat, _name in TAB_NAMES.items():
        if str(_remembered_tab).startswith(f"{_name} ("):
            st.session_state[DB_TAB_KEY] = TAB_LABELS[_cat]
            break


# ---------------------------------------------------------------------------- #
# GLOBAL EMAIL SEARCH — every category at once, whichever tab is open
# ---------------------------------------------------------------------------- #
GLOBAL_SEARCH_LIMIT = 200  # rows shown per category


GLOBAL_SEARCH_CAT_KEY = "global_search_cat"
# The lists that stop you contacting someone come first: they are what a search is usually for.
SEARCH_ORDER = ("unsub", "bounce", "mql", "master")
SEARCH_SHOW_ALL_UP_TO = 50  # this few matches fit in one table, so they open together


def clear_global_search():
    """Button callback: empty the search box and forget the results."""
    st.session_state["global_email_query"] = ""
    st.session_state.pop("global_email_search", None)
    st.session_state.pop(GLOBAL_SEARCH_CAT_KEY, None)


def _added_date(ts):
    """Day a record was saved, in the viewer's time zone, as a real date so the column sorts by date."""
    return None if ts is None or pd.isna(ts) else _to_local(ts).date()


def render_global_search_results(result):
    if not result:
        return
    query, found, counts = result["query"], result["df"], result["counts"]
    if found.empty:
        theme.empty_state("search_off", "No matching emails",
                          f"No email containing “{html.escape(query)}” is saved in Master, MQL, Unsubscribed or Bounce.")
        return
    total = sum(counts.values())
    risky = counts["bounce"] + counts["unsub"]
    theme.status_line(
        "warning" if risky else "info",
        f"{total:,} {'match' if total == 1 else 'matches'} for “{html.escape(query)}”",
        f"{risky:,} on Bounce or Unsubscribed — don't contact these." if risky
        else "None on Bounce or Unsubscribed.",
    )

    # One category at a time, so a few Bounce matches never sit below hundreds of Master rows.
    # A handful of matches (e.g. one exact address) is shown together under "All".
    hit_cats = [c for c in SEARCH_ORDER if counts[c]]
    options = (["all"] if total <= SEARCH_SHOW_ALL_UP_TO and len(hit_cats) > 1 else []) + hit_cats
    cat = st.segmented_control(
        "Show matches in", options, default=options[0], required=True, key=GLOBAL_SEARCH_CAT_KEY,
        format_func=lambda c: f"All ({total:,})" if c == "all" else f"{db.CATEGORY_LABELS[c]} ({counts[c]:,})",
    )
    if cat == "all":
        view = found.sort_values("category", key=lambda s: s.map(SEARCH_ORDER.index), kind="stable")
    else:
        view = found[found["category"] == cat]
        if counts[cat] > len(view):
            st.caption(f"First {len(view):,} of {counts[cat]:,} shown. Type more of the address to narrow it down.")

    table = {}
    if cat == "all":
        table["Category"] = view["category_label"]
    table["Email"] = view["email"]
    table["List"] = view["list_name"]
    if (view["category"] == "master").any():  # only Master records carry a name and company
        name = (view["first_name"].fillna("") + " " + view["last_name"].fillna("")).str.strip()
        table["Name"] = name.where(name != "", None)
        table["Company"] = view["company"]
    table["Added"] = view["created_at"].map(_added_date)
    st.dataframe(
        pd.DataFrame(table),
        width="stretch", hide_index=True, height=min(35 * (len(view) + 1) + 3, 420),
        column_config={
            "Category": st.column_config.TextColumn("Category", width="small"),
            "Email": st.column_config.TextColumn("Email", width="large"),
            "List": st.column_config.TextColumn("List", width="small"),
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Company": st.column_config.TextColumn("Company", width="large"),
            "Added": st.column_config.DateColumn("Added", format="D MMM YYYY", width="small"),
        },
    )
    _search_downloads(query, counts)


def _search_csv(query, counts, category=None):
    """Every match for `query` as CSV (not just the rows shown), for one category or all of them.
    Runs only when the download is clicked, so a broad search doesn't fetch its rows on every rerun."""
    found, _ = db.search_email_everywhere(query, limit_per_category=max(counts.values()))
    if category:
        found = found[found["category"] == category]
    found = found.sort_values("category", key=lambda s: s.map(SEARCH_ORDER.index), kind="stable")
    out = pd.DataFrame({
        "Category": found["category_label"],
        "Email": found["email"],
        "List": found["list_name"],
        "First Name": found["first_name"],
        "Last Name": found["last_name"],
        "Company": found["company"],
        "Job Title": found["job_title"],
        "Added": found["created_at"].map(_added_date),
    })
    if category:
        out = out.drop(columns="Category")
    if category != "master" and not (found["category"] == "master").any():
        out = out.drop(columns=["First Name", "Last Name", "Company", "Job Title"])
    return out.to_csv(index=False).encode("utf-8")


def _search_downloads(query, counts):
    """Download every match in one file, or each category's matches on their own."""
    total = sum(counts.values())
    hit_cats = [c for c in SEARCH_ORDER if counts[c]]
    stem = f"email_search_{safe_filename(query, 'results')}"
    st.caption("Download every match as CSV — not just the rows shown above:")
    # One category alone needs no second button: "all" is already that category.
    per_cat = hit_cats if len(hit_cats) > 1 else []
    cols = st.columns(4 if len(per_cat) < 4 else 5)
    cols[0].download_button(
        f"All matches ({total:,})", icon=":material/download:", type="primary", width="stretch",
        data=lambda: _search_csv(query, counts), file_name=f"{stem}.csv", mime="text/csv",
        key="dl_global_search_all",
        help="Every match in every category as one CSV, with a Category column.",
    )
    for col, c in zip(cols[1:], per_cat):
        label = db.CATEGORY_LABELS[c]
        col.download_button(
            f"{label} ({counts[c]:,})", icon=":material/download:", width="stretch",
            data=lambda c=c: _search_csv(query, counts, c),
            file_name=f"{stem}_{safe_filename(label)}.csv", mime="text/csv",
            key=f"dl_global_search_{c}",
            help=f"Only the {label} matches, as CSV.",
        )


with theme.card("global_search"):
    theme.section_header(
        None, "Find an email everywhere",
        "Search Master, MQL, Unsubscribed and Bounce at once. Part of an address works too, e.g. “@acme.com”.",
        "search",
    )
    # Clear sits outside the form: a second submit button would stop Enter from searching.
    g_form_col, g_clear_col = st.columns([5, 1], vertical_alignment="bottom")
    with g_form_col, st.container(key="global_search_box"):
        with st.form("global_email_search_form", border=False):
            g_text, g_go = st.columns([4, 1.25], vertical_alignment="bottom")
            g_query = g_text.text_input("Email address", key="global_email_query",
                                        placeholder="e.g. abc@email.com or part of an address")
            g_searched = g_go.form_submit_button("Search", type="primary", width="stretch", icon=":material/search:")
    # A minor action: a text button, so it doesn't compete with Search.
    g_clear_col.button(
        "Clear", key="global_search_clear", icon=":material/close:", type="tertiary",
        on_click=clear_global_search,
        disabled=not (st.session_state.get("global_email_query") or st.session_state.get("global_email_search")),
        help="Clear the search box and its results.",
    )
    # The field's "Press Enter to submit form" hint sat on top of the typed text.
    st.markdown('<style>.st-key-global_search_box [data-testid="InputInstructions"] { display: none; }</style>',
                unsafe_allow_html=True)
    if g_searched:
        g_term = (g_query or "").strip()
        if not g_term:
            st.session_state.pop("global_email_search", None)
            st.error("Type an email address, or part of one, then click Search.", icon=":material/error:")
        else:
            try:
                with st.spinner("Searching every category…"):
                    g_df, g_counts = db.search_email_everywhere(g_term, limit_per_category=GLOBAL_SEARCH_LIMIT)
                st.session_state["global_email_search"] = {"query": g_term, "df": g_df, "counts": g_counts}
                st.session_state.pop(GLOBAL_SEARCH_CAT_KEY, None)  # a new search opens on its own first category
            except Exception as e:
                st.session_state.pop("global_email_search", None)
                theme.friendly_error("Couldn't search your lists", "Please try again.", e)
    render_global_search_results(st.session_state.get("global_email_search"))


theme.region_header("Your saved lists", "Open a category to add files, review its lists or remove them.",
                    "folder_copy")
tab_master, tab_mql, tab_bounce, tab_unsub = st.tabs(
    [TAB_LABELS["master"], TAB_LABELS["mql"], TAB_LABELS["bounce"], TAB_LABELS["unsub"]],
    key=DB_TAB_KEY, on_change="rerun",
)


# ---------------------------------------------------------------------------- #
# MASTER FILE
# ---------------------------------------------------------------------------- #
with tab_master:
    with theme.card("master_overview"):
        theme.section_header(
            None, "Master leads",
            "Your main lead database. Leads here are skipped when you clean a new file.", "folder_open",
        )
        m = COUNTS["master"]
        try:
            stor = db.get_storage_info()
        except Exception as e:
            stor = None
            st.warning(f"Storage details are unavailable right now ({e}).")

        c1, c2, c3 = st.columns(3)
        c1.metric("Leads", f"{m['unique']:,}", help="Unique email addresses — each is counted once.")
        c2.metric("Lists", f"{m['lists']:,}", help="Named groups your Master leads are saved in.")
        last_upload_metric(c3, "master")

        if m["rows"] > m["unique"]:
            st.caption(
                f"{m['rows'] - m['unique']:,} email(s) appear in more than one Master list. "
                "Each is counted once, and new uploads never add an email that's already saved."
            )

        with st.expander("Storage & upload limits", expanded=False):
            c3, c4 = st.columns(2)
            c3.metric("Database size", fmt_bytes(stor["database_bytes"]) if stor else "—")
            c4.metric("Master leads storage", fmt_bytes(stor["master_bytes"]) if stor else "—")

            c5, c6, c7, c8 = st.columns(4)
            if stor and stor["quota_bytes"]:
                free = max(stor["quota_bytes"] - stor["database_bytes"], 0)
                used_pct = min(stor["database_bytes"] / stor["quota_bytes"] * 100, 100)
                c5.metric("Available storage", fmt_bytes(free), f"{used_pct:.1f}% of {fmt_bytes(stor['quota_bytes'])} used", delta_color="off")
            else:
                c5.metric("Available storage", "Not configured")
            c6.metric("Est. size per 1M records", fmt_bytes(stor["bytes_per_million"]) if stor and stor["bytes_per_million"] else "—")
            c7.metric("Max upload (CSV/XLSX)", fmt_bytes(MAX_UNCOMPRESSED_UPLOAD_BYTES))
            c8.metric("Max upload (ZIP/GZ)", fmt_bytes(MAX_COMPRESSED_UPLOAD_BYTES))
            st.caption(
                f"Sizes are read live from PostgreSQL (`pg_database_size` / `pg_total_relation_size`). "
                f"A ZIP/GZ upload may expand to at most {fmt_bytes(MAX_ARCHIVE_CONTENT_BYTES)} of data. "
                + (
                    "Set `storage_quota_mb` under `[postgres]` in secrets.toml (or `PG_STORAGE_QUOTA_MB`) "
                    "to your database plan's limit to see available storage."
                    if not (stor and stor["quota_bytes"]) else ""
                )
            )
            st.caption(f"Connected to {_cfg['dbname']} at {_cfg['host']}:{_cfg['port']}.")

    with theme.card("master_search"):
        theme.section_header(
            None, "Search & download",
            "Find Master leads by field and download them. Your database isn't changed.", "search",
        )
        with st.form("master_search_form", border=False):
            s_field, s_text, s_go = st.columns([1, 3, 1], vertical_alignment="bottom")
            search_field = s_field.selectbox("Search in", list(MASTER_FIELD_MAP),
                                             index=list(MASTER_FIELD_MAP).index("Industry"), key="master_search_field")
            search_chips = s_text.multiselect("Keywords", options=[], accept_new_options=True,
                                              key="master_search_keywords",
                                              placeholder="Type a keyword and press Enter, e.g. Real Estate")
            searched = s_go.form_submit_button("Search", type="primary", width="stretch", icon=":material/search:")
            st.caption("Add one or more keywords. Keywords match whole words only — "
                       "“CTO” finds “Co-founder & CTO”, not “Inspectors”.")
        if searched:
            terms = keyword_terms(search_chips)
            if not terms:
                st.session_state.pop("master_search", None)
                st.error("Add at least one keyword to search for, then click Search.", icon=":material/error:")
            else:
                try:
                    with st.spinner("Searching your Master database…"):
                        found = db.search_master_contacts(MASTER_FIELD_MAP[search_field], terms,
                                                          limit=MASTER_SEARCH_LIMIT + 1)
                    st.session_state["master_search"] = {"field": search_field, "terms": terms, "df": found}
                except Exception as e:
                    theme.friendly_error("Couldn't search your Master database", "Please try again.", e)
        render_master_search(st.session_state.get("master_search"))

    with theme.card("master_add"):
        theme.section_header(
            None, "Add leads",
            "Upload one or more files. Only new emails are added — nothing already saved is changed or deleted.",
            "upload_file",
        )

        show_import_messages("master_import_files")
        master_files = st.file_uploader(
            "Master file(s)",
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

        if st.button("Add to Master database", type="primary", key="save_import_master", icon=":material/add:",
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
                                f"**Upload complete** — {written_total:,} new leads were added to Master list "
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

    with theme.card("master_files"):
        theme.section_header(None, "Your lists", "Every Master list, its size, and how many uploads it holds.", "list_alt")
        try:
            master_lists_df = db.get_master_lists()
        except Exception as e:
            master_lists_df = pd.DataFrame()
            theme.friendly_error("Couldn't load your Master lists", "Try refreshing the page.", e)
        render_files("master", master_lists_df, "contact_count", "leads",
                     stor["master_bytes"] if stor else None, m["rows"])

    with theme.card("master_history"):
        theme.section_header(None, "History", "What was added, when, and by whom.", "history")
        with st.expander("Uploads per list — undo an upload", expanded=False):
            render_merge_history("master", master_lists_df, "leads")
        with st.expander("All uploads", expanded=False):
            show_history("master")


# ---------------------------------------------------------------------------- #
# MQL / BOUNCE / UNSUB — email-only categories, same UI each
# ---------------------------------------------------------------------------- #
LIST_VIEW_SORTS = {"Newest first": "newest", "Oldest first": "oldest", "Email A–Z": "email_asc", "Email Z–A": "email_desc"}
LIST_VIEW_PAGE_SIZES = (25, 50, 100)


def render_record_list(category: str):
    """List view: every saved email of the category as a table, with filters, sorting and paging."""
    label = EMAIL_CATEGORIES[category][0]
    page_key = f"{category}_list_page"

    def first_page():
        st.session_state[page_key] = 1

    def step_page(delta):
        st.session_state[page_key] = max(1, st.session_state.get(page_key, 1) + delta)

    with theme.card(f"{category}_records"):
        theme.section_header(
            None, f"All {label} records",
            "Every saved email, one row for each list it's in. Filter, sort and page through them.", "table_rows",
        )
        try:
            lists_df = db.get_email_lists(category)
        except Exception as e:
            lists_df = pd.DataFrame()
            st.warning(f"Couldn't load your {label} lists ({e}). You can still search every record.")
        names = {int(r.id): r.name for r in lists_df.itertuples()} if not lists_df.empty else {}

        f_search, f_lists, f_sort, f_size = st.columns([2.2, 2, 1.3, 1], vertical_alignment="bottom")
        search = f_search.text_input("Email contains", key=f"{category}_list_search",
                                     placeholder="e.g. @acme.com", on_change=first_page)
        chosen = f_lists.multiselect("Lists", list(names), format_func=lambda i: names.get(i, str(i)),
                                     key=f"{category}_list_lists", placeholder="All lists", on_change=first_page)
        sort_label = f_sort.selectbox("Sort", list(LIST_VIEW_SORTS), key=f"{category}_list_sort", on_change=first_page)
        size = f_size.selectbox("Rows per page", LIST_VIEW_PAGE_SIZES, index=1, key=f"{category}_list_size",
                                on_change=first_page)

        page = max(1, int(st.session_state.get(page_key, 1)))
        try:
            rows, total = db.get_email_records(category, search, chosen, LIST_VIEW_SORTS[sort_label], size, (page - 1) * size)
            pages = max(1, -(-total // size))
            if page > pages:  # the data shrank since this page was chosen
                page = st.session_state[page_key] = pages
                rows, total = db.get_email_records(category, search, chosen, LIST_VIEW_SORTS[sort_label], size,
                                                   (page - 1) * size)
        except Exception as e:
            theme.friendly_error(f"Couldn't load your {label} records", "Try refreshing the page.", e)
            return
        if total == 0:
            if search or chosen:
                theme.empty_state("search_off", "No matching records", "Try a different search or clear the filters.")
            else:
                theme.empty_state("inbox", f"No {label} records yet", "Switch to Standard view to add a file.")
            return

        st.dataframe(
            pd.DataFrame({"Email": rows["email"], "List": rows["list_name"],
                          "Added": rows["created_at"].map(fmt_datetime)}),
            width="stretch", hide_index=True,
        )
        info, prev_col, next_col = st.columns([4, 1, 1], vertical_alignment="center")
        start = (page - 1) * size + 1
        info.caption(f"Showing {start:,}–{start + len(rows) - 1:,} of {total:,} records · page {page:,} of {pages:,}")
        prev_col.button("Previous", key=f"{category}_list_prev", icon=":material/chevron_left:", width="stretch",
                        disabled=page <= 1, on_click=step_page, args=(-1,))
        next_col.button("Next", key=f"{category}_list_next", icon=":material/chevron_right:", width="stretch",
                        disabled=page >= pages, on_click=step_page, args=(1,))
        st.caption("To add files, delete a list or undo an upload, switch to Standard view.")


def render_email_category(category: str, list_view: bool = False):
    label, icon, description = EMAIL_CATEGORIES[category]
    cnt = COUNTS[category]

    with theme.card(f"{category}_overview"):
        theme.section_header(
            None, label, description + " Leads with these emails can be removed when you clean a file.", icon,
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Emails", f"{cnt['unique']:,}", help="Unique email addresses — each is counted once.")
        c2.metric("Lists", f"{cnt['lists']:,}")
        last_upload_metric(c3, category)

    if list_view:
        render_record_list(category)
        return

    with theme.card(f"{category}_add"):
        theme.section_header(
            None, f"Add to {label}",
            "Upload files with an email column — LeadFlow finds it automatically. Emails already saved are skipped.",
            "upload_file",
        )

        uploader_base = f"{category}_import_files"
        show_import_messages(uploader_base)
        files = st.file_uploader(
            f"{label} file(s)",
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

        if st.button(f"Add to {label}", type="primary", key=f"save_import_{category}", icon=":material/add:",
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
                                f"**Upload complete** — {written_total:,} emails were added to {label} list '{clean_name}'."))
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

    with theme.card(f"{category}_files"):
        theme.section_header(None, "Your lists", f"Every {label} list, its size, and how many uploads it holds.", "list_alt")
        try:
            lists_df = db.get_email_lists(category)
        except Exception as e:
            lists_df = pd.DataFrame()
            theme.friendly_error(f"Couldn't load your {label} lists", "Try refreshing the page.", e)
        try:
            stor = db.get_storage_info()
        except Exception:
            stor = None
        render_files(category, lists_df, "email_count", "emails",
                     stor[f"{category}_bytes"] if stor else None, cnt["rows"])

    with theme.card(f"{category}_history"):
        theme.section_header(None, "History", "What was added, when, and by whom.", "history")
        with st.expander("Uploads per list — undo an upload", expanded=False):
            render_merge_history(category, lists_df, "emails")
        with st.expander("All uploads", expanded=False):
            show_history(category)


with tab_mql:
    st.session_state.setdefault("mql_view", MQL_VIEWS[0])
    mql_view = st.segmented_control("MQL view", MQL_VIEWS, required=True, key="mql_view",
                                    label_visibility="collapsed")
    render_email_category("mql", list_view=mql_view == MQL_VIEWS[1])

with tab_bounce:
    render_email_category("bounce")

with tab_unsub:
    render_email_category("unsub")

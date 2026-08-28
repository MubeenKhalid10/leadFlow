"""
LeadFlow — Manage Master Files Database
---------------------------------------

Seed and maintain the Master and Bounce suppression lists that the main
cleaning page suppresses against. From this page you can:

  * Import Master file(s) into named lists (full contact records, deduped by email globally)
  * Import Bounce file(s) into named lists (emails only, deduped)
  * View list sizes, rename lists, preview contents, and delete lists

All suppression data lives in PostgreSQL (see db.py); nothing is uploaded on
the main page anymore.
"""

import pandas as pd
import streamlit as st

import db
import theme
from dataio import (
    auto_map_columns,
    extract_emails_from_file,
    load_file,
    validate_upload,
)
st.set_page_config(
    page_title="LeadFlow — Manage Database",
    page_icon="🗄️",
    layout="wide",
)
theme.inject_theme()
theme.inject_sidebar_title()


st.markdown('<div class="lf-topbar">', unsafe_allow_html=True)
theme.render_topbar(show_how=False)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("## 🗄️ Manage Master Files Database")
st.caption(
    "Store your Master and Bounce files data here once, as named lists. "
    "The main cleaning page then suppresses against whichever lists you pick per run."
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

# --- Global master stats overview -------------------------------------------
try:
    _stats = db.get_global_master_stats()
    stat_c1, stat_c2, stat_c3 = st.columns(3)
    stat_c1.metric("📋 Total Master Lists", f"{_stats['total_lists']:,}")
    stat_c2.metric("👥 Total Contacts Stored", f"{_stats['total_contacts']:,}")
    stat_c3.metric("📧 Unique Emails (Global)", f"{_stats['unique_emails']:,}")
    if _stats["total_contacts"] > _stats["unique_emails"]:
        _cross_dups = _stats["total_contacts"] - _stats["unique_emails"]
        st.warning(
            f"⚠️ **{_cross_dups:,} cross-list duplicate email(s) detected.** "
            "The same email exists in multiple master lists. "
            "New imports use global dedup to prevent this going forward."
        )
except Exception:
    pass  # Stats are optional — don't block page on failure


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


# ============================================================================ #
# Master + Bounce management, one tab each
# ============================================================================ #
tab_master, tab_bounce = st.tabs(["🗂️  Master lists", "🚫  Bounce lists"])


# ---------------------------------------------------------------------------- #
# MASTER
# ---------------------------------------------------------------------------- #
with tab_master:
    theme.section_header("01-Import contacts into a Master list", "Import")
    st.caption(
        "Upload one or more past-campaign contact files. Contacts are stored with "
        "full details (name, company, title, industry, location) and deduplicated "
        "by email **globally** — emails already in any master list are skipped. "
        "Re-importing the same file updates existing contacts."
    )

    master_files = st.file_uploader(
        "Master file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key="master_import_files",
    )

    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        st.warning(f"Could not load Master lists: {e}")
    master_names = master_lists_df["name"].tolist() if not master_lists_df.empty else []

    master_target = pick_target_list(master_names, "master_target")

    if st.button("📥  Import into Master list", type="primary", key="btn_import_master"):
        clean_name = (master_target or "").strip()
        if not master_files:
            st.error("Please choose at least one file to import.")
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
                try:
                    # Load all existing global emails BEFORE import for dedup
                    with st.spinner("Loading existing master emails for global dedup…"):
                        existing_all_emails = db.get_all_master_emails()

                    list_id = db.get_or_create_master_list(clean_name)
                    for f in master_files:
                        with st.spinner(f"Reading {f.name}…"):
                            fdf = load_file(f)
                        records, mapping = records_from_master_df(fdf)
                        if records is None:
                            skipped_files.append(f.name)
                            continue

                        # --- Global email deduplication ------------------------
                        # Filter out any emails already stored in ANY master list
                        before_dedup = len(records)
                        records = [
                            r for r in records
                            if db.normalize_email(r.get("email", "")) not in existing_all_emails
                        ]
                        dedup_skipped = before_dedup - len(records)
                        dedup_skipped_total += dedup_skipped

                        if dedup_skipped > 0:
                            st.info(
                                f"ℹ️ **{f.name}**: {dedup_skipped:,} email(s) already in a master list "
                                f"— skipped. {len(records):,} new contacts will be imported."
                            )

                        if records:
                            with st.spinner(f"Saving {len(records):,} new rows from {f.name}…"):
                                written = db.upsert_master_contacts(list_id, records)
                                written_total += written
                                # Update the in-memory set so subsequent files
                                # in the same batch don't re-import the same emails
                                for r in records:
                                    norm = db.normalize_email(r.get("email", ""))
                                    if norm:
                                        existing_all_emails.add(norm)
                        del fdf, records

                    if skipped_files:
                        st.warning(
                            "No Email column detected in: "
                            + ", ".join(skipped_files)
                            + " — those files were skipped."
                        )
                    if written_total:
                        msg = f"✅ Saved **{written_total:,}** new contacts into Master list **'{clean_name}'**."
                        if dedup_skipped_total:
                            msg += f" ({dedup_skipped_total:,} duplicate email(s) skipped globally.)"
                        st.success(msg)
                        st.rerun()
                    elif not skipped_files:
                        if dedup_skipped_total:
                            st.info(
                                f"All {dedup_skipped_total:,} email(s) already exist in your master lists. "
                                "Nothing new was imported."
                            )
                        else:
                            st.info("No rows with a valid email were found to import.")
                except Exception as e:
                    st.error(f"Import failed: {e}")

    st.divider()
    theme.section_header("02-Your Master lists", "Manage Lists")

    try:
        master_lists_df = db.get_master_lists()
    except Exception as e:
        master_lists_df = pd.DataFrame()
        st.error(f"Could not load Master lists: {e}")

    if master_lists_df.empty:
        st.markdown(
            '<div class="lf-inline-panel">📭 No Master lists yet. '
            'Import a file above to create your first one.</div>',
            unsafe_allow_html=True,
        )
    else:
        total_contacts = int(master_lists_df["contact_count"].sum())
        st.caption(f"{len(master_lists_df)} list(s) · {total_contacts:,} contacts total")
        for row in master_lists_df.itertuples():
            head_l, head_c, head_r = st.columns([5, 2, 2])
            head_l.markdown(f"**{row.name}**")
            head_c.markdown(f"👥 {int(row.contact_count):,} contacts")
            head_r.caption(f"Created {pd.to_datetime(row.created_at):%Y-%m-%d}")
            with st.expander("⚙️ Rename · preview · delete", expanded=False):
                new_name = st.text_input(
                    "Rename to", value=row.name, key=f"m_rename_{row.id}"
                )
                act_l, act_r = st.columns(2)
                if act_l.button("💾 Save name", key=f"m_save_{row.id}"):
                    try:
                        db.rename_master_list(row.id, new_name)
                        st.success("Renamed.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Rename failed: {e}")
                if act_r.button("👁️ Preview first 20", key=f"m_prev_{row.id}"):
                    try:
                        st.dataframe(
                            db.get_master_contacts_df([row.id], limit=20),
                            width="stretch",
                        )
                    except Exception as e:
                        st.error(f"Preview failed: {e}")
                st.markdown("---")
                confirm = st.checkbox(
                    "Yes, permanently delete this list and all its contacts",
                    key=f"m_confirm_{row.id}",
                )
                if st.button(
                    "🗑️ Delete list",
                    key=f"m_del_{row.id}",
                    disabled=not confirm,
                ):
                    try:
                        db.delete_master_list(row.id)
                        st.success(f"Deleted '{row.name}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")


# ---------------------------------------------------------------------------- #
# BOUNCE
# ---------------------------------------------------------------------------- #
with tab_bounce:
    theme.section_header("01-Import emails into a Bounce list", "Import")
    st.caption(
        "Upload bounce export file(s). Only the email column is needed — LeadFlow "
        "auto-detects it. Emails are normalised and deduplicated."
    )

    bounce_files = st.file_uploader(
        "Bounce file(s) — CSV, XLSX, XLS, ZIP, or GZ",
        type=["csv", "xlsx", "xls", "zip", "gz"],
        accept_multiple_files=True,
        key="bounce_import_files",
    )

    try:
        bounce_lists_df = db.get_bounce_lists()
    except Exception as e:
        bounce_lists_df = pd.DataFrame()
        st.warning(f"Could not load Bounce lists: {e}")
    bounce_names = bounce_lists_df["name"].tolist() if not bounce_lists_df.empty else []

    bounce_target = pick_target_list(bounce_names, "bounce_target")

    if st.button("📥  Import into Bounce list", type="primary", key="btn_import_bounce"):
        clean_name = (bounce_target or "").strip()
        if not bounce_files:
            st.error("Please choose at least one file to import.")
        elif not clean_name:
            st.error("Please enter a name for the list.")
        else:
            upload_errors = [err for f in bounce_files if (err := validate_upload(f))]
            if upload_errors:
                for err in upload_errors:
                    st.error(err)
            else:
                written_total = 0
                skipped_files = []
                try:
                    list_id = db.get_or_create_bounce_list(clean_name)
                    for f in bounce_files:
                        with st.spinner(f"Reading {f.name}…"):
                            fdf = load_file(f)
                        emails = extract_emails_from_file(fdf)
                        if emails is None or emails.empty:
                            skipped_files.append(f.name)
                            continue
                        with st.spinner(f"Saving {len(emails):,} emails from {f.name}…"):
                            written_total += db.upsert_bounce_emails(list_id, emails.tolist())
                        del fdf, emails
                    if skipped_files:
                        st.warning(
                            "No Email column detected in: "
                            + ", ".join(skipped_files)
                            + " — those files were skipped."
                        )
                    if written_total:
                        st.success(
                            f"✅ Saved {written_total:,} emails into Bounce list '{clean_name}'."
                        )
                        st.rerun()
                    elif not skipped_files:
                        st.info("No valid emails were found to import.")
                except Exception as e:
                    st.error(f"Import failed: {e}")

    st.divider()
    theme.section_header("02-Your Bounce lists", "Manage Lists")

    try:
        bounce_lists_df = db.get_bounce_lists()
    except Exception as e:
        bounce_lists_df = pd.DataFrame()
        st.error(f"Could not load Bounce lists: {e}")

    if bounce_lists_df.empty:
        st.markdown(
            '<div class="lf-inline-panel">📭 No Bounce lists yet. '
            'Import a file above to create your first one.</div>',
            unsafe_allow_html=True,
        )
    else:
        total_emails = int(bounce_lists_df["email_count"].sum())
        st.caption(f"{len(bounce_lists_df)} list(s) · {total_emails:,} emails total")
        for row in bounce_lists_df.itertuples():
            head_l, head_c, head_r = st.columns([5, 2, 2])
            head_l.markdown(f"**{row.name}**")
            head_c.markdown(f"✉️ {int(row.email_count):,} emails")
            head_r.caption(f"Created {pd.to_datetime(row.created_at):%Y-%m-%d}")
            with st.expander("⚙️ Rename · preview · delete", expanded=False):
                new_name = st.text_input(
                    "Rename to", value=row.name, key=f"b_rename_{row.id}"
                )
                act_l, act_r = st.columns(2)
                if act_l.button("💾 Save name", key=f"b_save_{row.id}"):
                    try:
                        db.rename_bounce_list(row.id, new_name)
                        st.success("Renamed.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Rename failed: {e}")
                if act_r.button("👁️ Preview first 20", key=f"b_prev_{row.id}"):
                    try:
                        st.dataframe(
                            db.get_bounce_emails_df([row.id], limit=20),
                            width="stretch",
                        )
                    except Exception as e:
                        st.error(f"Preview failed: {e}")
                st.markdown("---")
                confirm = st.checkbox(
                    "Yes, permanently delete this list and all its emails",
                    key=f"b_confirm_{row.id}",
                )
                if st.button(
                    "🗑️ Delete list",
                    key=f"b_del_{row.id}",
                    disabled=not confirm,
                ):
                    try:
                        db.delete_bounce_list(row.id)
                        st.success(f"Deleted '{row.name}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")

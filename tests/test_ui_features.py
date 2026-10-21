"""UI tests (streamlit.testing AppTest): save-to-category on the cleaning page, global email search,
MQL Standard/List view, and the admin gate on the Database page."""

import io

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import db
from conftest import ADMIN, ROOT, USER

DB_PAGE = str(ROOT / "pages" / "1_Database.py")
CLEAN_PAGE = str(ROOT / "app.py")
TIMEOUT = 60


def _run(at):
    at.run(timeout=TIMEOUT)
    assert not at.exception, [e.message for e in at.exception]
    return at


def _db_page(user=ADMIN):
    at = AppTest.from_file(DB_PAGE, default_timeout=TIMEOUT)
    if user:
        at.session_state["_auth_user"] = dict(user)
    at.session_state["_auth_restore_attempted"] = True  # no browser cookie in tests
    return _run(at)


def _texts(at):
    return " ".join(str(m.value) for m in at.markdown) + " ".join(str(c.value) for c in at.caption)


def _button(at, key):
    return next(b for b in at.button if b.key == key)


# --------------------------------------------------------------------------- #
# Authentication / authorisation
# --------------------------------------------------------------------------- #
def test_database_page_requires_login():
    at = _db_page(user=None)
    assert not [t for t in at.text_input if t.key == "global_email_query"]


def test_database_page_blocks_non_admins():
    at = _db_page(user=USER)
    assert "You need Admin access" in _texts(at)
    assert not [t for t in at.text_input if t.key == "global_email_query"]


# --------------------------------------------------------------------------- #
# Global email search
# --------------------------------------------------------------------------- #
@pytest.fixture
def seeded():
    db.store_records("master", "Master A", [{"email": "abc@email.com", "first_name": "Abe", "last_name": "Cole"}])
    db.store_records("mql", "MQL list", [{"email": "abc@email.com"}])
    db.store_records("bounce", "Bounces", [{"email": "abc@email.com"}])
    db.store_records("unsub", "Unsubs", [{"email": "someone@else.com"}])


def _search(at, query):
    at.text_input(key="global_email_query").set_value(query)
    next(b for b in at.button if "Search" in str(b.label) and b.form_id == "global_email_search_form").click()
    return _run(at)


def _results_table(at):
    return next(d.value for d in at.dataframe if "Category" in d.value.columns)


def test_global_search_labels_each_category_match(seeded):
    at = _search(_db_page(), "ABC@Email.com")
    table = _results_table(at)
    assert sorted(table["Category"]) == ["Bounce", "MQL", "Master"]
    assert set(table["Email"]) == {"abc@email.com"}
    assert table.loc[table["Category"] == "Master", "Name"].iloc[0] == "Abe Cole"
    assert table["Category"].tolist()[0] == "Bounce"  # do-not-contact lists come first
    assert "3 matches" in _texts(at)
    # A few matches open together; each category can also be shown on its own.
    assert at.segmented_control(key="global_search_cat").options == [
        "All (3)", "Bounce (1)", "MQL (1)", "Master (1)"]
    # Download everything at once, or one category on its own.
    assert [d.proto.label for d in at.get("download_button")] == [
        "All matches (3)", "Bounce (1)", "MQL (1)", "Master (1)"]


def test_global_search_partial_and_empty_states(seeded):
    at = _search(_db_page(), "@else.com")
    # Matches in one category only: the picker names it, so the table drops the Category column.
    assert at.segmented_control(key="global_search_cat").options == ["Unsubscribed (1)"]
    assert next(d.value for d in at.dataframe if "Email" in d.value.columns)["Email"].tolist() == ["someone@else.com"]
    at = _search(at, "nobody@nowhere.com")
    assert "No matching emails" in _texts(at)
    at = _search(at, "   ")
    assert any("Type an email address" in str(e.value) for e in at.error)


def test_global_search_shows_one_category_at_a_time(seeded):
    at = _search(_db_page(), "abc@email.com")
    at.segmented_control(key="global_search_cat").set_value("bounce")
    at = _run(at)
    # Only Bounce rows, without the Category column or the Master-only Name and Company.
    records = next(d.value for d in at.dataframe if list(d.value.columns) == ["Email", "List", "Added"])
    assert records["Email"].tolist() == ["abc@email.com"]
    # A new search starts again from its own first option.
    at = _search(at, "@else.com")
    assert at.segmented_control(key="global_search_cat").value == "unsub"


def test_clear_empties_the_search_box_and_results(seeded):
    at = _db_page()
    assert _button(at, "global_search_clear").disabled  # nothing to clear yet
    at = _search(at, "abc@email.com")
    assert not _button(at, "global_search_clear").disabled
    _button(at, "global_search_clear").click()
    at = _run(at)
    assert at.text_input(key="global_email_query").value == ""
    assert "global_email_search" not in at.session_state
    assert not [d for d in at.dataframe if "Category" in d.value.columns]


def test_open_tab_survives_a_count_change(seeded):
    at = _db_page()
    at.session_state["db_tab"] = "MQL (0)"  # label from before an import changed the count
    at = _run(at)
    assert at.session_state["db_tab"] == "MQL (1)"


def test_global_search_error_is_reported(seeded, monkeypatch):
    at = _db_page()
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "search_email_everywhere", boom)
    at = _search(at, "abc")
    assert any("Couldn't search your lists" in str(e.value) for e in at.error)


# --------------------------------------------------------------------------- #
# MQL Standard / List view
# --------------------------------------------------------------------------- #
def test_mql_view_switching_and_paging():
    db.store_records("mql", "Webinar", [{"email": f"lead{i:02d}@acme.com"} for i in range(60)])
    at = _db_page()
    assert at.session_state["mql_view"] == "Standard view"
    assert [b for b in at.button if b.key == "save_import_mql"]  # existing view's actions

    at.segmented_control(key="mql_view").set_value("List view")
    at = _run(at)
    assert not [b for b in at.button if b.key == "save_import_mql"]
    records = next(d.value for d in at.dataframe if list(d.value.columns) == ["Email", "List", "Added"])
    assert len(records) == 50 and set(records["List"]) == {"Webinar"}
    assert "Showing 1–50 of 60 records" in _texts(at)

    _button(at, "mql_list_next").click()
    at = _run(at)
    assert "Showing 51–60 of 60 records" in _texts(at)

    at.text_input(key="mql_list_search").set_value("LEAD0")
    at = _run(at)
    assert "Showing 1–10 of 10 records" in _texts(at)  # filter change returns to page 1

    at.segmented_control(key="mql_view").set_value("Standard view")
    at = _run(at)
    assert [b for b in at.button if b.key == "save_import_mql"]


# --------------------------------------------------------------------------- #
# Cleaning page: store cleaned data in the chosen category
# --------------------------------------------------------------------------- #
CLEANED_DF = pd.DataFrame({
    "First Name": ["Ann", "Bob", "Cy"],
    "Last Name": ["Lee", "Ray", "Ng"],
    "Company": ["Acme", "Acme", "Beta"],
    "Email": ["ann@acme.com", "bob@acme.com", "cy@beta.io"],
})


class _Upload(io.BytesIO):
    """Stands in for the uploaded raw file (Streamlit's UploadedFile is a named BytesIO)."""
    name = "leads.csv"


def _clean_page():
    at = AppTest.from_file(CLEAN_PAGE, default_timeout=TIMEOUT)
    at.session_state["_auth_user"] = dict(ADMIN)
    at.session_state["_auth_restore_attempted"] = True
    # The state a finished cleaning run leaves: the raw file in use plus its cleaned result.
    at.session_state["active_raw_file"] = _Upload(CLEANED_DF.to_csv(index=False).encode())
    at.session_state["cleaned_df"] = CLEANED_DF.copy()
    at.session_state["report"] = []
    at.session_state["metrics"] = {}
    at.session_state["run_token"] = "run-1"
    return _run(at)


def _tables():
    with db.get_conn() as conn:
        cur = conn.cursor()
        out = {}
        for cat, t in (("master", "master_contacts"), ("mql", "mql_emails"),
                       ("unsub", "unsub_emails"), ("bounce", "bounce_emails")):
            cur.execute(f"SELECT email FROM {t} ORDER BY email")
            out[cat] = [r[0] for r in cur.fetchall()]
    return out


@pytest.mark.parametrize("category,label", [("master", "Master"), ("mql", "MQL"),
                                            ("unsub", "Unsubscribed"), ("bounce", "Bounce")])
def test_save_cleaned_leads_to_each_category(category, label):
    at = _clean_page()
    assert at.radio(key="save_dest_category").value == "master"  # default unchanged
    at.radio(key="save_dest_category").set_value(category)
    at = _run(at)
    at.text_input(key=f"save_{category}_newname").set_value("Run list")
    at = _run(at)
    btn_key = "save_to_master_btn" if category == "master" else f"save_to_{category}_btn"
    assert _button(at, btn_key).label == f"Save 3 new leads to {label}"
    _button(at, btn_key).click()
    at = _run(at)
    assert any(f"added to {label} list 'Run list'" in str(s.value) for s in at.success)
    tables = _tables()
    assert tables[category] == ["ann@acme.com", "bob@acme.com", "cy@beta.io"]
    assert all(v == [] for k, v in tables.items() if k != category)


def test_save_to_email_category_previews_and_skips_existing():
    db.store_records("bounce", "Old bounces", [{"email": "bob@acme.com"}])
    at = _clean_page()
    at.radio(key="save_dest_category").set_value("bounce")
    at = _run(at)
    at.selectbox(key="save_bounce_choice").set_value("Old bounces")
    at = _run(at)
    assert _button(at, "save_to_bounce_btn").label == "Save 2 new leads to Bounce"
    assert "1 are already in this Bounce list" in _texts(at)
    _button(at, "save_to_bounce_btn").click()
    at = _run(at)
    assert _tables()["bounce"] == ["ann@acme.com", "bob@acme.com", "cy@beta.io"]


def test_save_to_master_still_dedupes_across_all_master_lists():
    db.store_records("master", "Earlier", [{"email": "ann@acme.com"}])
    at = _clean_page()
    at.text_input(key="save_master_newname").set_value("New list")
    at = _run(at)
    assert _button(at, "save_to_master_btn").label == "Save 2 new leads to Master"

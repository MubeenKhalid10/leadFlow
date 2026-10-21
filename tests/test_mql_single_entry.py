"""MQL Add Single Entry: the contact-detail columns (added without touching existing rows), saving one
record with the right field mapping, duplicate handling, undo, the List view and search showing the
saved columns, and the page's form with its validation."""

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import db
from conftest import ADMIN, ROOT
from dataio import extract_mql_records

ENTRY = {"first_name": " Ann ", "last_name": "Lee", "company": "Acme", "job_title": "CTO", "email": " Ann@Acme.com "}
LIST_COLUMNS = ["First Name", "Last Name", "Company", "Title", "Email", "List", "Added"]


def _mql_rows():
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT l.name, e.email, e.first_name, e.last_name, e.company, e.job_title "
                    "FROM mql_emails e JOIN mql_lists l ON l.id = e.list_id ORDER BY e.id")
        return cur.fetchall()


def _columns(table):
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = %s ORDER BY ordinal_position", (table,))
        return [r[0] for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def test_mql_table_has_the_detail_columns_and_others_dont():
    assert _columns("mql_emails") == ["id", "list_id", "email", "created_at",
                                      "first_name", "last_name", "company", "job_title"]
    assert _columns("bounce_emails") == _columns("unsub_emails") == ["id", "list_id", "email", "created_at"]


def test_upgrading_an_existing_database_keeps_its_mql_rows(monkeypatch):
    db.store_records("mql", "Old list", [{"email": "old@x.com"}])
    with db.get_conn() as conn:  # back to the table as it was before this feature
        conn.cursor().execute("ALTER TABLE mql_emails " + ", ".join(f"DROP COLUMN {c}" for c in db.MQL_DETAIL_COLUMNS))
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, list_id, email, created_at FROM mql_emails")
        before = cur.fetchall()

    monkeypatch.setattr(db, "_SCHEMA_READY_KEY", None)  # as on the next app start
    assert db.init_db() == (True, None)
    assert _columns("mql_emails")[-4:] == list(db.MQL_DETAIL_COLUMNS)
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, list_id, email, created_at, first_name, last_name, company, job_title FROM mql_emails")
        assert cur.fetchall() == [(*row, None, None, None, None) for row in before]
    # Running it again changes nothing.
    monkeypatch.setattr(db, "_SCHEMA_READY_KEY", None)
    assert db.init_db() == (True, None) and _columns("mql_emails")[-4:] == list(db.MQL_DETAIL_COLUMNS)


# --------------------------------------------------------------------------- #
# Saving one record
# --------------------------------------------------------------------------- #
def test_add_mql_record_maps_every_field():
    list_id = db.get_or_create_email_list("mql", "Hand entries")
    assert db.add_mql_record(list_id, ENTRY, uploaded_by="admin@example.com", list_name="Hand entries") is True
    assert _mql_rows() == [("Hand entries", "ann@acme.com", "Ann", "Lee", "Acme", "CTO")]


def test_blank_details_are_stored_as_null():
    list_id = db.get_or_create_email_list("mql", "L")
    db.add_mql_record(list_id, {"email": "only@x.com", "first_name": "  ", "company": ""})
    assert _mql_rows() == [("L", "only@x.com", None, None, None, None)]


def test_email_is_required():
    list_id = db.get_or_create_email_list("mql", "L")
    with pytest.raises(ValueError):
        db.add_mql_record(list_id, {"email": "  ", "first_name": "Ann"})
    assert _mql_rows() == []


def test_duplicate_in_the_same_list_is_skipped_and_the_saved_entry_kept():
    list_id = db.get_or_create_email_list("mql", "L")
    db.add_mql_record(list_id, ENTRY)
    assert db.add_mql_record(list_id, {**ENTRY, "email": "ANN@acme.com", "company": "Other Co"}) is False
    assert _mql_rows() == [("L", "ann@acme.com", "Ann", "Lee", "Acme", "CTO")]


def test_duplicate_of_a_file_import_is_skipped_too():
    list_id, _ = db.store_records("mql", "Imported", [{"email": "ann@acme.com"}])
    assert db.add_mql_record(list_id, ENTRY) is False
    assert _mql_rows() == [("Imported", "ann@acme.com", None, None, None, None)]


def test_same_email_in_another_list_is_added_like_an_import():
    first = db.get_or_create_email_list("mql", "First")
    second = db.get_or_create_email_list("mql", "Second")
    assert db.add_mql_record(first, ENTRY) and db.add_mql_record(second, ENTRY)
    assert [r[0] for r in _mql_rows()] == ["First", "Second"]


def test_single_entry_is_logged_and_can_be_undone():
    list_id = db.get_or_create_email_list("mql", "L")
    db.store_records("mql", "L", [{"email": "kept@x.com"}])
    db.add_mql_record(list_id, ENTRY, uploaded_by="admin@example.com", list_name="L")
    hist = db.get_upload_history("mql")
    entry = hist[hist["file_name"] == db.SINGLE_ENTRY_FILE_NAME].iloc[0]
    assert int(entry["rows_written"]) == 1 and entry["uploaded_by"] == "admin@example.com"
    assert db.revert_upload(int(entry["id"])) == 1
    assert [r[1] for r in _mql_rows()] == ["kept@x.com"]


def test_records_and_search_return_the_saved_details():
    list_id = db.get_or_create_email_list("mql", "L")
    db.add_mql_record(list_id, ENTRY)
    rows, total = db.get_email_records("mql")
    assert total == 1
    assert rows.iloc[0][["first_name", "last_name", "company", "job_title", "email"]].tolist() == \
        ["Ann", "Lee", "Acme", "CTO", "ann@acme.com"]
    assert "first_name" not in db.get_email_records("bounce")[0].columns
    found, counts = db.search_email_everywhere("ann@acme.com")
    assert counts["mql"] == 1
    assert found.iloc[0][["first_name", "last_name", "company", "job_title"]].tolist() == ["Ann", "Lee", "Acme", "CTO"]


# --------------------------------------------------------------------------- #
# MQL file imports and cleaned-lead saves keep name, company and title
# --------------------------------------------------------------------------- #
def test_file_records_take_whichever_details_the_file_has():
    df = pd.DataFrame({"E-mail": ["Ann@Acme.com", "", None, "bob@x.com"], "FName": ["Ann", "X", "Y", None],
                       "Surname": ["Lee", "", "", "Bo"], "Organisation": ["Acme", "", "", ""],
                       "Designation": ["CTO", "", "", "VP"], "Industry": ["IT", "", "", ""]})
    assert extract_mql_records(df) == [
        {"first_name": "Ann", "last_name": "Lee", "company": "Acme", "job_title": "CTO", "email": "Ann@Acme.com"},
        {"first_name": None, "last_name": "Bo", "company": "", "job_title": "VP", "email": "bob@x.com"},
    ]  # rows without an email dropped; Industry isn't an MQL column


def test_file_records_with_only_an_email_column():
    assert extract_mql_records(pd.DataFrame({"Email": ["a@x.com"]})) == [{"email": "a@x.com"}]
    assert extract_mql_records(pd.DataFrame({"Name": ["Ann"]})) is None  # no email column


def test_file_records_split_a_single_name_column():
    df = pd.DataFrame({"Email": ["a@x.com", "b@x.com"], "Full Name": ["Ann Marie Lee", "Cher"]})
    recs = extract_mql_records(df)
    assert [(r["first_name"], r["last_name"]) for r in recs] == [("Ann", "Marie Lee"), ("Cher", None)]


def test_upsert_mql_records_stores_details_and_skips_saved_emails():
    list_id, _ = db.store_records("mql", "L", [{"email": "saved@x.com"}])
    written = db.upsert_mql_records(list_id, [
        {"email": " SAVED@x.com", "first_name": "Should", "company": "Not change"},
        {"email": "ann@acme.com", "first_name": "Ann", "last_name": "Lee", "company": "Acme", "job_title": "CTO"},
        {"email": "ANN@acme.com", "first_name": "Second copy"},  # first record wins
        {"email": "plain@x.com"},
        {"email": "", "first_name": "No email"},
    ], upload={"file_name": "mql.csv", "rows_in_file": 5, "list_name": "L"})
    assert written == 2
    assert _mql_rows() == [("L", "saved@x.com", None, None, None, None),
                           ("L", "ann@acme.com", "Ann", "Lee", "Acme", "CTO"),
                           ("L", "plain@x.com", None, None, None, None)]
    hist = db.get_upload_history("mql")
    entry = hist[hist["file_name"] == "mql.csv"].iloc[0]
    assert int(entry["rows_written"]) == 2 and int(entry["rows_skipped"]) == 3
    assert db.revert_upload(int(entry["id"])) == 2  # an import with details can still be undone
    assert [r[1] for r in _mql_rows()] == ["saved@x.com"]


def test_upsert_mql_records_with_nothing_to_add_is_still_logged():
    list_id = db.get_or_create_email_list("mql", "L")
    assert db.upsert_mql_records(list_id, [{"email": ""}], upload={"file_name": "empty.csv", "rows_in_file": 1}) == 0
    assert db.get_upload_history("mql")["file_name"].tolist() == ["empty.csv"]


def test_saving_cleaned_leads_to_mql_keeps_details():
    db.store_records("mql", "Cleaned", [{"email": "ann@acme.com", "first_name": "Ann", "last_name": "Lee",
                                         "company": "Acme", "job_title": "CTO", "industry": "IT"}])
    assert _mql_rows() == [("Cleaned", "ann@acme.com", "Ann", "Lee", "Acme", "CTO")]


# --------------------------------------------------------------------------- #
# Database page
# --------------------------------------------------------------------------- #
def _run(at):
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _db_page():
    at = AppTest.from_file(str(ROOT / "pages" / "1_Database.py"), default_timeout=60)
    at.session_state["_auth_user"] = dict(ADMIN)
    at.session_state["_auth_restore_attempted"] = True
    return _run(at)


def _open_form(at):
    next(b for b in at.button if b.key == "mql_single_open").click()
    return _run(at)


def _fill_and_save(at, values, new_list=None, existing_list=None):
    for col, value in values.items():
        at.text_input(key=f"mql_single_{col}").set_value(value)
    if existing_list:
        at.selectbox(key="mql_single_target_choice").set_value(existing_list)
    at = _run(at)
    if new_list is not None:
        at.text_input(key="mql_single_target_newname").set_value(new_list)
    next(b for b in at.button if b.key == "mql_single_save").click()
    return _run(at)


def _records_table(at):
    return next(d.value for d in at.dataframe if list(d.value.columns) == LIST_COLUMNS)


def test_form_fields_follow_the_list_view_order():
    at = _open_form(_db_page())
    keys = [t.key for t in at.text_input if t.key and t.key.startswith("mql_single_") and "target" not in t.key]
    assert keys == ["mql_single_first_name", "mql_single_last_name", "mql_single_company",
                    "mql_single_job_title", "mql_single_email"]
    labels = [t.label for t in at.text_input if t.key in keys]
    assert labels == ["First Name", "Last Name", "Company", "Title", "Email *"]


def test_cancel_closes_the_form_without_saving():
    at = _open_form(_db_page())
    at.text_input(key="mql_single_email").set_value("ann@acme.com")
    next(b for b in at.button if b.key == "mql_single_cancel").click()
    at = _run(at)
    assert not [b for b in at.button if b.key == "mql_single_save"]
    assert _mql_rows() == []


def test_saving_shows_the_new_record_in_the_list_view():
    db.store_records("mql", "Webinar", [{"email": f"lead{i}@x.com"} for i in range(30)])
    at = _open_form(_db_page())
    at = _fill_and_save(at, ENTRY, existing_list="Webinar")
    assert at.session_state["mql_view"] == "List view"
    first = _records_table(at).iloc[0]
    assert first.tolist()[:6] == ["Ann", "Lee", "Acme", "CTO", "ann@acme.com", "Webinar"]
    assert ("Webinar", "ann@acme.com", "Ann", "Lee", "Acme", "CTO") in _mql_rows()


def test_saving_into_a_new_list():
    at = _fill_and_save(_open_form(_db_page()), {"email": "new@x.com", "company": "NewCo"}, new_list="Hand picked")
    assert _mql_rows() == [("Hand picked", "new@x.com", None, None, "NewCo", None)]
    assert _records_table(at).iloc[0]["Company"] == "NewCo"


@pytest.mark.parametrize("values, new_list, message", [
    ({"first_name": "Ann"}, "L", "Enter an email address."),
    ({"email": "not-an-email"}, "L", "doesn't look right"),
    ({"email": "ann@acme"}, "L", "doesn't look right"),
    ({"email": "ann@acme.com"}, "", "Enter a name for the new list"),
])
def test_validation_errors_save_nothing(values, new_list, message):
    at = _fill_and_save(_open_form(_db_page()), values, new_list=new_list)
    assert any(message in str(e.value) for e in at.error)
    assert _mql_rows() == []


def test_duplicate_is_reported_and_nothing_changes():
    db.store_records("mql", "Webinar", [{"email": "ann@acme.com"}])
    at = _fill_and_save(_open_form(_db_page()), ENTRY, existing_list="Webinar")
    assert any("already in the list “Webinar”" in str(e.value) for e in at.error)
    assert _mql_rows() == [("Webinar", "ann@acme.com", None, None, None, None)]


def test_database_failure_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "add_mql_record", boom)
    at = _fill_and_save(_open_form(_db_page()), ENTRY, new_list="L")
    assert any("Couldn't add this entry" in str(e.value) for e in at.error)
    assert _mql_rows() == []

"""Data-layer tests: storing into each category, the MQL list view query, and global email search."""

import pytest

import db

EMAIL_TABLES = {"mql": "mql_emails", "unsub": "unsub_emails", "bounce": "bounce_emails"}


def _rows(table):
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT email FROM {table} ORDER BY email")
        return [r[0] for r in cur.fetchall()]


def _all_tables():
    return {"master": _rows("master_contacts"), **{c: _rows(t) for c, t in EMAIL_TABLES.items()}}


CLEANED = [
    {"email": " Ann@Acme.com ", "first_name": "Ann", "last_name": "Lee", "company": "Acme"},
    {"email": "bob@acme.com", "first_name": "Bob", "company": "Acme"},
    {"email": "", "first_name": "No email"},
]


# --------------------------------------------------------------------------- #
# Storing cleaned data in each category (the cleaning page's save step)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("category", ["master", "mql", "unsub", "bounce"])
def test_store_records_goes_to_the_selected_category_only(category):
    list_id, written = db.store_records(category, "Cleaned run", CLEANED,
                                        upload={"file_name": "leads.csv (cleaned in LeadFlow)", "rows_in_file": 3,
                                                "list_name": "Cleaned run", "uploaded_by": "admin@example.com"})
    assert written == 2  # blank email skipped, emails normalised
    tables = _all_tables()
    assert tables[category] == ["ann@acme.com", "bob@acme.com"]
    assert all(rows == [] for cat, rows in tables.items() if cat != category)

    lists = db.get_master_lists() if category == "master" else db.get_email_lists(category)
    assert lists["name"].tolist() == ["Cleaned run"] and int(lists["id"].iloc[0]) == list_id
    hist = db.get_upload_history(category)
    assert len(hist) == 1 and int(hist["rows_written"].iloc[0]) == 2 and int(hist["list_id"].iloc[0]) == list_id


def test_store_records_master_keeps_details_and_upserts():
    db.store_records("master", "A", CLEANED[:1])
    db.store_records("master", "A", [{"email": "ann@acme.com", "job_title": "CTO"}])
    df = db.get_master_contacts_df(db.get_master_lists()["id"].tolist())
    row = df.iloc[0]
    assert len(df) == 1 and row["first_name"] == "Ann" and row["company"] == "Acme" and row["job_title"] == "CTO"


@pytest.mark.parametrize("category", ["mql", "unsub", "bounce"])
def test_store_records_email_categories_skip_emails_already_in_the_list(category):
    db.store_records(category, "L", CLEANED)
    _, written = db.store_records(category, "L", CLEANED + [{"email": "new@acme.com"}])
    assert written == 1
    assert _rows(EMAIL_TABLES[category]) == ["ann@acme.com", "bob@acme.com", "new@acme.com"]


def test_store_records_rejects_unknown_category_and_blank_list_name():
    with pytest.raises(ValueError):
        db.store_records("spam", "L", CLEANED)
    with pytest.raises(ValueError):
        db.store_records("mql", "  ", CLEANED)


# --------------------------------------------------------------------------- #
# Adding records directly to each category (Database page imports)
# --------------------------------------------------------------------------- #
def test_direct_add_to_master():
    list_id = db.get_or_create_master_list("Direct")
    assert db.upsert_master_contacts(list_id, [{"email": "X@Y.com", "first_name": "X"}]) == 1
    assert _all_tables()["master"] == ["x@y.com"]


@pytest.mark.parametrize("category", ["mql", "unsub", "bounce"])
def test_direct_add_to_email_category(category):
    list_id = db.get_or_create_email_list(category, "Direct")
    assert db.upsert_emails(category, list_id, ["X@Y.com", "x@y.com", "z@y.com"]) == 2
    assert db.get_category_counts()[category] == {"lists": 1, "rows": 2, "unique": 2}


# --------------------------------------------------------------------------- #
# MQL list view query
# --------------------------------------------------------------------------- #
@pytest.fixture
def mql_records():
    a = db.get_or_create_email_list("mql", "Webinar")
    b = db.get_or_create_email_list("mql", "Trade show")
    db.upsert_emails("mql", a, [f"user{i:02d}@acme.com" for i in range(30)])
    db.upsert_emails("mql", b, ["user00@acme.com", "zed@other.org"])
    return a, b


def test_list_view_pages_and_totals(mql_records):
    page1, total = db.get_email_records("mql", sort="email_asc", limit=25, offset=0)
    page2, total2 = db.get_email_records("mql", sort="email_asc", limit=25, offset=25)
    assert total == total2 == 32
    assert len(page1) == 25 and len(page2) == 7
    assert set(page1["email"]).isdisjoint(set(page2["email"]) - {"user00@acme.com"})
    assert list(page1.columns) == ["id", "email", "list_id", "list_name", "created_at",
                                   "first_name", "last_name", "company", "job_title"]
    # past the last page: no rows, but the true total
    rows, total = db.get_email_records("mql", limit=25, offset=100)
    assert rows.empty and total == 32


def test_list_view_filters_and_sorts(mql_records):
    a, b = mql_records
    rows, total = db.get_email_records("mql", search="USER0", sort="email_desc", limit=100)
    assert total == 11  # user00..user09 in Webinar + user00 in Trade show
    assert rows["email"].iloc[0] == "user09@acme.com"
    rows, total = db.get_email_records("mql", list_ids=[b], limit=100)
    assert total == 2 and set(rows["list_name"]) == {"Trade show"}
    rows, total = db.get_email_records("mql", search="zed", list_ids=[a], limit=100)
    assert total == 0 and rows.empty
    with pytest.raises(ValueError):
        db.get_email_records("mql", sort="drop table")


def test_list_view_treats_wildcards_literally(mql_records):
    assert db.get_email_records("mql", search="%")[1] == 0
    assert db.get_email_records("mql", search="user_0")[1] == 0


# --------------------------------------------------------------------------- #
# Global email search
# --------------------------------------------------------------------------- #
@pytest.fixture
def everywhere():
    db.store_records("master", "Master A", [{"email": "abc@email.com", "first_name": "Abe", "company": "Acme"},
                                            {"email": "xabc@email.com"}, {"email": "other@corp.com"}])
    db.store_records("master", "Master B", [{"email": "abc@email.com"}])
    db.store_records("mql", "MQL list", [{"email": "abc@email.com"}])
    db.store_records("bounce", "Bounces", [{"email": "abc@email.com"}, {"email": "bounced@corp.com"}])
    db.store_records("unsub", "Unsubs", [{"email": "gone@corp.com"}])


def test_search_finds_the_email_in_every_category_with_labels(everywhere):
    df, counts = db.search_email_everywhere("abc@email.com")
    exact = df[df["email"] == "abc@email.com"]
    # one row per stored record: two Master lists, MQL and Bounce — never merged
    assert sorted(exact["category_label"]) == ["Bounce", "MQL", "Master", "Master"]
    assert sorted(exact["list_name"]) == ["Bounces", "MQL list", "Master A", "Master B"]
    assert "Unsubscribed" not in set(df["category_label"])
    assert counts == {"master": 3, "mql": 1, "bounce": 1, "unsub": 0}  # master also matches xabc@
    # exact matches first, then other partial matches
    assert df["email"].iloc[: len(exact)].eq("abc@email.com").all()
    assert df["email"].iloc[-1] == "xabc@email.com"
    master_row = exact[exact["list_name"] == "Master A"].iloc[0]
    assert master_row["first_name"] == "Abe" and master_row["company"] == "Acme"


@pytest.mark.parametrize("query", ["ABC@EMAIL.COM", "  Abc@Email.Com  ", "abc@", "@email.com", "BC@EM"])
def test_search_is_case_insensitive_and_partial(everywhere, query):
    df, _ = db.search_email_everywhere(query)
    assert "abc@email.com" in set(df["email"])


def test_search_partial_domain_across_categories(everywhere):
    df, counts = db.search_email_everywhere("@corp.com")
    assert set(zip(df["category_label"], df["email"])) == {
        ("Master", "other@corp.com"), ("Bounce", "bounced@corp.com"), ("Unsubscribed", "gone@corp.com")}
    assert counts == {"master": 1, "mql": 0, "bounce": 1, "unsub": 1}


def test_search_empty_no_match_and_wildcards(everywhere):
    for q in ("", "   ", None):
        df, counts = db.search_email_everywhere(q)
        assert df.empty and sum(counts.values()) == 0
    assert db.search_email_everywhere("nobody@nowhere")[0].empty
    assert db.search_email_everywhere("%")[0].empty
    assert db.search_email_everywhere("_bc@email.com")[0].empty


def test_search_is_not_limited_to_a_visible_page():
    db.store_records("mql", "Big", [{"email": f"lead{i:04d}@big.com"} for i in range(1200)])
    db.store_records("bounce", "Late", [{"email": "lead1199@big.com"}])
    df, counts = db.search_email_everywhere("lead1199")
    assert set(df["category_label"]) == {"MQL", "Bounce"}
    df, counts = db.search_email_everywhere("@big.com", limit_per_category=50)
    assert counts["mql"] == 1200 and (df["category"] == "mql").sum() == 50
    assert (df["category"] == "bounce").sum() == 1  # one category's volume never hides another's matches

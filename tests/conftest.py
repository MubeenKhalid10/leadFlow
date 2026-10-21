"""
Test setup: point db.py at a disposable local PostgreSQL database.

The tests write and TRUNCATE tables, so they only run when LEADFLOW_TEST_PG_HOST etc. name a
local database whose name contains "test"; otherwise every test is skipped. They never use
the connection in .streamlit/secrets.toml. Example (Docker):

    docker run -d --rm --name leadflow-test-pg -e POSTGRES_PASSWORD=testpw \
        -e POSTGRES_DB=leadflow_test -p 55432:5432 postgres:16-alpine
    LEADFLOW_TEST_PG_HOST=localhost LEADFLOW_TEST_PG_PORT=55432 LEADFLOW_TEST_PG_DATABASE=leadflow_test \
        LEADFLOW_TEST_PG_USER=postgres LEADFLOW_TEST_PG_PASSWORD=testpw python -m pytest tests
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TEST_DB = {
    "PG_HOST": os.environ.get("LEADFLOW_TEST_PG_HOST", ""),
    "PG_PORT": os.environ.get("LEADFLOW_TEST_PG_PORT", "5432"),
    "PG_DATABASE": os.environ.get("LEADFLOW_TEST_PG_DATABASE", ""),
    "PG_USER": os.environ.get("LEADFLOW_TEST_PG_USER", "postgres"),
    "PG_PASSWORD": os.environ.get("LEADFLOW_TEST_PG_PASSWORD", ""),
    "PG_SSLMODE": "disable",
}
DB_CONFIGURED = (
    _TEST_DB["PG_HOST"] in ("localhost", "127.0.0.1")
    and "test" in _TEST_DB["PG_DATABASE"]
)
if DB_CONFIGURED:
    # Environment variables take priority over secrets.toml in db.get_config().
    os.environ.update(_TEST_DB)

ADMIN = {"id": "admin-1", "email": "admin@example.com", "role": "admin"}
USER = {"id": "user-1", "email": "user@example.com", "role": "user"}

_TABLES = ("master_contacts", "master_lists", "mql_emails", "mql_lists", "unsub_emails", "unsub_lists",
           "bounce_emails", "bounce_lists", "upload_history")


NO_DB_MODULES = {"test_auth_screen"}  # these replace every outside service with fakes


def _needs_db(node) -> bool:
    return node.module.__name__.rsplit(".", 1)[-1] not in NO_DB_MODULES


def pytest_collection_modifyitems(config, items):
    if DB_CONFIGURED:
        return
    skip = pytest.mark.skip(reason="set LEADFLOW_TEST_PG_* to a local *test* database (see tests/conftest.py)")
    for item in items:
        if _needs_db(item):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def clean_db(request):
    """Every test starts from empty tables."""
    if not _needs_db(request.node):
        yield
        return
    import db

    assert db.get_config()["host"] in ("localhost", "127.0.0.1"), "refusing to touch a non-local database"
    ok, err = db.init_db()
    assert ok, err
    with db.get_conn() as conn:
        conn.cursor().execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    db.invalidate_caches()
    yield
    db.invalidate_caches()

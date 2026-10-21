"""Sign-in / sign-up screen: mode switch, field checks, and plain-language Supabase errors.
Supabase is replaced by a fake client, so these tests never contact the auth service."""

from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from conftest import ROOT

TIMEOUT = 60


class FakeAuth:
    def __init__(self, error=None, session=True):
        self.error, self.session = error, session

    def _result(self, creds):
        if self.error:
            raise Exception(self.error)
        user = SimpleNamespace(id="u-1", email=creds["email"])
        session = SimpleNamespace(access_token="a", refresh_token="r") if self.session else None
        return SimpleNamespace(session=session, user=user)

    sign_in_with_password = _result
    sign_up = _result


def _screen(monkeypatch, auth=None):
    import Auth

    fake = SimpleNamespace(auth=auth or FakeAuth(), table=lambda name: None)
    monkeypatch.setattr(Auth, "_new_session_client", lambda: fake)
    monkeypatch.setattr(Auth, "_fetch_role", lambda client, uid: "user")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.session_state["_auth_restore_attempted"] = True
    at.run()
    assert not at.exception
    return at


def _submit(at, mode, email, password):
    at.text_input(key=f"{mode}_email").set_value(email)
    at.text_input(key=f"{mode}_password").set_value(password)
    next(b for b in at.button if b.key == f"go_{mode}").click()
    at.run()
    assert not at.exception
    return " ".join(str(m.value) for m in at.markdown)


def test_sign_in_is_the_default_and_the_switch_changes_the_form(monkeypatch):
    at = _screen(monkeypatch)
    page = " ".join(str(m.value) for m in at.markdown)
    assert "Welcome back" in page and {t.key for t in at.text_input} == {"login_email", "login_password"}
    at.segmented_control(key="auth_mode").set_value("Create account")
    at.run()
    page = " ".join(str(m.value) for m in at.markdown)
    assert "Create your account" in page and {t.key for t in at.text_input} == {"signup_email", "signup_password"}


@pytest.mark.parametrize("email,password,expected", [
    ("", "", "Enter your email and password"),
    ("not-an-email", "secret1", "doesn&#x27;t look right"),
    ("a@b.com", "", "Enter your password"),
])
def test_sign_in_checks_fields_first(monkeypatch, email, password, expected):
    page = _submit(_screen(monkeypatch), "login", email, password)
    assert expected.replace("&#x27;", "'") in page.replace("&#x27;", "'")


@pytest.mark.parametrize("error,expected", [
    ("Invalid login credentials", "Email or password is incorrect"),
    ("Email not confirmed", "Confirm your email first"),
    ("Request rate limit reached", "Too many attempts"),
    ("socket closed", "We couldn't sign you in"),
])
def test_sign_in_errors_are_plain_language(monkeypatch, error, expected):
    page = _submit(_screen(monkeypatch, FakeAuth(error=error)), "login", "a@b.com", "secret1")
    assert expected in page.replace("&#x27;", "'")
    assert error not in page  # the raw service message is logged, not shown


def test_sign_in_success_signs_the_user_in(monkeypatch):
    at = _screen(monkeypatch)
    _submit(at, "login", "a@b.com", "secret1")
    assert at.session_state["_auth_user"]["email"] == "a@b.com"


def test_sign_up_short_password_and_existing_account(monkeypatch):
    at = _screen(monkeypatch, FakeAuth(error="User already registered"))
    at.segmented_control(key="auth_mode").set_value("Create account")
    at.run()
    assert "too short" in _submit(at, "signup", "a@b.com", "123")
    assert "already exists" in _submit(at, "signup", "a@b.com", "secret1")


def test_sign_up_needing_confirmation_says_so(monkeypatch):
    at = _screen(monkeypatch, FakeAuth(session=False))
    at.segmented_control(key="auth_mode").set_value("Create account")
    at.run()
    page = _submit(at, "signup", "new@b.com", "secret1")
    assert "Account created" in page and "new@b.com" in page
    assert "_auth_user" not in at.session_state

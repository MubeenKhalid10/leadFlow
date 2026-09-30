"""
LeadFlow — Supabase-backed authentication & role-based access control (RBAC).
------------------------------------------------------------------------------

What this module does:
  * Signs users up / logs them in / logs them out via Supabase Auth
  * Reads each user's role ("admin" or "user") from a `profiles` table
  * Provides page-level guards:
        auth.require_login()          -> any signed-in user
        auth.require_role("admin")    -> admins only
  * Renders a small "signed in as ..." + logout widget in the sidebar

This module is self-contained and does not touch db.py (your existing
PostgreSQL suppression database) — Supabase is used purely for auth +
the `profiles` table that stores each user's role.

------------------------------------------------------------------------------
ONE-TIME SUPABASE SETUP
------------------------------------------------------------------------------
1. Create a free project at https://supabase.com
2. Project Settings -> API -> copy the "Project URL" and the "anon public" key.
3. Add them to .streamlit/secrets.toml:

        [supabase]
        url = "https://YOUR-PROJECT.supabase.co"
        anon_key = "eyJhbGciOi..."

   or, for Docker / AWS deployments, set the environment variables
   SUPABASE_URL and SUPABASE_KEY instead (secrets win when both exist).

4. In the Supabase SQL editor, run this once to create the roles table,
   auto-provision a profile row on signup, and set up RLS so:
     - every user can read/update their OWN profile
     - admins can read/update EVERY profile (needed for the "Manage Users" page)

        create type user_role as enum ('admin', 'user');

        create table public.profiles (
            id uuid references auth.users on delete cascade primary key,
            email text,
            role user_role not null default 'user',
            created_at timestamptz default now()
        );

        alter table public.profiles enable row level security;

        -- Bypasses RLS safely to avoid recursive-policy issues
        create or replace function public.is_admin()
        returns boolean
        language sql
        security definer
        set search_path = public
        as $$
            select exists (
                select 1 from public.profiles
                where id = auth.uid() and role = 'admin'
            );
        $$;

        create policy "Users read own profile"
            on public.profiles for select
            using (auth.uid() = id);

        create policy "Users update own profile"
            on public.profiles for update
            using (auth.uid() = id);

        create policy "Admins read all profiles"
            on public.profiles for select
            using (public.is_admin());

        create policy "Admins update all profiles"
            on public.profiles for update
            using (public.is_admin());

        -- Auto-create a profile row whenever someone signs up
        create function public.handle_new_user()
        returns trigger as $$
        begin
            insert into public.profiles (id, email) values (new.id, new.email);
            return new;
        end;
        $$ language plpgsql security definer;

        create trigger on_auth_user_created
            after insert on auth.users
            for each row execute procedure public.handle_new_user();

5. Promote your first admin (everyone else defaults to "user"):

        update public.profiles set role = 'admin' where email = 'you@company.com';

6. Install the client library:

        pip install supabase

------------------------------------------------------------------------------
"""

from __future__ import annotations

import html
import json
import os
from typing import Any
from urllib.parse import quote, unquote

import streamlit as st
import streamlit.components.v1 as components

try:
    from supabase import create_client, Client, ClientOptions
except ImportError:  # pragma: no cover - package not installed yet
    create_client = None
    Client = None
    ClientOptions = None


# ------------------------------------------------------------------------- #
# Client
# ------------------------------------------------------------------------- #
def _credentials() -> tuple[str, str]:
    if create_client is None:
        raise RuntimeError(
            "The `supabase` package isn't installed. Run: pip install supabase"
        )
    # 1) Streamlit secrets ([supabase] url / anon_key) — local development.
    #    st.secrets raises when no secrets file exists at all (e.g. in Docker),
    #    so guard it and fall through to the environment.
    url = key = None
    try:
        cfg = st.secrets.get("supabase", None) or {}
        url, key = cfg.get("url"), cfg.get("anon_key")
    except Exception:
        pass
    # 2) Environment variables — AWS / Docker deployment.
    if not url:
        url = os.environ.get("SUPABASE_URL")
    if not key:
        key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Add a [supabase] url / anon_key section to "
            ".streamlit/secrets.toml, or set the SUPABASE_URL and SUPABASE_KEY "
            "environment variables (see auth.py docstring)."
        )
    return url, key


@st.cache_resource(show_spinner=False)
def _anon_client() -> Any:
    """Process-wide anonymous client (no user session attached)."""
    url, key = _credentials()
    return create_client(url, key)


def _new_session_client() -> "Client":
    """A client dedicated to ONE browser session.

    Auth state (tokens) is stored on the client object, so sharing a single
    client between users would mix their sessions. Background token refresh is
    off; get_session() refreshes on demand instead (see get_client()).
    """
    url, key = _credentials()
    return create_client(url, key, options=ClientOptions(auto_refresh_token=False))


def get_client() -> "Client":
    """Returns the signed-in user's own client (tokens refreshed if needed),
    or the shared anonymous client when nobody is signed in."""
    client = st.session_state.get("_auth_client")
    if client is None:
        return _anon_client()
    try:
        session = client.auth.get_session()  # refreshes when expired
        if session is not None:
            stored = st.session_state.get("_auth_session") or {}
            if session.access_token != stored.get("access_token"):
                _store_session(session)
    except Exception:
        pass
    return client


# ------------------------------------------------------------------------- #
# Persistent login (browser cookie)
# ------------------------------------------------------------------------- #
# Streamlit's session_state dies on every browser refresh, so the Supabase
# token pair is also kept in a cookie. On a fresh Streamlit session the cookie
# is read back (st.context.cookies) and the Supabase session is restored,
# refreshing the access token when it has expired. When the refresh token
# itself is no longer valid, the user simply sees the login form again.
_COOKIE_NAME = "lf_auth"
_COOKIE_MAX_AGE = 7 * 24 * 3600  # browser keeps it 7 days; Supabase decides real validity


def _read_cookie() -> dict | None:
    try:
        raw = st.context.cookies.get(_COOKIE_NAME)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(unquote(raw))
    except Exception:
        return None
    if isinstance(data, dict) and data.get("refresh_token") and data.get("access_token"):
        return data
    return None


def _queue_cookie(value: dict | None) -> None:
    """Remember a cookie write for the next script run (a st.rerun() right after
    a login would otherwise drop the component that performs the write)."""
    st.session_state["_auth_cookie_pending"] = value if value else "clear"


def _flush_cookie() -> None:
    pending = st.session_state.pop("_auth_cookie_pending", None)
    if pending is None:
        return
    if pending == "clear":
        js = f"parent.document.cookie = '{_COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax';"
    else:
        val = quote(json.dumps(pending), safe="")
        js = (
            f"parent.document.cookie = '{_COOKIE_NAME}={val}; Max-Age={_COOKIE_MAX_AGE}; "
            "Path=/; SameSite=Lax' + (parent.location.protocol === 'https:' ? '; Secure' : '');"
        )
    components.html(f"<script>{js}</script>", height=0, width=0)


def _store_session(session) -> None:
    tokens = {"access_token": session.access_token, "refresh_token": session.refresh_token}
    st.session_state["_auth_session"] = tokens
    _queue_cookie(tokens)


def _restore_from_cookie() -> None:
    """Rebuild the Supabase session from the cookie, if there is a usable one."""
    if st.session_state.get("_auth_restore_attempted"):
        return
    st.session_state["_auth_restore_attempted"] = True
    data = _read_cookie()
    if not data:
        return
    try:
        client = _new_session_client()
        res = client.auth.set_session(data["access_token"], data["refresh_token"])
        if res is None or res.session is None or res.user is None:
            raise RuntimeError("no session")
        st.session_state["_auth_client"] = client
        _complete_login(client, res.session, res.user)  # role is re-read, never trusted from the cookie
    except Exception:
        _queue_cookie(None)


def _fetch_role(client, user_id: str) -> str:
    """Looks up the caller's role from public.profiles. Defaults to 'user'."""
    try:
        res = (
            client.table("profiles")
            .select("role")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return (res.data or {}).get("role", "user")
    except Exception:
        return "user"


# ------------------------------------------------------------------------- #
# Session helpers
# ------------------------------------------------------------------------- #
def current_user() -> dict | None:
    """Returns {'id', 'email', 'role'} for the signed-in user, or None."""
    return st.session_state.get("_auth_user")


def is_logged_in() -> bool:
    return current_user() is not None


def has_role(*roles: str) -> bool:
    user = current_user()
    return bool(user) and user["role"] in roles


def log_out():
    client = st.session_state.get("_auth_client")
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    st.session_state.pop("_auth_user", None)
    st.session_state.pop("_auth_session", None)
    st.session_state.pop("_auth_client", None)
    _queue_cookie(None)


def _complete_login(client, session, user):
    role = _fetch_role(client, user.id)
    st.session_state["_auth_user"] = {"id": user.id, "email": user.email, "role": role}
    st.session_state["_auth_client"] = client
    _store_session(session)


# ------------------------------------------------------------------------- #
# Styling
# ------------------------------------------------------------------------- #
# Self-contained so the login screen looks fully branded even when it renders
# before theme.py's own CSS has had a chance to run (e.g. on first load,
# before a session exists). Uses the same navy/Libre Franklin identity as
# theme.py; keep these variables in step with the tokens there.
_AUTH_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700&display=swap');

:root {
    --lf-auth-primary: #12305a;
    --lf-auth-primary-soft: #e9eef5;
    --lf-auth-title: #0c1b33;
    --lf-auth-muted: #5a6679;
    --lf-auth-border: #d5dae0;
}

html, body, .stApp, [data-testid="stMarkdownContainer"] {
    font-family: "Libre Franklin", "Segoe UI", sans-serif;
}

.stApp {
    background: #ffffff;
}

/* ---- Login / sign-up card ---- */
.lf-auth-wrap {
    margin: 2.5rem 0 0;
}

.lf-auth-brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.35rem;
}

.lf-auth-brand-icon {
    width: 36px;
    height: 36px;
    border-radius: 4px;
    background: var(--lf-auth-title);
    display: flex;
    align-items: center;
    justify-content: center;
}

.lf-auth-brand-name {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--lf-auth-title);
}

.lf-auth-title {
    font-size: 1.6rem;
    font-weight: 600;
    letter-spacing: -0.015em;
    color: var(--lf-auth-title);
    margin: 1.75rem 0 0.25rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--lf-auth-border);
}

.lf-auth-subtitle {
    color: var(--lf-auth-muted);
    font-size: 0.92rem;
    margin-bottom: 1.4rem;
}

/* The form sits on the page under its tabs; no floating card. */
div.st-key-lf_auth_card [data-testid="stForm"] {
    border: none !important;
    padding: 0.5rem 0 0 !important;
}

/* ---- Access-denied card ---- */
.lf-auth-denied {
    max-width: 520px;
    margin: 2rem auto 1.5rem;
    text-align: center;
    padding: 2.25rem 1.75rem;
    border-top: 1px solid var(--lf-auth-border);
    border-bottom: 1px solid var(--lf-auth-border);
}

/* Streamlit's hidden "link to heading" icon would push the heading off centre. */
.lf-auth-denied [data-testid="stHeaderActionElements"] {
    display: none !important;
}

.lf-auth-denied .lf-auth-denied-icon {
    font-size: 2.1rem;
    line-height: 1;
    margin-bottom: 0.5rem;
    color: var(--lf-auth-muted);
}

.lf-auth-denied h3 {
    color: var(--lf-auth-title);
    margin: 0 0 0.5rem;
}

.lf-auth-denied p {
    color: var(--lf-auth-muted);
    font-size: 0.92rem;
    margin: 0.25rem 0;
}

.lf-auth-role-pill {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--lf-auth-primary);
    background: var(--lf-auth-primary-soft);
    border-radius: 2px;
    padding: 0.15rem 0.5rem;
    margin-top: 0.4rem;
}
</style>
"""


def _inject_auth_css():
    st.markdown(_AUTH_CSS, unsafe_allow_html=True)


def _render_login_form():
    _inject_auth_css()
    # Signed out, the sidebar would hold nothing but a second copy of the name.
    st.markdown(
        '<style>.stApp [data-testid="stSidebar"], .stApp button[data-testid="stExpandSidebarButton"], '
        '.stApp [data-testid="stSidebarCollapsedControl"] { display: none !important; } '
        '.stApp, .stApp [data-testid="stAppViewContainer"], .stApp [data-testid="stMain"], '
        '.stApp [data-testid="stHeader"] { background: #ffffff !important; }</style>',
        unsafe_allow_html=True,
    )

    # The heading shares the form's column, so the two line up on one left edge.
    left, mid, right = st.columns([1, 3, 1])
    mid.markdown(
        """
        <div class="lf-auth-wrap">
            <div class="lf-auth-brand">
                <div class="lf-auth-brand-icon">
                    <svg width="22" height="22" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                        <path d="M7 10h6m-6 4h10m-10 4h8" stroke="white" stroke-width="2.4" stroke-linecap="round"/>
                        <circle cx="20" cy="10" r="3" fill="white" fill-opacity="0.9"/>
                    </svg>
                </div>
                <div class="lf-auth-brand-name">LeadFlow</div>
            </div>
            <div class="lf-auth-title">Sign in to LeadFlow</div>
            <div class="lf-auth-subtitle">
                Clean, filter and split your lead files. New here? Choose <strong>Create account</strong>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with mid:
        with st.container(key="lf_auth_card"):
            tab_login, tab_signup = st.tabs(["Sign in", "Create account"])

            with tab_login:
                with st.form("login_form"):
                    email = st.text_input("Email", key="login_email", placeholder="you@company.com")
                    password = st.text_input("Password", type="password", key="login_password",
                                             placeholder="Your password")
                    submitted = st.form_submit_button("Sign in", type="primary", width="stretch", key="go_login")
                if submitted:
                    try:
                        client = _new_session_client()
                        res = client.auth.sign_in_with_password(
                            {"email": email, "password": password}
                        )
                        _complete_login(client, res.session, res.user)
                        st.rerun()
                    except Exception as e:
                        st.error("**We couldn't sign you in.** Check your email and password and try again.",
                                 icon=":material/error:")
                        st.caption(f"Details: {e}")

            with tab_signup:
                with st.form("signup_form"):
                    new_email = st.text_input(
                        "Email", key="signup_email", placeholder="you@company.com"
                    )
                    new_password = st.text_input(
                        "Password", type="password", key="signup_password",
                        placeholder="At least 6 characters",
                    )
                    st.caption("New accounts start as a standard user. An admin can give you more access.")
                    submitted_signup = st.form_submit_button(
                        "Create account", type="primary", width="stretch", key="go_signup"
                    )
                if submitted_signup:
                    try:
                        client = _new_session_client()
                        res = client.auth.sign_up(
                            {"email": new_email, "password": new_password}
                        )
                        if res.session is None:
                            st.success(
                                "**Account created.** Check your email to confirm it, "
                                "then sign in on the **Sign in** tab.",
                                icon=":material/check_circle:",
                            )
                        else:
                            _complete_login(client, res.session, res.user)
                            st.rerun()
                    except Exception as e:
                        st.error("**We couldn't create your account.** Check your email address and use a password "
                                 "of at least 6 characters, then try again.", icon=":material/error:")
                        st.caption(f"Details: {e}")

    st.stop()


# ------------------------------------------------------------------------- #
# Page guards
# ------------------------------------------------------------------------- #
def require_login():
    """Call at the top of any page that needs a signed-in user.
    Restores a previous login from the browser cookie (page refresh / reload /
    navigating between pages), then renders a login form and halts the page
    if nobody is signed in."""
    if not is_logged_in():
        _restore_from_cookie()
    _flush_cookie()
    if not is_logged_in():
        _render_login_form()


def require_role(*roles: str):
    """Call at the top of restricted pages, e.g. auth.require_role("admin").
    Ensures login first, then blocks (st.stop()) with a friendly message
    if the signed-in user doesn't have one of the given roles."""
    require_login()
    if not has_role(*roles):
        _inject_auth_css()
        user = current_user()
        needed = " or ".join(r.title() for r in roles)
        st.markdown(
            f"""
            <div class="lf-auth-denied">
                <div class="lf-auth-denied-icon"><span class="lf-icon" aria-hidden="true">lock</span></div>
                <h3>You need {needed} access</h3>
                <p>Signed in as <strong>{html.escape(str(user['email']))}</strong></p>
                <span class="lf-auth-role-pill">Current role: {html.escape(str(user['role']))}</span>
                <p style="margin-top: 1rem;">
                    Ask an admin to change your role on the <strong>Users &amp; Access</strong> page
                    if you need this page.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _, link_col, _ = st.columns([2, 1, 2])
        try:
            link_col.page_link("app.py", label="Go to Clean Leads", icon=":material/mop:")
        except Exception:  # page registry unavailable (e.g. headless tests); the sidebar menu still works
            pass
        st.stop()


def render_user_badge():
    """Sidebar widget pinned to the bottom of the sidebar (styled in
    theme.py): who's signed in, their role, and a logout button. Safe to
    call on every page after require_login()/require_role()."""
    user = current_user()
    if not user:
        return
    _inject_auth_css()
    with st.sidebar:
        with st.container(key="lf_sidebar_user_box"):
            initial = html.escape((user["email"] or "?")[0].upper())
            role_label = "Admin" if user["role"] == "admin" else "User"
            st.markdown(
                f"""
                <div class="lf-sidebar-user-card">
                    <div class="lf-sidebar-user-avatar">{initial}</div>
                    <div class="lf-sidebar-user-info">
                        <div class="lf-sidebar-user-email" title="{html.escape(str(user['email']), quote=True)}">{html.escape(str(user['email']))}</div>
                        <div class="lf-sidebar-user-role">{role_label}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Sign out", key="logout_sidebar", icon=":material/logout:", width="stretch"):
                log_out()
                st.rerun()

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

import streamlit as st

try:
    from supabase import create_client, Client
except ImportError:  # pragma: no cover - package not installed yet
    create_client = None
    Client = None


# ------------------------------------------------------------------------- #
# Client
# ------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_client() -> "Client":
    """Returns a cached Supabase client built from st.secrets['supabase']."""
    if create_client is None:
        raise RuntimeError(
            "The `supabase` package isn't installed. Run: pip install supabase"
        )
    cfg = st.secrets.get("supabase", {})
    url, key = cfg.get("url"), cfg.get("anon_key")
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Add a [supabase] url / anon_key "
            "section to .streamlit/secrets.toml (see auth.py docstring)."
        )
    return create_client(url, key)


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
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.pop("_auth_user", None)
    st.session_state.pop("_auth_session", None)


def _complete_login(client, session, user):
    role = _fetch_role(client, user.id)
    st.session_state["_auth_user"] = {"id": user.id, "email": user.email, "role": role}
    st.session_state["_auth_session"] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }


# ------------------------------------------------------------------------- #
# Styling
# ------------------------------------------------------------------------- #
# Self-contained so the login screen looks fully branded even when it renders
# before theme.py's own CSS has had a chance to run (e.g. on first load,
# before a session exists). Uses the same indigo/Manrope identity as the
# rest of LeadFlow. If you'd like this pixel-matched to theme.py's exact
# tokens, share theme.py and these variables can be pointed at it directly.
_AUTH_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --lf-auth-primary: #3c37d6;
    --lf-auth-primary-2: #5a56eb;
    --lf-auth-primary-soft: #eef0ff;
    --lf-auth-title: #161a2d;
    --lf-auth-muted: #7f869b;
    --lf-auth-border: #dde2ef;
}

html, body, [class*="css"] { font-family: "Manrope", "Segoe UI", sans-serif !important; }

.stApp {
    background:
        radial-gradient(1000px 300px at 80% -10%, #e9ecff 0%, rgba(233, 236, 255, 0) 65%),
        linear-gradient(180deg, #fafbff 0%, #f7f8fc 45%, #f6f7fb 100%);
}

/* ---- Login / sign-up card ---- */
.lf-auth-wrap {
    max-width: 440px;
    margin: 2.5rem auto 0;
}

.lf-auth-brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.35rem;
}

.lf-auth-brand-icon {
    width: 40px;
    height: 40px;
    border-radius: 11px;
    background: linear-gradient(135deg, var(--lf-auth-primary), var(--lf-auth-primary-2));
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.15rem;
    box-shadow: 0 8px 16px rgba(60, 55, 214, 0.25);
}

.lf-auth-brand-name {
    font-size: 1.4rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--lf-auth-title);
}

.lf-auth-title {
    font-size: 1.55rem;
    font-weight: 800;
    color: var(--lf-auth-title);
    margin: 1rem 0 0.15rem;
}

.lf-auth-subtitle {
    color: var(--lf-auth-muted);
    font-size: 0.92rem;
    margin-bottom: 1.4rem;
}

div[data-testid="stVerticalBlockBorderWrapper"]:has(div.st-key-lf_auth_card) {
    max-width: 440px;
    margin: 0 auto;
    border-radius: 16px !important;
    border: 1px solid var(--lf-auth-border) !important;
    box-shadow: 0 20px 45px rgba(22, 26, 45, 0.08) !important;
    background: #ffffff !important;
    padding: 0.5rem 0.25rem !important;
}

/* ---- Access-denied card ---- */
.lf-auth-denied {
    max-width: 520px;
    margin: 2rem auto 0;
    text-align: center;
    padding: 2.25rem 1.75rem;
    border: 1px solid var(--lf-auth-border);
    border-radius: 16px;
    background: #ffffff;
    box-shadow: 0 20px 45px rgba(22, 26, 45, 0.08);
}

.lf-auth-denied .lf-auth-denied-icon {
    font-size: 2.1rem;
    margin-bottom: 0.5rem;
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
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--lf-auth-primary);
    background: var(--lf-auth-primary-soft);
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
    margin-top: 0.4rem;
}

/* ---- Sidebar user card, pinned to the bottom of the sidebar ---- */
/* Use flexbox to push the user card to the bottom of the sidebar content area */
[data-testid="stSidebar"] > div:first-child {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

[data-testid="stSidebarUserContent"] {
    display: flex;
    flex-direction: column;
    flex-grow: 1;
}

div.st-key-lf_sidebar_user_box {
    margin-top: auto !important;
    padding-bottom: 1rem !important;
}

/* Ensure navigation doesn't overlap if it gets too long, though flex should handle this */
[data-testid="stSidebarNav"] {
    margin-bottom: 1rem;
}

.lf-sidebar-user-card {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.75rem 0.85rem;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    margin-bottom: 0.6rem;
}

.lf-sidebar-user-avatar {
    flex-shrink: 0;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--lf-auth-primary), var(--lf-auth-primary-2));
    color: #ffffff;
    font-weight: 800;
    font-size: 0.95rem;
    display: flex;
    align-items: center;
    justify-content: center;
}

.lf-sidebar-user-info {
    min-width: 0;
}

.lf-sidebar-user-email {
    font-size: 0.82rem;
    font-weight: 700;
    color: #f1f2fb;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.lf-sidebar-user-role {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #b9bdf0;
}

div.st-key-lf_sidebar_user_box .stButton > button {
    width: 100%;
    border-radius: 9px !important;
    font-weight: 700 !important;
    background: rgba(255, 255, 255, 0.08) !important;
    color: #f1f2fb !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
}

div.st-key-lf_sidebar_user_box .stButton > button:hover {
    background: rgba(255, 255, 255, 0.16) !important;
    border-color: rgba(255, 255, 255, 0.3) !important;
}
</style>
"""


def _inject_auth_css():
    st.markdown(_AUTH_CSS, unsafe_allow_html=True)


def _render_login_form():
    _inject_auth_css()

    st.markdown(
        """
        <div class="lf-auth-wrap">
            <div class="lf-auth-brand">
                <div class="lf-auth-brand-icon">⚡</div>
                <div class="lf-auth-brand-name">LeadFlow</div>
            </div>
            <div class="lf-auth-title">Sign in to your account</div>
            <div class="lf-auth-subtitle">
                New here? Use <strong>Create account</strong> below — you'll start as a standard user.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, mid, right = st.columns([1, 3, 1])
    with mid:
        with st.container(key="lf_auth_card"):
            tab_login, tab_signup = st.tabs(["Log in", "Create account"])

            with tab_login:
                with st.form("login_form"):
                    email = st.text_input("Email", key="login_email", placeholder="you@company.com")
                    password = st.text_input("Password", type="password", key="login_password")
                    submitted = st.form_submit_button("Log in", type="primary", width="stretch")
                if submitted:
                    try:
                        client = get_client()
                        res = client.auth.sign_in_with_password(
                            {"email": email, "password": password}
                        )
                        _complete_login(client, res.session, res.user)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Login failed: {e}")

            with tab_signup:
                with st.form("signup_form"):
                    new_email = st.text_input(
                        "Email", key="signup_email", placeholder="you@company.com"
                    )
                    new_password = st.text_input(
                        "Password", type="password", key="signup_password",
                        help="At least 6 characters.",
                    )
                    submitted_signup = st.form_submit_button(
                        "Create account", type="primary", width="stretch"
                    )
                if submitted_signup:
                    try:
                        client = get_client()
                        res = client.auth.sign_up(
                            {"email": new_email, "password": new_password}
                        )
                        if res.session is None:
                            st.info(
                                "✅ Account created. Check your email to confirm it, "
                                "then log in on the **Log in** tab."
                            )
                        else:
                            _complete_login(client, res.session, res.user)
                            st.rerun()
                    except Exception as e:
                        st.error(f"Sign up failed: {e}")

    st.stop()


# ------------------------------------------------------------------------- #
# Page guards
# ------------------------------------------------------------------------- #
def require_login():
    """Call at the top of any page that needs a signed-in user.
    Renders a login form and halts the page if nobody is signed in."""
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
                <div class="lf-auth-denied-icon">🚫</div>
                <h3>You need {needed} access</h3>
                <p>Signed in as <strong>{user['email']}</strong></p>
                <span class="lf-auth-role-pill">Current role: {user['role']}</span>
                <p style="margin-top: 1rem;">
                    Ask an admin to upgrade your role from the <strong>Manage Users</strong> page
                    if you believe this is a mistake.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()


def render_user_badge():
    """Sidebar widget pinned to the bottom of the sidebar (via flex CSS in
    _AUTH_CSS): who's signed in, their role, and a logout button. Safe to
    call on every page after require_login()/require_role()."""
    user = current_user()
    if not user:
        return
    _inject_auth_css()
    with st.sidebar:
        with st.container(key="lf_sidebar_user_box"):
            initial = (user["email"] or "?")[0].upper()
            role_label = "Admin" if user["role"] == "admin" else "User"
            st.markdown(
                f"""
                <div class="lf-sidebar-user-card">
                    <div class="lf-sidebar-user-avatar">{initial}</div>
                    <div class="lf-sidebar-user-info">
                        <div class="lf-sidebar-user-email">{user['email']}</div>
                        <div class="lf-sidebar-user-role">{role_label}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Log out", key="_sidebar_logout"):
                log_out()
                st.rerun()

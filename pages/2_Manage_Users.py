"""
LeadFlow — Manage Users (Admin only)
--------------------------------------------------------------------------

Lets an admin see every signed-up user and promote/demote them between
the "user" and "admin" roles. Relies on the RLS policies described in
auth.py's setup docstring (admins can read/update every row in
public.profiles; everyone else can only see their own row).
"""

import pandas as pd
import streamlit as st

import Auth as auth
import theme

st.set_page_config(page_title="Users & Access — LeadFlow", page_icon="👥", layout="wide")
theme.inject_theme()
theme.inject_sidebar_title()

auth.require_role("admin")
auth.render_user_badge()
theme.sidebar_nav(auth.current_user(), current="pages/2_Manage_Users.py")

theme.page_header("group", "Users & Access", "Choose who can manage the lead database and other users.")

try:
    client = auth.get_client()
    res = client.table("profiles").select("id, email, role, created_at").execute()
    profiles = pd.DataFrame(res.data or [])
except Exception as e:
    theme.friendly_error("Couldn't load the list of users", "Please refresh the page and try again.", e)
    st.stop()

if profiles.empty:
    theme.empty_state("group", "No users yet", "People appear here after they create an account on the sign-in screen.")
    st.stop()

profiles = profiles.sort_values("created_at")
me = auth.current_user()

with theme.card("users"):
    theme.section_header(
        None, "Team members",
        "<b>Admin</b> — can open the Lead Database and this page. "
        "<b>User</b> — can clean, split and download leads.",
        "group",
    )
    _admins = int((profiles["role"] == "admin").sum())
    st.caption(
        f"{len(profiles)} {'user' if len(profiles) == 1 else 'users'} · "
        f"{_admins} {'admin' if _admins == 1 else 'admins'}. Pick a new role, then click Save role."
    )

    widths = [4, 2, 2, 2]
    heads = ["Email", "Joined", "Current role", "Change role"]
    theme.table_header("users", widths, heads)

    for row in profiles.itertuples():
        c1, c2, c3, c4 = theme.table_row(f"user_{row.id}", widths)
        theme.table_cell(c1, heads[0], row.email, strong=True,
                         suffix=' <span class="lf-you">you</span>' if row.id == me["id"] else "")
        theme.table_cell(c2, heads[1], f"{pd.to_datetime(row.created_at):%d-%b-%Y}")
        theme.table_cell(c3, heads[2], "Admin" if row.role == "admin" else "User",
                         icon_name="shield_person" if row.role == "admin" else "person")

        with c4:
            is_self = row.id == me["id"]
            new_role = st.selectbox(
                heads[3],
                ["user", "admin"],
                index=["user", "admin"].index(row.role),
                format_func=str.title,
                key=f"role_select_{row.id}",
                label_visibility="collapsed",
                disabled=is_self,
            )
            if not is_self and new_role != row.role:
                if st.button("Save role", key=f"save_role_{row.id}", type="primary", width="stretch",
                             help=f"Make {row.email} {'an admin' if new_role == 'admin' else 'a standard user'}."):
                    try:
                        client.table("profiles").update({"role": new_role}).eq(
                            "id", row.id
                        ).execute()
                        st.toast(f"{row.email} is now {'an admin' if new_role == 'admin' else 'a standard user'}.", icon=":material/check_circle:")
                        st.rerun()
                    except Exception as e:
                        theme.friendly_error("Couldn't change this role", "Nothing was changed. Please try again.", e)

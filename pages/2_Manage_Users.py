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

st.set_page_config(page_title="LeadFlow — Manage Users", page_icon="👥", layout="wide")
theme.inject_theme()
theme.inject_sidebar_title()

auth.require_role("admin")
auth.render_user_badge()

st.markdown('<div class="lf-topbar">', unsafe_allow_html=True)
theme.render_topbar(show_how=False)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("## 👥 Manage Users")
st.caption("Promote a teammate to admin, or move an admin back to a standard user.")

try:
    client = auth.get_client()
    res = client.table("profiles").select("id, email, role, created_at").execute()
    profiles = pd.DataFrame(res.data or [])
except Exception as e:
    st.error(f"Couldn't load users: {e}")
    st.stop()

if profiles.empty:
    st.info("No users yet.")
    st.stop()

profiles = profiles.sort_values("created_at")
me = auth.current_user()

st.caption(f"{len(profiles)} user(s) total")
st.divider()

for row in profiles.itertuples():
    c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
    c1.markdown(f"**{row.email}**" + (" · _you_" if row.id == me["id"] else ""))
    c2.caption(f"Joined {pd.to_datetime(row.created_at):%Y-%m-%d}")
    c3.markdown("🛡️ Admin" if row.role == "admin" else "👤 User")

    with c4:
        is_self = row.id == me["id"]
        new_role = st.selectbox(
            "Role",
            ["user", "admin"],
            index=["user", "admin"].index(row.role),
            key=f"role_select_{row.id}",
            label_visibility="collapsed",
            disabled=is_self,
            help="You can't change your own role." if is_self else None,
        )
        if not is_self and new_role != row.role:
            if st.button("Save", key=f"role_save_{row.id}", type="primary"):
                try:
                    client.table("profiles").update({"role": new_role}).eq(
                        "id", row.id
                    ).execute()
                    st.success(f"Updated {row.email} to **{new_role}**.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")
    st.divider()

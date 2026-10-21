"""
LeadFlow — server entry point.

Runs the normal Streamlit app (app.py and pages/) plus one extra HTTP route that
streams prepared database backups from disk (see backup.py):

    streamlit run asgi_app.py
"""

import streamlit as st

import backup

app = st.App("app.py", routes=backup.routes())

"""
LeadFlow — shared UI theme
--------------------------

The visual layer (fonts, colours, page and section headers, status messages,
sidebar branding and the "How it works" dialog) lives here so every page — the
Clean Leads page, the Lead Database page and the Users & Access page — looks and
behaves the same.

Usage on each page (after st.set_page_config):
    import theme
    theme.inject_theme()
    theme.inject_sidebar_title()
    theme.page_header("🧹", "Clean Leads", "One sentence on what this page is for.")
    ...
    theme.section_header(1, "Upload your lead file", "Add a CSV or Excel file to begin.", icon="📤")
"""

import html
import logging

import streamlit as st

_log = logging.getLogger("leadflow")


# The main page's workflow, shown as a progress strip under the page header.
WORKFLOW_STEPS = [
    ("Upload", "Add your lead file"),
    ("Review", "Check columns & options"),
    ("Clean", "Remove unwanted leads"),
    ("Download", "Get your campaign files"),
]


@st.dialog("How LeadFlow works")
def show_how_it_works():
    st.markdown(
        """
        **1. Upload** — add a CSV or Excel file of leads.

        **2. Review** — check that LeadFlow matched your columns (only **Email** is
        required) and tick the saved lists whose leads you want removed:
        **Master**, **Bounced**, **MQL** and **Unsubscribed**.

        **3. Clean** — LeadFlow removes leads with no email, India-based contacts,
        rows with garbled characters, duplicates, and anyone on the ticked lists.

        **4. Download** — get the full campaign file, or split it by country or by
        a field such as Industry. Downloading a split removes those leads from the
        campaign file, so nobody gets the same campaign twice.
        """
    )
    st.caption("Admins manage the saved lists on the Lead Database page.")


def page_header(icon, title, subtitle, show_how=False):
    """Top of every page: where you are (title) and what the page is for (one sentence).

    `show_how` adds a small "How it works" help button on the right.
    """
    text_col, help_col = st.columns([5, 1], vertical_alignment="center")
    text_col.markdown(
        f'<header class="lf-page-head"><h1 class="lf-page-title">'
        f'<span aria-hidden="true">{icon}</span> {html.escape(title)}</h1>'
        f'<p class="lf-page-sub">{html.escape(subtitle)}</p></header>',
        unsafe_allow_html=True,
    )
    if show_how and help_col.button("How it works", key="how_it_works_btn", type="tertiary",
                                    icon=":material/help:", width="stretch"):
        show_how_it_works()


def inject_sidebar_title():
    """Inject the LeadFlow branding title into the sidebar top."""
    st.sidebar.markdown(
        """
        <div class="lf-sidebar-header">
            <div class="lf-sidebar-logo">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="28" height="28" rx="8" fill="#4f46e5"/>
                    <path d="M7 10h6m-6 4h10m-10 4h8" stroke="white" stroke-width="2" stroke-linecap="round"/>
                    <circle cx="20" cy="10" r="3" fill="white" fill-opacity="0.9"/>
                </svg>
            </div>
            <div class="lf-sidebar-title-text">
                <span class="lf-sidebar-brand-name">LeadFlow</span>
                <span class="lf-sidebar-brand-sub">Lead data cleaning</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Sidebar menu: (page file, label, icon, admin only, tooltip). Replaces Streamlit's
# file-name based menu (hidden via client.showSidebarNavigation in config.toml).
NAV_PAGES = [
    ("app.py", "Clean Leads", "🧹", False, "Upload a lead file, clean it, then split and download your campaign."),
    ("pages/1_Database.py", "Lead Database", "🗄️", True, "Your saved Master, MQL, Bounced and Unsubscribed lists."),
    ("pages/2_Manage_Users.py", "Users & Access", "👥", True, "Choose who has admin access."),
]


def sidebar_nav(user=None, current="app.py"):
    """Named page links in the sidebar. Admin pages stay visible to everyone (they guard
    themselves) but are greyed out for non-admins so it's clear they need admin access.
    `current` is this page's file, so its link can be highlighted."""
    is_admin = bool(user) and user.get("role") == "admin"
    with st.sidebar:
        st.markdown('<div class="lf-sidebar-nav-label">Menu</div>', unsafe_allow_html=True)
        for page, label, icon, admin_only, tip in NAV_PAGES:
            locked = admin_only and not is_admin
            # st.page_link exposes no "current page" attribute, so wrap it in a keyed container for the CSS.
            slot = st.container(key="lf_nav_current") if page == current else st.container()
            try:
                slot.page_link(
                    page,
                    label=f"{label} (admins only)" if locked else label,
                    icon=icon,
                    help="Only admins can open this page." if locked else tip,
                    disabled=locked,
                )
            except Exception as e:  # e.g. a page file missing from this deployment
                _log.warning("Sidebar link to %s unavailable: %s", page, e)


def section_header(number, title, subtitle=None, icon=""):
    """Section heading: an optional step number, the title, and one short line on its purpose.

    Pass a number (1, 2, …) only for real, ordered workflow steps; use None for plain sections.
    """
    badge = (f'<div class="lf-section-badge" aria-hidden="true">{html.escape(str(number))}</div>'
             if number else "")
    step = f'<span class="lf-sr-only">Step {html.escape(str(number))}: </span>' if number else ""
    icon_html = f'<span aria-hidden="true">{icon}</span> ' if icon else ""
    sub = f'<div class="lf-section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="lf-section-head">{badge}<div class="lf-section-text">'
        f'<h2>{step}{icon_html}{title}</h2>{sub}</div></div>',
        unsafe_allow_html=True,
    )


def workflow_steps(current, target=None):
    """Progress strip for the main workflow. Steps before `current` (0-based) are done.

    Pass an st.empty() as `target` to redraw it in place later in the same run.
    """
    parts = []
    for i, (label, hint) in enumerate(WORKFLOW_STEPS):
        state = "done" if i < current else ("active" if i == current else "todo")
        mark = "✓" if state == "done" else str(i + 1)
        status = {"done": "completed", "active": "current step", "todo": "not started"}[state]
        aria = ' aria-current="step"' if state == "active" else ""
        if i:
            parts.append(f'<div class="lf-step-line {"done" if i <= current else ""}"></div>')
        parts.append(
            f'<div class="lf-step {state}"{aria}>'
            f'<span class="lf-step-dot" aria-hidden="true">{mark}</span>'
            f'<span class="lf-step-text"><span class="lf-step-label">{label}</span>'
            f'<span class="lf-step-hint">{hint}</span></span>'
            f'<span class="lf-sr-only">({status})</span></div>'
        )
    (target or st).markdown(
        f'<nav class="lf-stepper" aria-label="Progress">{"".join(parts)}</nav>',
        unsafe_allow_html=True,
    )


def empty_state(icon, title, text=""):
    """Placeholder for a section with nothing to show: what is empty, and what to do about it."""
    st.markdown(
        f'<div class="lf-empty"><div class="lf-empty-icon" aria-hidden="true">{icon}</div>'
        f'<div class="lf-empty-title">{title}</div>'
        + (f'<div class="lf-empty-text">{text}</div>' if text else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def status_line(kind, title, detail=""):
    """Compact one-line state message: ✓ success, ⚠ warning, ✕ error, → next step, • info.

    `title` and `detail` are HTML; escape any user data in them before calling.
    The symbol plus the words carry the meaning, so the state never depends on colour alone.
    """
    symbol = {"success": "✓", "warning": "⚠", "error": "✕", "next": "→", "info": "•"}[kind]
    detail_html = f'<span class="lf-status-detail">{detail}</span>' if detail else ""
    st.markdown(
        f'<div class="lf-status lf-status-{kind}" role="status">'
        f'<span class="lf-status-icon" aria-hidden="true">{symbol}</span>'
        f'<span class="lf-status-title">{title}</span>{detail_html}</div>',
        unsafe_allow_html=True,
    )


def removal_breakdown(groups, total):
    """"Why were leads removed?" panel: reasons in titled groups, each with its count, a bar
    showing its share of `total`, and a subtotal; a total line that matches the Removed metric.

    groups: [(group title, [(label, short hint, count or None if the check didn't run), ...]), ...]
    """
    def row(label, hint, n):
        if n is None:
            return (f'<div class="lf-why-row lf-off"><div class="lf-why-label">{label}'
                    f'<small>list not ticked</small></div><div class="lf-why-bar"></div>'
                    f'<div class="lf-why-count">Not checked</div></div>')
        n = int(n)
        pct = 0 if not total or not n else max(n / total * 100, 1.5)
        return (f'<div class="lf-why-row{" lf-zero" if not n else ""}"><div class="lf-why-label">{label}'
                f'<small>{hint}</small></div>'
                f'<div class="lf-why-bar" aria-hidden="true"><span style="width:{pct:.1f}%"></span></div>'
                f'<div class="lf-why-count">{n:,}</div></div>')

    sections = []
    for title, rows in groups:
        subtotal = sum(int(n) for _, _, n in rows if n)
        sections.append(
            f'<section class="lf-why-group"><div class="lf-why-group-head"><span>{title}</span>'
            f'<b>{subtotal:,}</b></div>' + "".join(row(*r) for r in rows) + "</section>"
        )
    st.markdown(
        f'<div class="lf-why" role="group" aria-label="Why leads were removed">'
        f'<div class="lf-why-title">Why were leads removed?</div>'
        f'<div class="lf-why-groups">{"".join(sections)}</div>'
        f'<div class="lf-why-total"><span>Total removed</span><b>{total:,}</b></div></div>',
        unsafe_allow_html=True,
    )


def card(key):
    """Solid, bordered container for one page section: `with theme.card("upload"): ...`.

    Just a keyed st.container; its look comes from the st-key-lf_card_ rule in inject_theme().
    Keys must be unique on a page.
    """
    return st.container(key=f"lf_card_{key}")


def subcard(key):
    """Lightly tinted group inside a card, for related controls that belong together."""
    return st.container(key=f"lf_subcard_{key}")


def friendly_error(title, message, error=None):
    """Plain-language error with a next step; the raw error goes to the log and a small caption."""
    st.error(f"**{title}**  \n{message}", icon=":material/error:")
    if error is not None:
        _log.error("%s: %s", title, error, exc_info=error if isinstance(error, BaseException) else None)
        st.caption(f"Technical details: {type(error).__name__}: {html.escape(str(error))[:500]}")


def inject_theme():
    """Inject the global CSS. Call once per page after set_page_config."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        :root {
            --lf-bg: #f7f8fc;
            --lf-surface: #ffffff;
            --lf-border: #dde2ef;
            --lf-title: #161a2d;
            --lf-body: #4c5268;
            --lf-muted: #646b82;
            --lf-input-border: #8b93ab;
            --lf-focus: 0 0 0 3px rgba(79, 70, 229, 0.35);
            --lf-primary: #4f46e5;
            --lf-primary-hover: #4338ca;
            --lf-primary-2: #6366f1;
            --lf-primary-3: #818cf8;
            --lf-primary-soft: #eef0ff;
            --lf-primary-glow: rgba(79, 70, 229, 0.18);
            --lf-success: #059669;
            --lf-success-soft: #d1fae5;
            --lf-danger: #dc2626;
            --lf-danger-soft: #fee2e2;
            --lf-warning: #d97706;
            --lf-warning-soft: #fef3c7;
            --lf-shadow-sm: 0 1px 3px rgba(22, 26, 45, 0.07), 0 1px 2px rgba(22, 26, 45, 0.04);
            --lf-shadow-md: 0 4px 16px rgba(22, 26, 45, 0.08), 0 2px 6px rgba(22, 26, 45, 0.05);
            --lf-shadow-lg: 0 10px 30px rgba(22, 26, 45, 0.10), 0 4px 12px rgba(22, 26, 45, 0.06);
            --lf-shadow-primary: 0 1px 2px rgba(22, 26, 45, 0.12);
            --lf-radius: 14px;
            --lf-radius-sm: 10px;
            --lf-sidebar-bg: #0d0f1c;
            --lf-sidebar-surface: #141728;
            --lf-sidebar-border: rgba(99, 102, 241, 0.15);
            --lf-sidebar-text: #c7caf5;
            --lf-sidebar-muted: #6b6f9a;
        }

        html, body, [class*="css"] {
            font-family: "Manrope", "Inter", "Segoe UI", sans-serif !important;
        }

        /* ---------------------------------------------------------------
           TEXT VISIBILITY
           LeadFlow is a light-surface design. Browsers in dark mode used to
           make Streamlit render white default text on these light surfaces,
           so headings/labels/table text disappeared. Pin the colour scheme
           and the base text colour here (config.toml [theme] does the same
           for Streamlit's own widgets), so every page inherits readable text.
           --------------------------------------------------------------- */
        :root, .stApp {
            color-scheme: light;
        }
        [data-testid="stAppViewContainer"] [data-testid="stMain"],
        [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stMarkdownContainer"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stWidgetLabel"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stCaptionContainer"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stExpander"] summary,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stMetricLabel"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stFileUploader"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stCheckbox"],
        [data-testid="stAppViewContainer"] [data-testid="stMain"] .stDataFrame,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stTable"] {
            color: var(--lf-body);
        }
        [data-testid="stAppViewContainer"] [data-testid="stMain"] h1,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] h2,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] h3,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] h4,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-testid="stMetricValue"] {
            color: var(--lf-title);
        }
        [data-testid="stAppViewContainer"] [data-testid="stMain"] input,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] textarea,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-baseweb="select"] div,
        [data-baseweb="popover"] [role="option"],
        [data-baseweb="menu"] [role="option"] {
            color: var(--lf-title);
        }
        [data-testid="stAppViewContainer"] [data-testid="stMain"] input,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] textarea,
        [data-testid="stAppViewContainer"] [data-testid="stMain"] [data-baseweb="select"] > div,
        [data-baseweb="popover"] ul,
        [data-baseweb="menu"] {
            background-color: #ffffff;
        }
        /* Keep white text on filled primary buttons and the active tab. */
        .stButton button[kind="primary"] *,
        [data-testid="stDownloadButton"] button[kind="primary"] *,
        [data-testid="stTabs"] [aria-selected="true"] * {
            color: #ffffff !important;
        }

        /* ---------------------------------------------------------------
           MAIN BACKGROUND
           --------------------------------------------------------------- */
        .stApp {
            background: var(--lf-bg);
        }

        [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"] {
            max-width: 1140px;
            padding-top: 4.25rem;
            padding-bottom: 3.5rem;
        }

        [data-testid="stHeader"] {
            background: rgba(247, 248, 252, 0.88);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-bottom: 1px solid rgba(221, 226, 239, 0.7);
        }

        /* ---------------------------------------------------------------
           SIDEBAR — Dark premium design
           --------------------------------------------------------------- */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0d0f1c 0%, #111328 40%, #0f1120 100%) !important;
            border-right: 1px solid rgba(99, 102, 241, 0.12) !important;
            box-shadow: 4px 0 24px rgba(0, 0, 0, 0.35) !important;
            position: relative !important;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding: 0 0 9rem 0 !important;
    display: flex !important;
    flex-direction: column !important;
    height: 100% !important;
    position: relative !important;
    box-sizing: border-box !important;
}

        /* Move the built-in navigation down so our custom title is above it */
        [data-testid="stSidebarNav"] {
    order: 2 !important;
    margin-bottom: 1rem !important;
    padding-bottom: 1rem !important;
}
        [data-testid="stSidebarContent"] > div:not([data-testid="stSidebarNav"]) {
            order: 1 !important;
        }

        /* Sidebar header / branding */
        .lf-sidebar-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 1.4rem 1.25rem 1rem;
            margin-bottom: 0;
        }

        .lf-sidebar-logo {
            flex-shrink: 0;
            filter: drop-shadow(0 4px 12px rgba(99, 102, 241, 0.5));
        }

        .lf-sidebar-title-text {
            display: flex;
            flex-direction: column;
            gap: 0;
        }

        .lf-sidebar-brand-name {
            font-size: 1.25rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #e0e7ff !important;
            line-height: 1.2;
        }

        .lf-sidebar-brand-sub {
            font-size: 0.65rem;
            font-weight: 600;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #4b5196;
            line-height: 1.3;
        }

        .lf-sidebar-divider {
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, rgba(99, 102, 241, 0.3) 30%, rgba(99, 102, 241, 0.3) 70%, transparent 100%);
            margin: 0.5rem 1rem 0.75rem;
        }

        .lf-sidebar-nav-label {
            font-size: 0.6rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            color: #3d4176;
            padding: 0 1.25rem 0.4rem;
            text-transform: uppercase;
        }

        /* Sidebar navigation links */
        [data-testid="stSidebar"] [data-testid="stSidebarNavItems"] {
            padding: 0 0.75rem 1rem;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
            border-radius: 10px !important;
            padding: 0.65rem 1rem !important;
            margin-bottom: 0.25rem !important;
            color: #8b90cc !important;
            font-weight: 600 !important;
            font-size: 0.875rem !important;
            transition: all 0.18s ease !important;
            background: transparent !important;
            border: 1px solid transparent !important;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
            background: rgba(99, 102, 241, 0.1) !important;
            color: #a5b4fc !important;
            border-color: rgba(99, 102, 241, 0.2) !important;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-selected="true"],
        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"],
        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][data-test-is-active="true"] {
            background: linear-gradient(135deg, rgba(79, 70, 229, 0.25) 0%, rgba(99, 102, 241, 0.15) 100%) !important;
            color: #c7d2fe !important;
            border-color: rgba(99, 102, 241, 0.35) !important;
            box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.15) inset !important;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span {
            color: inherit !important;
        }

        /* Named page links (theme.sidebar_nav) — same look as the built-in menu */
        [data-testid="stSidebar"] [data-testid="stPageLink"] {
            padding: 0 0.75rem;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
            border-radius: 10px !important;
            padding: 0.6rem 0.9rem !important;
            margin-bottom: 0.2rem !important;
            font-weight: 600 !important;
            background: transparent !important;
            border: 1px solid transparent !important;
            transition: background 0.18s ease, border-color 0.18s ease, transform 0.18s ease !important;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span,
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p,
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] p {
            color: #b9bdf0 !important;
            font-size: 0.9rem !important;
            font-weight: 600 !important;
        }

        [data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {
            background: rgba(99, 102, 241, 0.12) !important;
            border-color: rgba(99, 102, 241, 0.25) !important;
        }

        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] {
            background: rgba(99, 102, 241, 0.24) !important;
            border-color: rgba(129, 140, 248, 0.45) !important;
            /* Accent bar marks the current page without relying on colour alone. */
            box-shadow: inset 3px 0 0 #a5b4fc !important;
        }

        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] span,
        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] p {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] .lf-sidebar-nav-label {
            color: #6b6f9a !important;
            padding: 0.6rem 1.6rem 0.35rem;
        }

        /* Sidebar widget labels and text */
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: #8b90cc !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #c7d2fe !important;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: #6b6f9a !important;
            font-size: 0.8rem;
        }

        [data-testid="stSidebar"] .stButton button {
            background: rgba(99, 102, 241, 0.12) !important;
            color: #a5b4fc !important;
            border: 1px solid rgba(99, 102, 241, 0.25) !important;
        }

        [data-testid="stSidebar"] .stButton button:hover {
            background: rgba(99, 102, 241, 0.22) !important;
            color: #c7d2fe !important;
            border-color: rgba(99, 102, 241, 0.4) !important;
        }

        /* ---------------------------------------------------------------
           SIDEBAR USER BADGE — PINNED TO BOTTOM
           --------------------------------------------------------------- */
        div.st-key-lf_sidebar_user_box {
            position: absolute !important;
            left: 0.75rem !important;
            right: 0.75rem !important;
            bottom: 1rem !important;
            width: auto !important;
            max-width: none !important;
            margin: 0 !important;
            padding: 0 !important;
            z-index: 1000 !important;
        }

        .lf-sidebar-user-card {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            padding: 0.75rem 0.85rem;
            margin-bottom: 0.6rem;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
        }

        .lf-sidebar-user-avatar {
            flex-shrink: 0;
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background: linear-gradient(135deg, #4f46e5, #6366f1);
            color: #ffffff !important;
            font-weight: 800;
            font-size: 0.95rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .lf-sidebar-user-info {
            min-width: 0;
            flex: 1;
        }

        .lf-sidebar-user-email {
            font-size: 0.82rem;
            font-weight: 700;
            color: #f1f2fb !important;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .lf-sidebar-user-role {
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #a5b4fc !important;
        }

        div.st-key-lf_sidebar_user_box .stButton {
            width: 100% !important;
            margin: 0 !important;
        }

        div.st-key-lf_sidebar_user_box .stButton button {
            width: 100% !important;
            min-height: 2.35rem !important;
            border-radius: 9px !important;
            font-weight: 700 !important;
            font-size: 0.82rem !important;
            background: rgba(255, 255, 255, 0.08) !important;
            color: #f1f2fb !important;
            border: 1px solid rgba(255, 255, 255, 0.18) !important;
            box-shadow: none !important;
        }

        div.st-key-lf_sidebar_user_box .stButton button:hover {
            background: rgba(255, 255, 255, 0.16) !important;
            border-color: rgba(255, 255, 255, 0.3) !important;
            transform: none !important;
            box-shadow: none !important;
        }

        /* Sidebar scrollbar */
        [data-testid="stSidebar"]::-webkit-scrollbar { width: 4px; }
        [data-testid="stSidebar"]::-webkit-scrollbar-track { background: transparent; }
        [data-testid="stSidebar"]::-webkit-scrollbar-thumb {
            background: rgba(99, 102, 241, 0.2);
            border-radius: 4px;
        }

        /* Sidebar toggle — the ">>" expand button (shown when the sidebar is
           closed) and the "<<" collapse button inside the sidebar header.
           Boxed and highlighted so they are easy to spot. */
        button[data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapseButton"] button {
            width: 2.5rem !important;
            height: 2.5rem !important;
            min-width: 2.5rem !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%) !important;
            border: 1px solid rgba(99, 102, 241, 0.55) !important;
            border-radius: var(--lf-radius-sm) !important;
            box-shadow: var(--lf-shadow-primary) !important;
            opacity: 1 !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease !important;
        }

        button[data-testid="stExpandSidebarButton"]:hover,
        [data-testid="stSidebarCollapseButton"] button:hover {
            background: linear-gradient(135deg, #4338ca 0%, #4f46e5 100%) !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 10px 28px rgba(79, 70, 229, 0.38) !important;
        }

        button[data-testid="stExpandSidebarButton"] span,
        button[data-testid="stExpandSidebarButton"] svg,
        [data-testid="stSidebarCollapseButton"] button span,
        [data-testid="stSidebarCollapseButton"] button svg {
            color: #ffffff !important;
            fill: #ffffff !important;
            font-size: 1.25rem !important;
        }

        /* ---------------------------------------------------------------
           PAGE HEADER (theme.page_header) — where am I, what is this page for
           --------------------------------------------------------------- */
        .lf-page-head {
            padding: 0.1rem 0 0.2rem;
        }

        [data-testid="stAppViewContainer"] [data-testid="stMain"] h1.lf-page-title {
            margin: 0;
            padding: 0;
            color: var(--lf-title);
            font-size: 1.85rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            line-height: 1.2;
        }

        [data-testid="stAppViewContainer"] [data-testid="stMain"] p.lf-page-sub {
            margin: 0.3rem 0 0;
            color: var(--lf-body);
            font-size: 0.98rem;
            font-weight: 500;
        }

        /* ---------------------------------------------------------------
           SECTION HEADERS (theme.section_header)
           --------------------------------------------------------------- */
        .lf-section-head {
            margin-top: 1.1rem;
            margin-bottom: 0.9rem;
            display: flex;
            align-items: flex-start;
            gap: 0.8rem;
        }

        /* Step number — only on real, ordered workflow steps. */
        .lf-section-badge {
            flex-shrink: 0;
            width: 32px;
            height: 32px;
            margin-top: 0.1rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.95rem;
            font-weight: 800;
            color: #ffffff;
            background: var(--lf-primary);
        }

        .lf-section-head h2 {
            margin: 0;
            padding: 0 !important;
            color: var(--lf-title);
            font-size: 1.3rem;
            line-height: 1.3;
            letter-spacing: -0.01em;
            font-weight: 800;
        }

        /* ---------------------------------------------------------------
           STATUS LINES (theme.status_line) — ✓ done, ⚠ check, ✕ failed, → next
           --------------------------------------------------------------- */
        .lf-status {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 0.25rem 0.6rem;
            padding: 0.6rem 0.9rem;
            margin: 0.4rem 0 0.6rem;
            border-radius: var(--lf-radius-sm);
            border: 1px solid;
            font-size: 0.93rem;
        }
        .lf-status-icon { font-weight: 800; }
        .lf-status-title { font-weight: 700; }
        .lf-status-detail { color: var(--lf-body); }
        .lf-status-success { background: #ecfdf5; border-color: #a7f3d0; color: #065f46; }
        .lf-status-warning { background: #fffbeb; border-color: #fcd34d; color: #78350f; }
        .lf-status-error   { background: #fef2f2; border-color: #fca5a5; color: #991b1b; }
        .lf-status-next    { background: var(--lf-primary-soft); border-color: #c7d2fe; color: #3730a3; }
        .lf-status-info    { background: #f8fafc; border-color: var(--lf-border); color: var(--lf-title); }

        /* Small uppercase label above a group of related controls. */
        .lf-group-label {
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--lf-muted);
            margin: 0.9rem 0 0.35rem;
        }

        /* Legend chips (e.g. what "Location Empty" means). */
        .lf-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem 0.9rem;
            margin: 0.1rem 0 0.7rem;
            font-size: 0.85rem;
            color: var(--lf-body);
        }
        .lf-legend b { color: var(--lf-title); }

        /* "Why were leads removed?" (theme.removal_breakdown) */
        .lf-why {
            margin: 0.8rem 0 1rem;
            padding: 1rem 1.1rem 0.9rem;
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius-sm);
            background: #ffffff;
        }
        .lf-why-title {
            font-weight: 800;
            font-size: 1rem;
            color: var(--lf-title);
            margin-bottom: 0.75rem;
        }
        .lf-why-groups {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 0.9rem 1.6rem;
        }
        .lf-why-group-head {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding-bottom: 0.4rem;
            margin-bottom: 0.2rem;
            border-bottom: 2px solid var(--lf-border);
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--lf-muted);
        }
        .lf-why-group-head b {
            font-size: 0.95rem;
            letter-spacing: 0;
            color: var(--lf-title);
            font-variant-numeric: tabular-nums;
        }
        .lf-why-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 90px 6.5rem;
            align-items: center;
            gap: 0.75rem;
            padding: 0.45rem 0;
            border-bottom: 1px solid #eef0f6;
        }
        .lf-why-row:last-child { border-bottom: none; }
        .lf-why-label {
            font-weight: 700;
            font-size: 0.92rem;
            color: var(--lf-title);
            line-height: 1.25;
        }
        .lf-why-label small {
            display: block;
            font-weight: 500;
            font-size: 0.78rem;
            color: var(--lf-muted);
        }
        .lf-why-bar {
            height: 8px;
            border-radius: 999px;
            background: #eef0f6;
            overflow: hidden;
        }
        .lf-why-bar span {
            display: block;
            height: 100%;
            border-radius: 999px;
            background: var(--lf-primary);
        }
        .lf-why-count {
            text-align: right;
            font-weight: 800;
            font-size: 0.95rem;
            color: var(--lf-title);
            font-variant-numeric: tabular-nums;
        }
        .lf-why-row.lf-zero .lf-why-label,
        .lf-why-row.lf-zero .lf-why-count { color: var(--lf-muted); font-weight: 600; }
        .lf-why-row.lf-off .lf-why-label { color: var(--lf-muted); font-weight: 600; }
        .lf-why-row.lf-off .lf-why-bar { background: none; }
        .lf-why-row.lf-off .lf-why-count {
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--lf-muted);
        }
        .lf-why-total {
            display: flex;
            justify-content: space-between;
            margin-top: 0.8rem;
            padding-top: 0.7rem;
            border-top: 2px solid var(--lf-title);
            font-weight: 800;
            color: var(--lf-title);
        }
        .lf-why-total b { font-variant-numeric: tabular-nums; }

        /* ---------------------------------------------------------------
           CARDS / PANELS / EXPANDERS
           --------------------------------------------------------------- */
        [data-testid="stExpander"] {
            border: 1px solid var(--lf-border) !important;
            border-radius: var(--lf-radius-sm) !important;
            background: #ffffff !important;
            margin-bottom: 0.75rem;
            overflow: hidden;
        }

        [data-testid="stExpander"] summary {
            font-weight: 700 !important;
            color: var(--lf-title) !important;
            padding: 0.7rem 1rem !important;
        }

        [data-testid="stExpander"] summary:hover {
            color: var(--lf-primary) !important;
            background: #f8f9fe;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: var(--lf-radius) !important;
        }

        /* Table rows built from columns (e.g. "Your lists"): each row sits in its own box,
           and the heading row gets the same side padding so the columns line up. */
        div[class*="st-key-lf_row_"] {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius-sm);
            background: #ffffff;
            padding: 0.5rem 1rem;
            transition: border-color 0.15s ease, background 0.15s ease;
        }
        div[class*="st-key-lf_row_"]:hover {
            border-color: #c7d2fe;
            background: #fbfbff;
        }
        div[class*="st-key-lf_rowhead_"] {
            padding: 0 calc(1rem + 1px);
        }

        /* ---------------------------------------------------------------
           FILE UPLOADERS
           --------------------------------------------------------------- */
        [data-testid="stFileUploaderDropzone"] {
            border: 2px dashed #9ea7c2;
            border-radius: 12px;
            background: #fbfbff;
            padding: 1.4rem 1.2rem;
            transition: border-color 0.15s ease, background 0.15s ease;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
            border-color: var(--lf-primary);
            background: var(--lf-primary-soft);
        }
        [data-testid="stFileUploaderDropzoneInstructions"] {padding-top: 0.25rem;}
        /* "Upload" is the main action of the upload step. */
        [data-testid="stMain"] [data-testid="stFileUploader"] button[data-testid="stBaseButton-secondary"] {
            background: var(--lf-primary) !important;
            color: #ffffff !important;
            border: 1px solid var(--lf-primary) !important;
            font-weight: 700 !important;
        }
        [data-testid="stMain"] [data-testid="stFileUploader"] button[data-testid="stBaseButton-secondary"] * {
            color: #ffffff !important;
        }
        [data-testid="stMain"] [data-testid="stFileUploader"] button[data-testid="stBaseButton-secondary"]:hover {
            background: var(--lf-primary-hover) !important;
        }

        /* Remove-file button next to an uploaded file: a clear red ✕. */
        [data-testid="stFileUploader"] button[aria-label*="Remove"],
        [data-testid="stFileUploader"] button[title*="Remove"] {
            position: relative !important;
            min-width: 25px !important;
            width: 25px !important;
            height: 25px !important;
            min-height: 25px !important;
            padding: 0 !important;
            background: #ef4444 !important;
            border: 1px solid #dc2626 !important;
            border-radius: 6px !important;
            color: transparent !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            box-shadow: none !important;
        }

        [data-testid="stFileUploader"] button[aria-label*="Remove"] svg,
        [data-testid="stFileUploader"] button[title*="Remove"] svg {
            display: none !important;
        }

        [data-testid="stFileUploader"] button[aria-label*="Remove"]::after,
        [data-testid="stFileUploader"] button[title*="Remove"]::after {
            content: "✕";
            color: #ffffff !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            position: absolute !important;
            top: 50% !important;
            left: 50% !important;
            transform: translate(-50%, -52%) !important;
            pointer-events: none !important;
        }

        [data-testid="stFileUploader"] button[aria-label*="Remove"]:hover,
        [data-testid="stFileUploader"] button[title*="Remove"]:hover {
            background: #dc2626 !important;
            border-color: #b91c1c !important;
        }

        /* ---------------------------------------------------------------
           ALERTS / METRICS / TABLES
           --------------------------------------------------------------- */
        [data-testid="stAlert"] {
            border-radius: var(--lf-radius-sm);
        }

        [data-testid="stMetric"] {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius-sm);
            background: #ffffff;
            padding: 0.75rem 1rem;
        }

        [data-testid="stMetricLabel"] {
            color: var(--lf-muted) !important;
            font-weight: 600 !important;
            font-size: 0.82rem !important;
        }

        [data-testid="stMetricValue"] {
            color: var(--lf-title) !important;
            font-weight: 800 !important;
            font-variant-numeric: tabular-nums;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius-sm);
            overflow: hidden;
        }

        /* ---------------------------------------------------------------
           BUTTONS — one clear hierarchy everywhere:
             primary   filled      the one main action of a section
             secondary white+border other useful actions
             tertiary  text link   help / minor actions
           The key prefix sets the action colour (Streamlit adds an
           st-key-<key> class to the button's container):
             go_ start/continue (brand) · dl_ download (green) · save_ save (blue)
             del_ delete (red) · retry_ retry (amber) · view_ preview (teal)
             reset_ clear/reset (slate)
           Filled colours keep white text at 4.5:1 contrast or better.
           --------------------------------------------------------------- */
        [class*="st-key-go_"]    { --lf-btn-a: #4f46e5; --lf-btn-hover: #4338ca; --lf-btn-soft: #eef0ff; }
        [class*="st-key-dl_"]    { --lf-btn-a: #047857; --lf-btn-hover: #065f46; --lf-btn-soft: #ecfdf5; }
        [class*="st-key-save_"]  { --lf-btn-a: #1d4ed8; --lf-btn-hover: #1e40af; --lf-btn-soft: #eff6ff; }
        [class*="st-key-del_"]   { --lf-btn-a: #b91c1c; --lf-btn-hover: #991b1b; --lf-btn-soft: #fef2f2; }
        [class*="st-key-retry_"] { --lf-btn-a: #b45309; --lf-btn-hover: #92400e; --lf-btn-soft: #fffbeb; }
        [class*="st-key-view_"]  { --lf-btn-a: #0e7490; --lf-btn-hover: #155e75; --lf-btn-soft: #ecfeff; }
        [class*="st-key-reset_"] { --lf-btn-a: #334155; --lf-btn-hover: #1e293b; --lf-btn-soft: #f1f5f9; }

        :is([data-testid="stMain"], [role="dialog"])
            :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"]) button {
            border-radius: 8px !important;
            font-weight: 700 !important;
            min-height: 2.5rem;
            font-size: 0.92rem !important;
            transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
        }

        /* Primary */
        :is([data-testid="stMain"], [role="dialog"])
            button:is([kind="primary"], [kind="primaryFormSubmit"]) {
            background: var(--lf-btn-a, var(--lf-primary)) !important;
            color: #ffffff !important;
            border: 1px solid var(--lf-btn-a, var(--lf-primary)) !important;
            box-shadow: var(--lf-shadow-primary) !important;
        }
        :is([data-testid="stMain"], [role="dialog"])
            button:is([kind="primary"], [kind="primaryFormSubmit"]):hover {
            background: var(--lf-btn-hover, var(--lf-primary-hover)) !important;
            border-color: var(--lf-btn-hover, var(--lf-primary-hover)) !important;
        }

        /* Secondary */
        :is([data-testid="stMain"], [role="dialog"])
            button:is([kind="secondary"], [kind="secondaryFormSubmit"]) {
            background: #ffffff !important;
            color: var(--lf-btn-a, var(--lf-title)) !important;
            border: 1px solid var(--lf-btn-a, var(--lf-input-border)) !important;
            box-shadow: none !important;
        }
        :is([data-testid="stMain"], [role="dialog"])
            button:is([kind="secondary"], [kind="secondaryFormSubmit"]):hover {
            background: var(--lf-btn-soft, var(--lf-primary-soft)) !important;
            color: var(--lf-btn-hover, var(--lf-primary)) !important;
            border-color: var(--lf-btn-hover, var(--lf-primary)) !important;
        }

        /* Tertiary: text link style */
        :is([data-testid="stMain"], [role="dialog"]) button[kind="tertiary"] {
            color: var(--lf-primary) !important;
            min-height: 2.25rem;
            font-weight: 700 !important;
        }
        :is([data-testid="stMain"], [role="dialog"]) button[kind="tertiary"]:hover {
            color: var(--lf-primary-hover) !important;
            text-decoration: underline;
        }

        /* Labels take the button's own text colour. Without this, the page-wide
           text rules (main area and sidebar) recolour the <p> inside each button. */
        :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"])
            button[data-testid^="stBaseButton"] * {
            color: inherit !important;
        }

        /* Log out, on the dark sidebar */
        [data-testid="stSidebar"] .stElementContainer[class*="st-key-logout_"] button[data-testid^="stBaseButton"] {
            background: rgba(239, 68, 68, 0.14) !important;
            color: #fecaca !important;
            border: 1px solid rgba(248, 113, 113, 0.45) !important;
        }
        [data-testid="stSidebar"] .stElementContainer[class*="st-key-logout_"] button[data-testid^="stBaseButton"]:hover {
            background: rgba(239, 68, 68, 0.28) !important;
            color: #ffffff !important;
            border-color: rgba(248, 113, 113, 0.7) !important;
        }

        /* Disabled: plainly grey but still readable, whatever the action colour. */
        .stElementContainer :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"])
            button[data-testid^="stBaseButton"]:disabled {
            background: #e5e7eb !important;
            color: #4b5563 !important;
            border: 1px solid #d1d5db !important;
            box-shadow: none !important;
            opacity: 1 !important;
            cursor: not-allowed !important;
        }

        /* Visible keyboard focus on every interactive control. */
        button:focus-visible,
        a:focus-visible,
        summary:focus-visible,
        [role="tab"]:focus-visible,
        [data-testid="stFileUploaderDropzone"]:focus-within {
            outline: none !important;
            box-shadow: var(--lf-focus) !important;
        }

        /* ---------------------------------------------------------------
           TABS — the selected tab is filled and underlined, so it's obvious
           which one you're viewing (not just by colour).
           --------------------------------------------------------------- */
        [data-testid="stTabs"] [role="tablist"] {
            gap: 0.4rem;
            border-bottom: 1px solid var(--lf-border);
            flex-wrap: wrap;
            padding-bottom: 0.5rem;
            margin-bottom: 0.4rem;
        }

        [data-testid="stTabs"] [data-baseweb="tab-highlight"],
        [data-testid="stTabs"] [data-baseweb="tab-border"] {
            display: none !important;
        }

        [data-testid="stTabs"] [role="tab"] {
            border: 1px solid var(--lf-input-border);
            border-radius: 8px;
            font-weight: 700;
            font-size: 0.9rem;
            color: var(--lf-body);
            padding: 0.5rem 1rem;
            background: #ffffff;
            transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
        }

        [data-testid="stTabs"] [role="tab"]:hover {
            color: var(--lf-primary);
            border-color: var(--lf-primary);
            background: var(--lf-primary-soft);
        }

        [data-testid="stTabs"] [aria-selected="true"] {
            color: #ffffff !important;
            background: var(--lf-primary) !important;
            border: 1px solid var(--lf-primary) !important;
            box-shadow: inset 0 -3px 0 #312e81;
        }

        /* ---------------------------------------------------------------
           FORM CONTROLS — visible borders so every input looks like an input
           --------------------------------------------------------------- */
        :is([data-testid="stMain"], [role="dialog"]) [data-testid="stWidgetLabel"] p {
            font-weight: 700 !important;
            color: var(--lf-title) !important;
        }

        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label {
            font-weight: 600 !important;
            color: var(--lf-body) !important;
        }

        [data-testid="stRadio"] > div {
            gap: 0.6rem;
        }

        div[data-baseweb="radio"] > div:first-child,
        [data-testid="stCheckbox"] span[data-baseweb="checkbox"] > div:first-child {
            border-color: var(--lf-input-border) !important;
        }

        div[data-baseweb="radio"] input:checked + div,
        [data-testid="stCheckbox"] input:checked + span > div:first-child {
            background-color: var(--lf-primary) !important;
            border-color: var(--lf-primary) !important;
        }

        /* The field itself: text inputs, text areas, number inputs, dropdowns and multiselects.
           Streamlit draws these borders in the (white) secondary background colour, so without
           this they're invisible on white cards. */
        :is([data-testid="stMain"], [role="dialog"]) :is(
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stNumberInputContainer"],
            [data-testid="stSelectbox"] > div > div[role="group"],
            [data-testid="stMultiSelect"] > div > div[role="group"]
        ) {
            border: 1px solid var(--lf-input-border) !important;
            border-radius: 8px !important;
            background: #ffffff !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
        }

        :is([data-testid="stMain"], [role="dialog"]) :is(
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stNumberInputContainer"],
            [data-testid="stSelectbox"] > div > div[role="group"],
            [data-testid="stMultiSelect"] > div > div[role="group"]
        ):hover {
            border-color: var(--lf-primary) !important;
        }

        :is([data-testid="stMain"], [role="dialog"]) :is(
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stNumberInputContainer"],
            [data-testid="stSelectbox"] > div > div[role="group"],
            [data-testid="stMultiSelect"] > div > div[role="group"]
        ):focus-within {
            border-color: var(--lf-primary) !important;
            box-shadow: var(--lf-focus) !important;
        }

        [data-testid="stMain"] input::placeholder,
        [data-testid="stMain"] textarea::placeholder {
            color: #8a90a4 !important;
            opacity: 1;
        }

        /* ---------------------------------------------------------------
           GLOBAL LOADING OVERLAY & INTERACTION BLOCKER
           --------------------------------------------------------------- */
        @keyframes global-spinner-spin {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }

        @keyframes lf-overlay-in {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        /* Clicks are blocked at once, but the veil only fades in if the rerun takes
           longer than ~0.4s, so quick interactions don't flash the screen. The veil is
           light and unblurred so progress messages underneath stay readable. */
        [data-testid="stApp"][data-test-script-state="running"]::before {
            content: "";
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(247, 248, 252, 0.45);
            z-index: 999990;
            pointer-events: all !important;
            cursor: wait !important;
            animation: lf-overlay-in 0.2s ease 0.4s both;
        }

        [data-testid="stApp"][data-test-script-state="running"]::after {
            content: "";
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 44px;
            height: 44px;
            border: 4px solid rgba(79, 70, 229, 0.15);
            border-top: 4px solid var(--lf-primary);
            border-radius: 50%;
            z-index: 999999;
            animation: lf-overlay-in 0.2s ease 0.4s both,
                       global-spinner-spin 0.75s cubic-bezier(0.4, 0, 0.2, 1) infinite;
            pointer-events: none !important;
        }

        [data-testid="stApp"][data-test-script-state="running"] button,
        [data-testid="stApp"][data-test-script-state="running"] input,
        [data-testid="stApp"][data-test-script-state="running"] select,
        [data-testid="stApp"][data-test-script-state="running"] [role="button"],
        [data-testid="stApp"][data-test-script-state="running"] [data-testid="stFileUploader"],
        [data-testid="stApp"][data-test-script-state="running"] [data-testid="stCheckbox"],
        [data-testid="stApp"][data-test-script-state="running"] [data-baseweb="select"] {
            pointer-events: none !important;
            cursor: wait !important;
        }

        [data-stale="true"] {
            pointer-events: none !important;
            opacity: 0.7;
            transition: opacity 0.2s ease-in-out;
        }

        [data-testid="stSpinner"] {
            padding: 0.65rem 1rem;
            background: var(--lf-primary-soft);
            border: 1px solid #c7d2fe;
            border-radius: 10px;
            margin: 0.5rem 0;
            font-weight: 500;
            color: #1e293b;
        }

        /* ---------------------------------------------------------------
           DIVIDERS
           --------------------------------------------------------------- */
        [data-testid="stDivider"] hr {
            border-color: #e9ecf6;
            border-width: 1px 0 0;
            margin: 1.5rem 0;
        }

        /* ---------------------------------------------------------------
           SECTION SUBTITLE / HELP TEXT
           --------------------------------------------------------------- */
        .lf-section-sub {
            color: var(--lf-body);
            font-size: 0.93rem;
            font-weight: 500;
            margin-top: 0.2rem;
            line-height: 1.45;
        }

        .lf-sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip: rect(0 0 0 0);
            white-space: nowrap;
        }

        /* ---------------------------------------------------------------
           WORKFLOW STEPPER
           --------------------------------------------------------------- */
        .lf-stepper {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.85rem 1.1rem;
            margin: 0 0 0.5rem;
            background: var(--lf-surface);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
        }

        .lf-step {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            min-width: 0;
        }

        .lf-step-dot {
            flex-shrink: 0;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 0.85rem;
            border: 2px solid #c7cdea;
            color: var(--lf-muted);
            background: #ffffff;
            transition: background 0.25s ease, border-color 0.25s ease, color 0.25s ease;
        }

        .lf-step.done .lf-step-dot {
            background: var(--lf-success);
            border-color: var(--lf-success);
            color: #ffffff;
        }

        .lf-step.active .lf-step-dot {
            background: var(--lf-primary);
            border-color: var(--lf-primary);
            color: #ffffff;
            box-shadow: 0 0 0 4px var(--lf-primary-glow);
        }

        .lf-step.active .lf-step-label { color: var(--lf-primary); }

        .lf-step-text {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        .lf-step-label {
            font-weight: 800;
            font-size: 0.9rem;
            color: var(--lf-title);
        }

        .lf-step.todo .lf-step-label { color: var(--lf-muted); }

        .lf-step-hint {
            font-size: 0.74rem;
            color: var(--lf-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .lf-step-line {
            flex: 1;
            height: 2px;
            min-width: 1rem;
            background: #e1e5f2;
            border-radius: 2px;
            transition: background 0.25s ease;
        }

        .lf-step-line.done { background: var(--lf-success); }

        /* ---------------------------------------------------------------
           EMPTY STATES
           --------------------------------------------------------------- */
        .lf-empty {
            text-align: center;
            padding: 1.6rem 1.2rem;
            margin: 0.5rem 0 1rem;
            border: 1.5px dashed #cfd5ec;
            border-radius: var(--lf-radius);
            background: #fbfcff;
        }

        .lf-empty-icon { font-size: 1.9rem; line-height: 1; margin-bottom: 0.45rem; }

        .lf-empty-title {
            font-weight: 800;
            font-size: 1.02rem;
            color: var(--lf-title);
        }

        .lf-empty-text {
            color: var(--lf-body);
            font-size: 0.9rem;
            margin-top: 0.25rem;
        }

        /* Warning note shown next to split downloads */
        .lf-note {
            display: flex;
            gap: 0.5rem;
            align-items: flex-start;
            padding: 0.6rem 0.85rem;
            margin: 0.35rem 0 0.6rem;
            border-radius: var(--lf-radius-sm);
            background: var(--lf-warning-soft);
            border: 1px solid #fcd34d;
            color: #78350f;
            font-size: 0.87rem;
            font-weight: 600;
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                animation-delay: 0s !important;
                transition-duration: 0.01ms !important;
            }
        }

        @media (max-width: 900px) {
            .lf-step-hint { display: none; }
            .lf-stepper { padding: 0.7rem 0.8rem; gap: 0.35rem; }
        }

        @media (max-width: 560px) {
            /* Only the current step keeps its label on phones; the rest show just their dot. */
            .lf-step:not(.active) .lf-step-text { display: none; }
            .lf-step-label { font-size: 0.82rem; white-space: nowrap; }
            .lf-step-dot { width: 26px; height: 26px; font-size: 0.78rem; }
            .lf-step-line { min-width: 0.4rem; }
        }

        /* ---------------------------------------------------------------
           SECTION CARDS (theme.card / theme.subcard)
           Each workflow section sits on its own solid card so sections read
           as separate blocks; related controls inside a section can share a
           tinted sub-card.
           --------------------------------------------------------------- */
        div[class*="st-key-lf_card_"] {
            background: var(--lf-surface);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            padding: 0.35rem 1.5rem 1.4rem;
            margin-bottom: 1rem;
        }

        div[class*="st-key-lf_card_"] .lf-section-head {
            margin-top: 1rem;
        }

        div[class*="st-key-lf_subcard_"] {
            background: #f7f8fc;
            border: 1px solid #e3e7f3;
            border-radius: var(--lf-radius-sm);
            padding: 0.25rem 1.2rem 1.1rem;
        }

        div[class*="st-key-lf_subcard_"] .lf-section-head {
            margin-top: 0.8rem;
        }

        /* Section titles inside cards. */
        [data-testid="stAppViewContainer"] [data-testid="stMain"] .lf-section-head h2 {
            color: var(--lf-title);
            font-size: 1.3rem;
            font-weight: 800;
            margin: 0;
        }

        /* Sub-headings inside a section: smaller, with an accent bar. */
        [data-testid="stAppViewContainer"] div[class*="st-key-lf_card_"] [data-testid="stHeadingWithActionElements"] > h3 {
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--lf-title);
            padding: 0;
            margin: 1rem 0 0.35rem;
        }

        @media (max-width: 640px) {
            div[class*="st-key-lf_card_"] { padding: 0.2rem 0.9rem 1rem; }
            div[class*="st-key-lf_subcard_"] { padding: 0.2rem 0.75rem 0.9rem; }
            [data-testid="stAppViewContainer"] [data-testid="stMain"] h1.lf-page-title { font-size: 1.5rem; }
            [data-testid="stAppViewContainer"] [data-testid="stMain"] .lf-section-head h2 { font-size: 1.15rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

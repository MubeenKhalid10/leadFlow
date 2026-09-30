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
    theme.page_header("mop", "Clean Leads", "One sentence on what this page is for.")
    ...
    theme.section_header(1, "Upload your lead file", "Add a CSV or Excel file to begin.")

Icons are Material Symbols names ("mop", "database", …), the same family Streamlit's own
widgets use, so every icon on a page shares one weight and style.
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


def icon(name, cls=""):
    """One Material Symbols icon as inline HTML, for headers and messages built with st.markdown.
    Decorative: hidden from screen readers, so the text beside it must carry the meaning."""
    extra = f" {cls}" if cls else ""
    return f'<span class="lf-icon{extra}" aria-hidden="true" translate="no">{html.escape(name)}</span>'


def page_header(icon_name, title, subtitle, show_how=False):
    """Top of every page: where you are (title) and what the page is for (one sentence).

    `show_how` adds a small "How it works" help button on the right.
    """
    text_col, help_col = st.columns([5, 1], vertical_alignment="center")
    text_col.markdown(
        f'<header class="lf-page-head"><h1 class="lf-page-title">'
        f'{icon(icon_name)}{html.escape(title)}</h1>'
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
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <rect width="28" height="28" rx="4" fill="#ffffff"/>
                    <path d="M7 10h6m-6 4h10m-10 4h8" stroke="#0c1b33" stroke-width="2" stroke-linecap="round"/>
                    <circle cx="20" cy="10" r="3" fill="#0c1b33"/>
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
    ("app.py", "Clean Leads", ":material/mop:", False, "Upload a lead file, clean it, then split and download your campaign."),
    ("pages/1_Database.py", "Lead Database", ":material/database:", True, "Your saved Master, MQL, Bounced and Unsubscribed lists."),
    ("pages/2_Manage_Users.py", "Users & Access", ":material/group:", True, "Choose who has admin access."),
]


def sidebar_nav(user=None, current="app.py"):
    """Named page links in the sidebar. Admin pages stay visible to everyone (they guard
    themselves) but are greyed out for non-admins so it's clear they need admin access.
    `current` is this page's file, so its link can be highlighted."""
    is_admin = bool(user) and user.get("role") == "admin"
    with st.sidebar:
        st.markdown('<div class="lf-sidebar-nav-label"><span class="lf-sr-only">Menu</span></div>',
                    unsafe_allow_html=True)
        for page, label, nav_icon, admin_only, tip in NAV_PAGES:
            locked = admin_only and not is_admin
            # st.page_link exposes no "current page" attribute, so wrap it in a keyed container for the CSS.
            slot = st.container(key="lf_nav_current") if page == current else st.container()
            try:
                slot.page_link(
                    page,
                    label=f"{label} (admins only)" if locked else label,
                    icon=nav_icon,
                    help="Only admins can open this page." if locked else tip,
                    disabled=locked,
                )
            except Exception as e:  # e.g. a page file missing from this deployment
                _log.warning("Sidebar link to %s unavailable: %s", page, e)


def section_header(number, title, subtitle=None, icon_name=""):
    """Section heading: an optional step number, the title, and one short line on its purpose.

    Pass a number (1, 2, …) only for real, ordered workflow steps; use None for plain sections.
    """
    badge = (f'<div class="lf-section-badge" aria-hidden="true">{html.escape(str(number))}</div>'
             if number else "")
    step = f'<span class="lf-sr-only">Step {html.escape(str(number))}: </span>' if number else ""
    # The step badge already marks a numbered step; an icon beside it would be a second marker.
    icon_html = icon(icon_name) if icon_name and not number else ""
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
        mark = icon("check") if state == "done" else str(i + 1)
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


def empty_state(icon_name, title, text=""):
    """Placeholder for a section with nothing to show: what is empty, and what to do about it."""
    st.markdown(
        f'<div class="lf-empty"><div class="lf-empty-icon">{icon(icon_name)}</div>'
        f'<div class="lf-empty-title">{title}</div>'
        + (f'<div class="lf-empty-text">{text}</div>' if text else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def status_line(kind, title, detail=""):
    """Compact one-line state message: success, warning, error, next step or info.

    `title` and `detail` are HTML; escape any user data in them before calling.
    The icon plus the words carry the meaning, so the state never depends on colour alone.
    """
    symbol = {"success": "check_circle", "warning": "warning", "error": "error",
              "next": "arrow_forward", "info": "info"}[kind]
    detail_html = f'<span class="lf-status-detail">{detail}</span>' if detail else ""
    st.markdown(
        f'<div class="lf-status lf-status-{kind}" role="status">'
        f'{icon(symbol, "lf-status-icon")}'
        f'<span class="lf-status-title">{title}</span>{detail_html}</div>',
        unsafe_allow_html=True,
    )


def note(text):
    """Amber caution beside an action with a side effect (e.g. a download that removes leads).
    `text` is HTML; escape any user data in it before calling."""
    st.markdown(f'<div class="lf-note">{icon("warning")}<span>{text}</span></div>', unsafe_allow_html=True)


def table_header(key, widths, labels):
    """Column headings, padded to line up with the rows below them (hidden on phones,
    where each cell shows its own label instead)."""
    cols = st.container(key=f"lf_rowhead_{key}").columns(widths)
    for col, label in zip(cols, labels):
        if label:
            col.markdown(f'<span class="lf-col-head">{html.escape(label)}</span>', unsafe_allow_html=True)


def table_row(key, widths):
    """One ruled table row. Returns its columns."""
    return st.container(key=f"lf_row_{key}").columns(widths, vertical_alignment="center")


def table_cell(col, label, value, strong=False, icon_name="", suffix=""):
    """Text cell of a table_row. `value` is plain text and is escaped, so file names and email
    addresses can't be read as Markdown or HTML. `label` repeats the column heading on phones,
    where the row stacks and the heading row is hidden. `suffix` is trusted HTML."""
    cls = "lf-cell lf-cell-strong" if strong else "lf-cell"
    lead = icon(icon_name) if icon_name else ""
    text = html.escape(str(value))
    col.markdown(
        f'<span class="lf-cell-label">{html.escape(label)}</span>'
        f'<span class="{cls}">{lead}{text}{suffix}</span>',
        unsafe_allow_html=True,
    )


def removal_breakdown(groups, total, start=None, final=None):
    """The results statement: rows in, every deduction with its reason and share, and rows
    out, set as one ruled column whose figures share a right edge and which closes under a
    double rule.

    groups: [(group title, [(label, short hint, count or None if the check didn't run), ...]), ...]
    total:  leads removed (the sum of the counts). start / final: rows in the file and clean
    leads left; when given they open and close the statement.
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

    def line(cls, label, hint, n):
        small = f'<small>{hint}</small>' if hint else ""
        return (f'<div class="lf-why-line {cls}"><div class="lf-why-label">{label}{small}</div>'
                f'<div class="lf-why-count">{int(n):,}</div></div>')

    sections = []
    for title, rows in groups:
        subtotal = sum(int(n) for _, _, n in rows if n)
        sections.append(
            f'<section class="lf-why-group"><div class="lf-why-group-head"><span>{title}</span>'
            f'<b>{subtotal:,}</b></div>' + "".join(row(*r) for r in rows) + "</section>"
        )
    opening = line("lf-why-open", "In your file", "rows before cleaning", start) if start is not None else ""
    closing = line("lf-why-close", "Clean leads", "in your campaign file", final) if final is not None else ""
    st.markdown(
        f'<div class="lf-why" role="group" aria-label="Why leads were removed">'
        f'<div class="lf-why-title">Why were leads removed?</div>'
        f'{opening}<div class="lf-why-groups">{"".join(sections)}</div>'
        f'{line("lf-why-total", "Total removed", "", total)}{closing}</div>',
        unsafe_allow_html=True,
    )


def card(key):
    """Bordered white box for one page section: `with theme.card("upload"): ...`.

    Just a keyed st.container; its look comes from the st-key-lf_card_ rule in inject_theme().
    Keys must be unique on a page.
    """
    return st.container(key=f"lf_card_{key}")


def subcard(key):
    """Bordered grey panel inside a card, for related controls that belong together."""
    return st.container(key=f"lf_subcard_{key}")


def friendly_error(title, message, error=None):
    """Plain-language error with a next step; the raw error goes to the log and a small caption."""
    st.error(f"**{title}**  \n{message}", icon=":material/error:")
    if error is not None:
        _log.error("%s: %s", title, error, exc_info=error if isinstance(error, BaseException) else None)
        st.caption(f"Technical details: {type(error).__name__}: {html.escape(str(error))[:500]}")


def inject_theme():
    """Inject the global CSS. Call once per page after set_page_config.

    The look: white boxes on a cool grey page, hairline borders and navy ink. Every section
    is a box whose heading sits in a pale navy band; checkboxes and tabs are boxed too.
    Flat fills only (no gradients, glows or blur), 4px corners, and colour used for
    meaning: navy for actions and the current step; green, amber and red for outcomes.
    """
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700&display=swap');

        :root {
            --lf-bg: #f2f4f6;
            --lf-surface: #ffffff;
            --lf-mist: #f2f4f6;
            --lf-border: #d5dae0;
            --lf-border-soft: #e6e9ed;
            --lf-title: #0c1b33;
            --lf-body: #36435a;
            --lf-muted: #5a6679;
            --lf-placeholder: #667286;
            --lf-input-border: #8591a3;
            --lf-primary: #12305a;
            --lf-primary-hover: #0c1b33;
            --lf-link: #1d4e89;
            --lf-primary-soft: #e9eef5;
            --lf-heading-band: #dbe5f2;
            --lf-heading-band-edge: #b7c8de;
            --lf-success: #1a6b47;
            --lf-success-soft: #e8f3ed;
            --lf-danger: #a3271f;
            --lf-danger-soft: #fbecea;
            --lf-warning: #8a6100;
            --lf-warning-soft: #fbf3dc;
            --lf-focus: 0 0 0 2px #ffffff, 0 0 0 4px #1d4e89;
            --lf-focus-on-dark: 0 0 0 2px #0c1b33, 0 0 0 4px #ffffff;
            --lf-radius: 4px;
            --lf-radius-sm: 4px;
            --lf-rail: #0c1b33;
            --lf-rail-text: #c9d3e2;
            --lf-rail-muted: #93a1b8;
            --lf-rail-rule: rgba(255, 255, 255, 0.14);
        }

        /* config.toml [theme] font gives Streamlit's own components this face; this rule covers
           the HTML this module writes. Nothing broader: a blanket font rule would also replace
           the icon font Streamlit sets on its icons. */
        html, body, .stApp, [data-testid="stMarkdownContainer"] {
            font-family: "Libre Franklin", "Segoe UI", sans-serif;
        }
        /* Dropdowns: the chosen value and the option list set their own face. */
        [data-baseweb="select"] :is(div, span, input),
        :is([data-testid="stSelectbox"], [data-testid="stMultiSelect"]) :is(input, div, span):not([data-testid="stIconMaterial"]),
        [data-baseweb="popover"] [role="option"],
        [data-baseweb="popover"] li {
            font-family: "Libre Franklin", "Segoe UI", sans-serif !important;
        }

        /* Icons (theme.icon): Material Symbols, the family Streamlit's own widgets use.
           Sized in em so an icon always matches the text it sits beside. */
        .lf-icon {
            font-family: "Material Symbols Rounded" !important;
            font-weight: 400;
            font-style: normal;
            font-size: 1.2em;
            line-height: 1;
            letter-spacing: normal;
            text-transform: none;
            white-space: nowrap;
            display: inline-block;
            vertical-align: -0.2em;
            user-select: none;
            font-feature-settings: "liga";
            -webkit-font-smoothing: antialiased;
        }

        /* Browser surfaces: selection, caret and scrollbars take the palette too. */
        ::selection { background: #cfdcee; color: var(--lf-title); }
        [data-testid="stSidebar"] ::selection { background: #ffffff; color: var(--lf-rail); }
        input, textarea { caret-color: var(--lf-link); }
        [data-testid="stMain"] { scrollbar-color: #b3bcc8 transparent; }

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

        /* Captions are secondary text, but still have to be readable (4.5:1 on white and on mist). */
        [data-testid="stMain"] [data-testid="stCaptionContainer"],
        [data-testid="stMain"] [data-testid="stCaptionContainer"] p,
        [role="dialog"] [data-testid="stCaptionContainer"] p {
            color: var(--lf-muted) !important;
            opacity: 1 !important;
        }

        /* ---------------------------------------------------------------
           PAGE
           --------------------------------------------------------------- */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {
            background: var(--lf-bg);
        }

        [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"] {
            max-width: 1140px;
            padding-top: 4.25rem;
            padding-bottom: 3.5rem;
        }

        [data-testid="stHeader"] {
            background: var(--lf-bg);
            border-bottom: 1px solid var(--lf-border);
        }

        /* ---------------------------------------------------------------
           SIDEBAR: one flat navy rail
           --------------------------------------------------------------- */
        [data-testid="stSidebar"] {
            background: var(--lf-rail) !important;
            border-right: none !important;
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

        /* Branding */
        .lf-sidebar-header {
            display: flex;
            align-items: center;
            gap: 0.7rem;
            padding: 1.4rem 1.25rem 1.1rem;
        }

        .lf-sidebar-logo { flex-shrink: 0; line-height: 0; }

        .lf-sidebar-title-text {
            display: flex;
            flex-direction: column;
        }

        .lf-sidebar-brand-name {
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            color: #ffffff !important;
            line-height: 1.2;
        }

        .lf-sidebar-brand-sub {
            font-size: 0.78rem;
            font-weight: 400;
            color: var(--lf-rail-muted) !important;
            line-height: 1.4;
        }

        /* A rule between the name and the links, inset like the account rule at the bottom. */
        [data-testid="stSidebar"] .lf-sidebar-nav-label {
            height: 0;
            margin: 0 0.75rem 0.6rem;
            border-top: 1px solid var(--lf-rail-rule);
        }

        /* Named page links (theme.sidebar_nav) */
        [data-testid="stSidebar"] [data-testid="stPageLink"] {
            padding: 0 0.75rem;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
            border-radius: var(--lf-radius) !important;
            padding: 0.55rem 0.85rem !important;
            margin-bottom: 0.15rem !important;
            background: transparent !important;
            border: none !important;
            transition: background-color 0.15s ease !important;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span,
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p,
        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] [data-testid="stMarkdownContainer"] p {
            color: var(--lf-rail-text) !important;
            font-size: 0.9rem !important;
            font-weight: 500 !important;
        }

        [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] [data-testid="stIconMaterial"] {
            color: var(--lf-rail-muted) !important;
            font-size: 1.2rem !important;
        }

        [data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {
            background: rgba(255, 255, 255, 0.07) !important;
        }

        /* Current page: a lighter fill plus heavier white text, so it never relies on colour alone. */
        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] {
            background: rgba(255, 255, 255, 0.13) !important;
        }

        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] span,
        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] p,
        [data-testid="stSidebar"] div.st-key-lf_nav_current [data-testid="stPageLink-NavLink"] [data-testid="stIconMaterial"] {
            color: #ffffff !important;
            font-weight: 700 !important;
        }

        /* Sidebar text and widgets */
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            color: var(--lf-rail-text) !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #ffffff !important;
        }

        /* Account, pinned to the bottom of the rail */
        div.st-key-lf_sidebar_user_box {
            position: absolute !important;
            left: 0.75rem !important;
            right: 0.75rem !important;
            bottom: 1rem !important;
            width: auto !important;
            max-width: none !important;
            margin: 0 !important;
            padding: 0.9rem 0 0 !important;
            border-top: 1px solid var(--lf-rail-rule);
            z-index: 1000 !important;
        }

        .lf-sidebar-user-card {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            padding: 0 0.35rem;
            margin-bottom: 0.7rem;
        }

        .lf-sidebar-user-avatar {
            flex-shrink: 0;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: #ffffff;
            color: var(--lf-rail) !important;
            font-weight: 700;
            font-size: 0.9rem;
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
            font-weight: 600;
            color: #ffffff !important;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .lf-sidebar-user-role {
            font-size: 0.78rem;
            font-weight: 400;
            color: var(--lf-rail-muted) !important;
        }

        [data-testid="stSidebar"] .stButton button[data-testid^="stBaseButton"] {
            width: 100% !important;
            min-height: 2.35rem !important;
            border-radius: var(--lf-radius) !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
            background: transparent !important;
            color: #ffffff !important;
            border: 1px solid rgba(255, 255, 255, 0.32) !important;
            box-shadow: none !important;
            transition: background-color 0.15s ease, border-color 0.15s ease !important;
        }

        [data-testid="stSidebar"] .stButton button[data-testid^="stBaseButton"]:hover {
            background: rgba(255, 255, 255, 0.1) !important;
            border-color: rgba(255, 255, 255, 0.6) !important;
        }

        [data-testid="stSidebar"] { scrollbar-color: rgba(255, 255, 255, 0.25) transparent; }

        /* Sidebar toggle: the collapse arrow inside the rail and the expand arrow on the page. */
        [data-testid="stSidebarCollapseButton"] button,
        button[data-testid="stExpandSidebarButton"] {
            width: 2.25rem !important;
            height: 2.25rem !important;
            min-width: 2.25rem !important;
            padding: 0 !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            border-radius: var(--lf-radius) !important;
            opacity: 1 !important;
            transition: background-color 0.15s ease !important;
        }

        [data-testid="stSidebarCollapseButton"] button {
            background: transparent !important;
            border: 1px solid transparent !important;
        }
        [data-testid="stSidebarCollapseButton"] button:hover {
            background: rgba(255, 255, 255, 0.1) !important;
        }
        [data-testid="stSidebarCollapseButton"] button span,
        [data-testid="stSidebarCollapseButton"] button svg {
            color: #ffffff !important;
            fill: #ffffff !important;
        }

        button[data-testid="stExpandSidebarButton"] {
            background: #ffffff !important;
            border: 1px solid var(--lf-input-border) !important;
        }
        button[data-testid="stExpandSidebarButton"]:hover {
            background: var(--lf-mist) !important;
            border-color: var(--lf-title) !important;
        }
        button[data-testid="stExpandSidebarButton"] span,
        button[data-testid="stExpandSidebarButton"] svg {
            color: var(--lf-title) !important;
            fill: var(--lf-title) !important;
        }

        /* ---------------------------------------------------------------
           PAGE HEADER (theme.page_header): where am I, what is this page for
           --------------------------------------------------------------- */
        .lf-page-head {
            padding: 0.1rem 0 1.1rem;
        }

        [data-testid="stAppViewContainer"] [data-testid="stMain"] h1.lf-page-title {
            margin: 0;
            padding: 0;
            color: var(--lf-title);
            font-size: 1.75rem;
            font-weight: 600;
            letter-spacing: -0.015em;
            line-height: 1.2;
        }

        .lf-page-title .lf-icon {
            color: var(--lf-muted);
            margin-right: 0.5rem;
            font-size: 1.1em;
        }

        /* Streamlit adds a "link to heading" icon to every heading; these are app titles, not doc anchors. */
        .lf-page-head [data-testid="stHeaderActionElements"],
        .lf-section-head [data-testid="stHeaderActionElements"] {
            display: none !important;
        }

        [data-testid="stAppViewContainer"] [data-testid="stMain"] p.lf-page-sub {
            margin: 0.35rem 0 0;
            color: var(--lf-body);
            font-size: 0.98rem;
            font-weight: 400;
            max-width: 85ch;
            text-wrap: pretty;
        }

        /* ---------------------------------------------------------------
           SECTIONS (theme.card / theme.subcard / theme.section_header)
           Each section is a white box on the grey page, and its heading sits
           in a pale navy band across the top of the box. Related controls inside
           a section share a grey panel with its own border.
           --------------------------------------------------------------- */
        div[class*="st-key-lf_card_"] {
            --lf-card-pad: 1.5rem;
            background: var(--lf-surface);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            padding: 0 var(--lf-card-pad) 1.5rem;
            margin-bottom: 1rem;
            overflow: hidden;
        }

        div[class*="st-key-lf_subcard_"] {
            --lf-card-pad: 1.2rem;
            background: var(--lf-mist);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            padding: 0 var(--lf-card-pad) 1.1rem;
            overflow: hidden;
        }

        /* The heading band: bleeds to the edges of its box. */
        .lf-section-head {
            display: flex;
            align-items: flex-start;
            gap: 0.7rem;
            margin: 0 calc(var(--lf-card-pad, 0rem) * -1) 1rem;
            padding: 0.85rem var(--lf-card-pad, 0rem);
            /* Pale navy, not grey: the page and the panels inside a section are grey, so a
               heading band in the action colour's own hue is what marks it as a heading. */
            background: var(--lf-heading-band);
            border-bottom: 1px solid var(--lf-heading-band-edge);
        }
        .lf-section-head .lf-section-sub { color: var(--lf-title); }

        /* Step number: only on real, ordered workflow steps. */
        .lf-section-badge {
            flex-shrink: 0;
            width: 26px;
            height: 26px;
            margin-top: 0.05rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.82rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
            color: #ffffff;
            background: var(--lf-primary);
        }

        [data-testid="stAppViewContainer"] [data-testid="stMain"] .lf-section-head h2 {
            margin: 0;
            padding: 0 !important;
            color: var(--lf-title);
            font-size: 1.2rem;
            line-height: 1.3;
            letter-spacing: -0.01em;
            font-weight: 600;
            text-wrap: balance;
        }

        .lf-section-head h2 .lf-icon {
            color: var(--lf-primary);
            margin-right: 0.45rem;
        }

        .lf-section-sub {
            color: var(--lf-body);
            font-size: 0.93rem;
            font-weight: 400;
            margin-top: 0.2rem;
            line-height: 1.45;
            max-width: 95ch;
        }

        /* Sub-headings inside a section. */
        [data-testid="stAppViewContainer"] div[class*="st-key-lf_card_"] [data-testid="stHeadingWithActionElements"] > h3 {
            font-size: 1.02rem;
            font-weight: 600;
            color: var(--lf-title);
            padding: 0;
            margin: 1rem 0 0.35rem;
        }

        /* Heading above a group of related controls: a grey strip with a border, so the
           group reads as its own block inside the section. */
        .lf-group-label {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--lf-title);
            margin: 1.1rem 0 0.6rem;
            padding: 0.45rem 0.75rem;
            background: var(--lf-mist);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
        }
        div[class*="st-key-lf_subcard_"] .lf-group-label { background: #e6e9ed; }

        .lf-sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip: rect(0 0 0 0);
            white-space: nowrap;
        }

        /* ---------------------------------------------------------------
           STATUS LINES (theme.status_line): done, check, failed, next, info
           --------------------------------------------------------------- */
        .lf-status {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 0.25rem 0.6rem;
            padding: 0.55rem 0.85rem;
            margin: 0.4rem 0 0.6rem;
            border-radius: var(--lf-radius);
            border: 1px solid;
            font-size: 0.93rem;
        }
        .lf-status-icon { align-self: center; font-size: 1.25em; }
        .lf-status-title { font-weight: 600; }
        .lf-status-detail { color: var(--lf-body); }
        .lf-status-success { background: var(--lf-success-soft); border-color: #b5d6c4; color: #12492f; }
        .lf-status-warning { background: var(--lf-warning-soft); border-color: #e2c878; color: #5c4003; }
        .lf-status-error   { background: var(--lf-danger-soft); border-color: #e5b5b0; color: #7d1d17; }
        /* Next step and plain information are not outcomes: text only, no tint or box. */
        .lf-status-next,
        .lf-status-info    { background: none; border-color: transparent; padding-left: 0; padding-right: 0; color: var(--lf-title); }

        /* Caution beside an action with a side effect (theme.note). */
        .lf-note {
            display: flex;
            gap: 0.5rem;
            align-items: flex-start;
            padding: 0.55rem 0.85rem;
            margin: 0.35rem 0 0.6rem;
            border-radius: var(--lf-radius);
            background: var(--lf-warning-soft);
            border: 1px solid #e2c878;
            color: #5c4003;
            font-size: 0.87rem;
            font-weight: 500;
        }
        .lf-note .lf-icon { flex-shrink: 0; font-size: 1.15rem; color: var(--lf-warning); vertical-align: 0; }

        /* Legend (e.g. what "Location Empty" means). */
        .lf-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem 0.9rem;
            margin: 0.1rem 0 0.7rem;
            font-size: 0.85rem;
            color: var(--lf-body);
        }
        .lf-legend b { color: var(--lf-title); font-weight: 600; }

        /* ---------------------------------------------------------------
           THE STATEMENT (theme.removal_breakdown): "Why were leads removed?"
           Set like a reconciliation: ruled lines, figures on one right edge,
           and a total that closes under a double rule.
           --------------------------------------------------------------- */
        .lf-why {
            margin: 1.4rem 0 1.2rem;
            padding: 0;
        }
        .lf-why-title {
            font-weight: 600;
            font-size: 1.02rem;
            color: var(--lf-title);
            margin-bottom: 0.8rem;
        }
        /* The two groups of reasons sit side by side, each in its own box. */
        .lf-why-groups {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr));
            gap: 1rem;
            margin-top: 1rem;
            align-items: start;
        }
        .lf-why-group {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            background: var(--lf-surface);
            overflow: hidden;
        }
        .lf-why-group .lf-why-row { padding-left: 0.9rem; padding-right: 0.9rem; }
        .lf-why-group .lf-why-row:last-child { border-bottom: none; }
        /* Opening, subtotal and closing lines: label left, figure on the shared right edge. */
        .lf-why-line {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 1rem;
            color: var(--lf-title);
        }
        .lf-why-line .lf-why-label { font-weight: 600; font-size: 0.95rem; }
        /* Opening, total and closing lines take the same side inset as the boxed rows. */
        .lf-why-line { padding-left: 0.9rem !important; padding-right: 0.9rem !important; }
        .lf-why-open {
            padding: 0.6rem 0;
            background: var(--lf-mist);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
        }
        .lf-why-close {
            margin-top: 0.1rem;
            padding: 0.7rem 0 0.2rem;
            border-top: 6px double var(--lf-title);
        }
        .lf-why-close .lf-why-label { font-size: 1.02rem; font-weight: 700; }
        .lf-why-close .lf-why-count { font-size: 1.35rem; font-weight: 700; line-height: 1.1; }
        .lf-why-group-head {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 0.6rem 0.9rem;
            background: var(--lf-mist);
            border-bottom: 1px solid var(--lf-border);
            font-size: 0.74rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: var(--lf-muted);
        }
        .lf-why-group-head b {
            font-size: 0.95rem;
            font-weight: 600;
            letter-spacing: 0;
            color: var(--lf-title);
            font-variant-numeric: tabular-nums;
        }
        .lf-why-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 70px 5.75rem;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--lf-border-soft);
        }
        .lf-why-label {
            font-weight: 500;
            font-size: 0.92rem;
            color: var(--lf-title);
            line-height: 1.3;
        }
        .lf-why-label small {
            display: block;
            font-weight: 400;
            font-size: 0.78rem;
            color: var(--lf-muted);
        }
        .lf-why-bar {
            height: 4px;
            background: var(--lf-border-soft);
            overflow: hidden;
        }
        .lf-why-bar span {
            display: block;
            height: 100%;
            background: var(--lf-primary);
        }
        .lf-why-count {
            text-align: right;
            font-weight: 600;
            font-size: 0.95rem;
            color: var(--lf-title);
            font-variant-numeric: tabular-nums;
        }
        .lf-why-row.lf-zero .lf-why-label,
        .lf-why-row.lf-zero .lf-why-count { color: var(--lf-muted); font-weight: 400; }
        .lf-why-row.lf-off .lf-why-label { color: var(--lf-muted); font-weight: 400; }
        .lf-why-row.lf-off .lf-why-bar { background: none; }
        .lf-why-row.lf-off .lf-why-count {
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--lf-muted);
        }
        .lf-why-total {
            margin-top: 1.1rem;
            padding: 0.6rem 0 0.7rem;
            border-top: 1px solid var(--lf-title);
        }

        /* ---------------------------------------------------------------
           EXPANDERS / TABLE ROWS
           --------------------------------------------------------------- */
        [data-testid="stExpander"] {
            border: 1px solid var(--lf-border) !important;
            border-radius: var(--lf-radius) !important;
            background: var(--lf-surface) !important;
            margin-bottom: 0.75rem;
            overflow: hidden;
        }

        /* One edge only: Streamlit draws a second, rounder border on the inner <details>. */
        [data-testid="stExpander"] details {
            border: none !important;
            border-radius: 0 !important;
        }

        [data-testid="stExpander"] summary {
            font-weight: 500 !important;
            color: var(--lf-title) !important;
            padding: 0.65rem 0.9rem !important;
        }

        [data-testid="stExpander"] summary:hover {
            color: var(--lf-title) !important;
            background: var(--lf-mist);
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: var(--lf-radius) !important;
        }

        /* Table rows built from columns (theme.table_row): ruled lines under a heading row. */
        div[class*="st-key-lf_row_"] {
            border-bottom: 1px solid var(--lf-border-soft);
            padding: 0.55rem 0.5rem;
            transition: background-color 0.15s ease;
        }
        div[class*="st-key-lf_row_"]:hover {
            background: var(--lf-mist);
        }
        div[class*="st-key-lf_rowhead_"] {
            padding: 0 0.5rem 0.15rem;
            border-bottom: 1px solid var(--lf-title);
        }
        .lf-col-head {
            font-size: 0.74rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: var(--lf-muted);
        }
        .lf-cell {
            color: var(--lf-body);
            font-size: 0.93rem;
            font-variant-numeric: tabular-nums;
            overflow-wrap: anywhere;
        }
        .lf-cell-strong { color: var(--lf-title); font-weight: 600; }
        /* Streamlit turns email addresses into mailto links; in a table they read as plain values. */
        .lf-cell a { color: inherit !important; text-decoration: none !important; }
        .lf-cell a:hover { text-decoration: underline !important; text-underline-offset: 0.18em; }
        .lf-cell .lf-icon { color: var(--lf-muted); margin-right: 0.3rem; }
        /* Shown only on phones, where rows stack and the heading row is hidden. */
        .lf-cell-label { display: none; }
        .lf-you {
            display: inline-block;
            margin-left: 0.45rem;
            padding: 0.05rem 0.4rem;
            border-radius: 2px;
            background: var(--lf-primary-soft);
            color: var(--lf-primary);
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            vertical-align: 0.08em;
        }

        /* ---------------------------------------------------------------
           FILE UPLOADERS
           --------------------------------------------------------------- */
        [data-testid="stFileUploaderDropzone"] {
            border: 1px dashed #8591a3;
            border-radius: var(--lf-radius);
            background: var(--lf-mist);
            padding: 1.4rem 1.2rem;
            transition: border-color 0.15s ease, background-color 0.15s ease;
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
            border-radius: var(--lf-radius) !important;
            font-weight: 600 !important;
        }
        [data-testid="stMain"] [data-testid="stFileUploader"] button[data-testid="stBaseButton-secondary"] * {
            color: #ffffff !important;
        }
        [data-testid="stMain"] [data-testid="stFileUploader"] button[data-testid="stBaseButton-secondary"]:hover {
            background: var(--lf-primary-hover) !important;
        }

        /* Remove-file button next to an uploaded file: an outlined close icon that turns red on hover. */
        [data-testid="stFileUploader"] button[aria-label*="Remove"],
        [data-testid="stFileUploader"] button[title*="Remove"] {
            position: relative !important;
            min-width: 25px !important;
            width: 25px !important;
            height: 25px !important;
            min-height: 25px !important;
            padding: 0 !important;
            background: #ffffff !important;
            border: 1px solid var(--lf-input-border) !important;
            border-radius: var(--lf-radius) !important;
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
            content: "close";
            font-family: "Material Symbols Rounded" !important;
            color: var(--lf-title) !important;
            font-size: 18px !important;
            font-weight: 600 !important;
            line-height: 1 !important;
            position: absolute !important;
            top: 50% !important;
            left: 50% !important;
            transform: translate(-50%, -50%) !important;
            pointer-events: none !important;
        }

        [data-testid="stFileUploader"] button[aria-label*="Remove"]:hover,
        [data-testid="stFileUploader"] button[title*="Remove"]:hover {
            background: var(--lf-danger) !important;
            border-color: var(--lf-danger) !important;
        }
        [data-testid="stFileUploader"] button[aria-label*="Remove"]:hover::after,
        [data-testid="stFileUploader"] button[title*="Remove"]:hover::after {
            color: #ffffff !important;
        }

        /* ---------------------------------------------------------------
           ALERTS / METRICS / TABLES
           --------------------------------------------------------------- */
        [data-testid="stAlert"] {
            border-radius: var(--lf-radius);
        }

        /* Figures: a label and a value in a grey box, near body size. */
        [data-testid="stMetric"] {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            background: var(--lf-mist);
            padding: 0.6rem 0.9rem 0.5rem;
        }

        [data-testid="stMetricLabel"] {
            color: var(--lf-muted) !important;
            font-weight: 500 !important;
            font-size: 0.82rem !important;
        }

        [data-testid="stMetricValue"] {
            color: var(--lf-title) !important;
            font-weight: 600 !important;
            font-size: 1.25rem !important;
            line-height: 1.35 !important;
            font-variant-numeric: tabular-nums;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            overflow: hidden;
            font-variant-numeric: tabular-nums;
        }

        /* ---------------------------------------------------------------
           BUTTONS: one hierarchy everywhere.
             primary   filled navy   the one main action of a section
             secondary white+border  other useful actions
             tertiary  text link     help / minor actions
           Colour means something, so there is only one exception: a button
           whose key starts with del_ (delete, undo) is red.
           --------------------------------------------------------------- */
        [class*="st-key-del_"] { --lf-btn-a: #a3271f; --lf-btn-hover: #86201a; --lf-btn-soft: #fbecea; }

        :is([data-testid="stMain"], [role="dialog"])
            :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"]) button {
            border-radius: var(--lf-radius) !important;
            font-weight: 600 !important;
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
            box-shadow: none !important;
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
            background: var(--lf-btn-soft, var(--lf-mist)) !important;
            color: var(--lf-btn-hover, var(--lf-title)) !important;
            border-color: var(--lf-btn-hover, var(--lf-title)) !important;
        }

        /* Tertiary: text link style */
        :is([data-testid="stMain"], [role="dialog"]) button[kind="tertiary"] {
            color: var(--lf-link) !important;
            min-height: 2.25rem;
            font-weight: 600 !important;
        }
        :is([data-testid="stMain"], [role="dialog"]) button[kind="tertiary"]:hover {
            color: var(--lf-primary-hover) !important;
            text-decoration: underline;
            text-underline-offset: 0.18em;
        }

        /* Labels take the button's own text colour. Without this, the page-wide
           text rules (main area and sidebar) recolour the <p> inside each button. */
        :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"])
            button[data-testid^="stBaseButton"] * {
            color: inherit !important;
        }

        /* Disabled: plainly grey but still readable. */
        [data-testid="stMain"] .stElementContainer :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"])
            button[data-testid^="stBaseButton"]:disabled,
        [role="dialog"] .stElementContainer :is(.stButton, [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"])
            button[data-testid^="stBaseButton"]:disabled {
            background: var(--lf-border-soft) !important;
            color: var(--lf-muted) !important;
            border: 1px solid var(--lf-border) !important;
            box-shadow: none !important;
            opacity: 1 !important;
            cursor: not-allowed !important;
        }

        /* Visible keyboard focus on every interactive control: a solid two-tone ring that
           holds 3:1 against the page, tinted panels and filled buttons alike. */
        button:focus-visible,
        a:focus-visible,
        summary:focus-visible,
        [role="tab"]:focus-visible,
        [data-testid="stFileUploaderDropzone"]:focus-within {
            outline: none !important;
            box-shadow: var(--lf-focus) !important;
        }
        [data-testid="stCheckbox"] label:has(input:focus-visible) span[data-baseweb="checkbox"] > div:first-child,
        [data-testid="stCheckbox"] label:has(input:focus-visible) > span:first-child,
        div[data-baseweb="radio"]:has(input:focus-visible) > div:first-child {
            box-shadow: var(--lf-focus) !important;
        }
        [data-testid="stSidebar"] button:focus-visible,
        [data-testid="stSidebar"] a:focus-visible {
            box-shadow: var(--lf-focus-on-dark) !important;
        }

        /* ---------------------------------------------------------------
           TABS: each tab is a box; the selected one is filled navy with
           white, heavier text, so it never depends on colour alone.
           --------------------------------------------------------------- */
        [data-testid="stTabs"] [role="tablist"] {
            gap: 0.5rem;
            border-bottom: 1px solid var(--lf-border);
            flex-wrap: wrap;
            padding-bottom: 0.75rem;
            margin-bottom: 0.6rem;
        }

        /* Streamlit's own sliding highlight and track; the rule and underline above replace them. */
        [data-testid="stTabs"] [data-baseweb="tab-highlight"],
        [data-testid="stTabs"] [data-baseweb="tab-border"],
        [data-testid="stTabs"] [role="tablist"]::after {
            display: none !important;
        }

        [data-testid="stTabs"] [role="tab"] {
            border: 1px solid var(--lf-input-border);
            border-radius: var(--lf-radius);
            background: var(--lf-surface);
            padding: 0.5rem 1rem;
            font-weight: 600;
            font-size: 0.92rem;
            color: var(--lf-body);
            transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease;
        }

        [data-testid="stTabs"] [role="tab"] * { color: inherit !important; }

        [data-testid="stTabs"] [role="tab"]:hover {
            color: var(--lf-title);
            background: var(--lf-mist);
            border-color: var(--lf-title);
        }

        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            color: #ffffff !important;
            font-weight: 700;
            background: var(--lf-primary);
            border-color: var(--lf-primary);
        }

        [data-testid="stTabs"] [role="tab"]:focus-visible {
            box-shadow: var(--lf-focus) !important;
        }

        /* ---------------------------------------------------------------
           FORM CONTROLS: visible borders so every input looks like an input
           --------------------------------------------------------------- */
        :is([data-testid="stMain"], [role="dialog"]) [data-testid="stWidgetLabel"] p {
            font-weight: 600 !important;
            color: var(--lf-title) !important;
        }

        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label {
            font-weight: 500 !important;
            color: var(--lf-body) !important;
        }

        [data-testid="stRadio"] > div {
            gap: 0.6rem;
        }

        /* Every checkbox sits in its own box: grey on a white section, white on a grey panel.
           A ticked box takes a navy border and a pale navy fill as well as its tick. */
        [data-testid="stMain"] [data-testid="stElementContainer"]:has(> [data-testid="stCheckbox"]) {
            width: 100% !important;
        }
        [data-testid="stMain"] [data-testid="stCheckbox"] {
            width: 100%;
            padding: 0.55rem 0.75rem;
            background: var(--lf-mist);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            transition: background-color 0.15s ease, border-color 0.15s ease;
        }
        [data-testid="stMain"] div[class*="st-key-lf_subcard_"] [data-testid="stCheckbox"] {
            background: var(--lf-surface);
        }
        [data-testid="stMain"] [data-testid="stCheckbox"]:has(input:checked) {
            background: var(--lf-primary-soft);
            border-color: var(--lf-primary);
        }
        [data-testid="stMain"] [data-testid="stCheckbox"]:has(input:disabled) {
            background: var(--lf-border-soft);
            border-style: dashed;
        }

        /* Long checkbox labels wrap; a clipped "Master leads (no lists…" hides the state. */
        [data-testid="stCheckbox"] label [data-testid="stMarkdownContainer"],
        [data-testid="stCheckbox"] label [data-testid="stMarkdownContainer"] p {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
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
           Streamlit draws these borders in its secondary background colour, which is too faint
           to read as a field edge. */
        :is([data-testid="stMain"], [role="dialog"]) :is(
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stNumberInputContainer"],
            [data-testid="stSelectbox"] > div > div[role="group"],
            [data-testid="stMultiSelect"] > div > div[role="group"]
        ) {
            border: 1px solid var(--lf-input-border) !important;
            border-radius: var(--lf-radius) !important;
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
            border-color: var(--lf-title) !important;
        }

        :is([data-testid="stMain"], [role="dialog"]) :is(
            [data-testid="stTextInputRootElement"],
            [data-testid="stTextAreaRootElement"],
            [data-testid="stNumberInputContainer"],
            [data-testid="stSelectbox"] > div > div[role="group"],
            [data-testid="stMultiSelect"] > div > div[role="group"]
        ):focus-within {
            border-color: var(--lf-link) !important;
            box-shadow: var(--lf-focus) !important;
        }

        [data-testid="stMain"] input::placeholder,
        [data-testid="stMain"] textarea::placeholder {
            color: var(--lf-placeholder) !important;
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
            background: rgba(255, 255, 255, 0.5);
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
            width: 36px;
            height: 36px;
            border: 3px solid var(--lf-border);
            border-top: 3px solid var(--lf-primary);
            border-radius: 50%;
            z-index: 999999;
            animation: lf-overlay-in 0.2s ease 0.4s both,
                       global-spinner-spin 0.75s linear infinite;
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
            padding: 0.6rem 0.9rem;
            background: var(--lf-mist);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            margin: 0.5rem 0;
            font-weight: 500;
            color: var(--lf-title);
        }

        /* ---------------------------------------------------------------
           DIVIDERS
           --------------------------------------------------------------- */
        [data-testid="stDivider"] hr {
            border-color: var(--lf-border-soft);
            border-width: 1px 0 0;
            margin: 1.5rem 0;
        }

        /* ---------------------------------------------------------------
           WORKFLOW STEPPER: four steps on one ruled line
           --------------------------------------------------------------- */
        .lf-stepper {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.85rem 1.25rem;
            margin: 0 0 1rem;
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
            width: 26px;
            height: 26px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 0.8rem;
            font-variant-numeric: tabular-nums;
            border: 1px solid var(--lf-input-border);
            color: var(--lf-muted);
            background: #ffffff;
            transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
        }

        .lf-step-dot .lf-icon { font-size: 1.05rem; vertical-align: 0; font-weight: 600; }

        /* Done: outlined with a tick. Current: filled. The shape differs as well as the tone. */
        .lf-step.done .lf-step-dot {
            background: #ffffff;
            border-color: var(--lf-primary);
            color: var(--lf-primary);
        }

        .lf-step.active .lf-step-dot {
            background: var(--lf-primary);
            border-color: var(--lf-primary);
            color: #ffffff;
        }

        .lf-step-text {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        .lf-step-label {
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--lf-title);
        }

        .lf-step.active .lf-step-label { font-weight: 700; }
        .lf-step.todo .lf-step-label { color: var(--lf-muted); font-weight: 500; }

        .lf-step-hint {
            font-size: 0.76rem;
            color: var(--lf-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .lf-step-line {
            flex: 1;
            height: 1px;
            min-width: 1rem;
            background: var(--lf-border);
            transition: background-color 0.2s ease;
        }

        .lf-step-line.done { background: var(--lf-primary); }

        /* ---------------------------------------------------------------
           EMPTY STATES
           --------------------------------------------------------------- */
        .lf-empty {
            text-align: center;
            padding: 1.6rem 1.2rem;
            margin: 0.5rem 0 1rem;
            border: 1px dashed #b3bcc8;
            border-radius: var(--lf-radius);
            background: var(--lf-mist);
        }

        .lf-empty-icon { font-size: 1.6rem; line-height: 1; margin-bottom: 0.45rem; color: var(--lf-muted); }
        .lf-empty-icon .lf-icon { vertical-align: 0; }

        .lf-empty-title {
            font-weight: 600;
            font-size: 1rem;
            color: var(--lf-title);
        }

        .lf-empty-text {
            color: var(--lf-body);
            font-size: 0.9rem;
            margin-top: 0.25rem;
            text-wrap: pretty;
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
            .lf-stepper { gap: 0.4rem; }
        }

        @media (max-width: 640px) {
            /* Table rows stack on phones: drop the heading row and label each value instead. */
            div[class*="st-key-lf_rowhead_"] { display: none; }
            div[class*="st-key-lf_row_"] { padding: 0.75rem 0.25rem; }
            div[class*="st-key-lf_row_"] [data-testid="stHorizontalBlock"] { gap: 0.45rem; }
            .lf-cell-label {
                display: block;
                font-size: 0.7rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.07em;
                color: var(--lf-muted);
            }
            /* Statement rows: the share bar goes, the label and figure keep the width. */
            .lf-why-row { grid-template-columns: minmax(0, 1fr) auto; }
            .lf-why-bar { display: none; }
            div[class*="st-key-lf_card_"] { --lf-card-pad: 0.9rem; padding-bottom: 1rem; }
            div[class*="st-key-lf_subcard_"] { --lf-card-pad: 0.8rem; padding-bottom: 0.9rem; }
            .lf-stepper { padding: 0.7rem 0.8rem; }
            [data-testid="stAppViewContainer"] [data-testid="stMain"] h1.lf-page-title { font-size: 1.45rem; }
            [data-testid="stAppViewContainer"] [data-testid="stMain"] .lf-section-head h2 { font-size: 1.1rem; }
            /* Tabs stay on one line and scroll sideways rather than wrapping under the rule. */
            [data-testid="stTabs"] [role="tablist"] {
                gap: 1.25rem;
                flex-wrap: nowrap;
                overflow-x: auto;
                scrollbar-width: none;
            }
            [data-testid="stTabs"] [role="tab"] { flex-shrink: 0; }
            /* A control in a stacked table row shows its own label, since the heading row is hidden. */
            div[class*="st-key-lf_row_"] [data-testid="stWidgetLabel"] {
                display: flex !important;
                visibility: visible !important;
                height: auto !important;
                min-height: 0 !important;
                margin-bottom: 0.15rem;
            }
            div[class*="st-key-lf_row_"] [data-testid="stWidgetLabel"] p {
                font-size: 0.7rem !important;
                font-weight: 600 !important;
                text-transform: uppercase;
                letter-spacing: 0.07em;
                color: var(--lf-muted) !important;
            }
        }

        @media (max-width: 560px) {
            /* Only the current step keeps its label on phones; the rest show just their marker. */
            .lf-step:not(.active) .lf-step-text { display: none; }
            .lf-step-label { font-size: 0.85rem; white-space: nowrap; }
            .lf-step-line { min-width: 0.4rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

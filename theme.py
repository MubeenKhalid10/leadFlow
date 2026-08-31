"""
LeadFlow — shared UI theme
--------------------------

The visual layer (fonts, colours, section headers, top bar, sidebar branding,
and the "How it works" dialog) lives here so every page — the main cleaning
page and the Manage Suppression Database page — looks identical.

Usage on each page (after st.set_page_config):
    import theme
    theme.inject_theme()
    theme.inject_sidebar_title()
    theme.render_topbar()
    ...
    theme.section_header("01-Upload the Files", "Upload")
"""

import streamlit as st


SECTION_ICONS = {
    "Upload": "📤",
    "Review Data": "🔍",
    "Configure": "⚙️",
    "Run Processing": "▶️",
    "Review Results": "📊",
    "Download": "⬇️",
    "Save to Master": "💾",
    "Manage Lists": "🗄️",
    "Import": "📥",
    "Database": "🗃️",
}


@st.dialog("How LeadFlow works")
def show_how_it_works():
    st.markdown(
        """
        ### Clean your lead data in 5 steps

        **1. Upload your raw file**
        Upload the raw lead file you want cleaned.

        **2. Review your data**
        Preview the uploaded data and confirm the detected column mapping.

        **3. Choose suppression lists**
        Pick which Master and Bounce lists (stored in your database) to
        suppress against. Manage those lists on the
        **🗄️ Manage Suppression Database** page.

        **4. Run the cleaning pipeline**
        LeadFlow removes blank emails, filters Indian contacts, separates
        special-character records, removes duplicate emails, and applies
        Master/Bounce suppression from the database.

        **5. Export & update**
        Download the campaign-ready file, then optionally save the cleaned
        contacts back into a Master list for next time.
        """
    )


def render_topbar(show_how: bool = True):
    """Brand + tagline, with an optional 'How it works' button."""
    top_left, top_how = st.columns([9, 2])

    with top_left:
        st.markdown(
            """
            <div class="lf-brand-wrap">
                <div class="lf-brand">LeadFlow</div>
                <div class="lf-tagline">
                    Turn messy lead data into clean, campaign-ready contacts.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_how:
        if show_how and st.button(
            "How it works",
            key="how_it_works_btn",
            use_container_width=True,
        ):
            show_how_it_works()


def inject_sidebar_title():
    """Inject the LeadFlow branding title into the sidebar top."""
    st.sidebar.markdown(
        """
        <div class="lf-sidebar-header">
            <div class="lf-sidebar-logo">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect width="28" height="28" rx="8" fill="url(#sidebar_logo_grad)"/>
                    <path d="M7 10h6m-6 4h10m-10 4h8" stroke="white" stroke-width="2" stroke-linecap="round"/>
                    <circle cx="20" cy="10" r="3" fill="white" fill-opacity="0.9"/>
                    <defs>
                        <linearGradient id="sidebar_logo_grad" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
                            <stop stop-color="#6366f1"/>
                            <stop offset="1" stop-color="#4f46e5"/>
                        </linearGradient>
                    </defs>
                </svg>
            </div>
            <div class="lf-sidebar-title-text">
                <span class="lf-sidebar-brand-name">LeadFlow</span>
                <span class="lf-sidebar-brand-sub">Data Cleaner</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(number, title):
    """Renders a numbered section badge + kicker + heading."""
    icon = SECTION_ICONS.get(title, "")
    step_no = number.split("-", 1)[0].strip()
    kicker = number.split("-", 1)[1].strip() if "-" in number else title
    st.markdown(
        f"""
        <div class="lf-section-head">
            <div class="lf-section-badge">{step_no}</div>
            <div class="lf-section-text">
                <div class="lf-section-kicker">{kicker}</div>
                <h2>{icon}&nbsp;{title}</h2>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
            --lf-muted: #7f869b;
            --lf-primary: #4f46e5;
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
            --lf-shadow-primary: 0 8px 24px rgba(79, 70, 229, 0.28);
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
           MAIN BACKGROUND
           --------------------------------------------------------------- */
        .stApp {
            background:
                radial-gradient(ellipse 900px 350px at 75% -5%, rgba(99, 102, 241, 0.08) 0%, transparent 70%),
                radial-gradient(ellipse 600px 300px at 10% 80%, rgba(79, 70, 229, 0.05) 0%, transparent 60%),
                linear-gradient(180deg, #fafbff 0%, var(--lf-bg) 40%, #f4f5fb 100%);
        }

        [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"] {
            max-width: 1140px;
            padding-top: 5.25rem;
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
            background: linear-gradient(135deg, #a5b4fc 0%, #818cf8 50%, #6366f1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
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
            transform: translateX(2px) !important;
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

        [data-testid="stSidebar"] .stButton > button {
            background: rgba(99, 102, 241, 0.12) !important;
            color: #a5b4fc !important;
            border: 1px solid rgba(99, 102, 241, 0.25) !important;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
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

        div.st-key-lf_sidebar_user_box .stButton > button {
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

        div.st-key-lf_sidebar_user_box .stButton > button:hover {
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

        /* ---------------------------------------------------------------
           TOP BAR
           --------------------------------------------------------------- */
        .lf-topbar {
            padding: 0.2rem 0 1.1rem;
            border-bottom: 1px solid #e7eaf4;
            margin-bottom: 1.25rem;
        }

        .lf-brand-wrap {
            display: flex;
            align-items: baseline;
            gap: 0.75rem;
            flex-wrap: wrap;
        }

        .lf-brand {
            font-size: 2.75rem;
            font-weight: 800;
            letter-spacing: -0.04em;
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .lf-tagline {
            color: var(--lf-muted);
            font-size: 0.95rem;
            font-weight: 500;
        }

        /* ---------------------------------------------------------------
           SECTION HEADERS
           --------------------------------------------------------------- */
        .lf-section-head {
            margin-top: 2.4rem;
            margin-bottom: 1.1rem;
            display: flex;
            align-items: center;
            gap: 1rem;
            padding-bottom: 0.85rem;
            border-bottom: 1px solid #e9ecf6;
        }

        .lf-section-badge {
            flex-shrink: 0;
            width: 46px;
            height: 46px;
            border-radius: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            font-weight: 800;
            color: #ffffff;
            background: linear-gradient(135deg, var(--lf-primary) 0%, var(--lf-primary-2) 100%);
            box-shadow: 0 6px 18px rgba(79, 70, 229, 0.30);
            position: relative;
            overflow: hidden;
        }

        .lf-section-badge::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 40%;
            background: linear-gradient(180deg, rgba(255,255,255,0.25) 0%, transparent 100%);
            border-radius: 13px 13px 0 0;
        }

        .lf-section-kicker {
            text-transform: uppercase;
            letter-spacing: 0.09em;
            font-size: 0.7rem;
            font-weight: 700;
            color: var(--lf-primary-2);
            margin-bottom: 0.15rem;
            opacity: 0.75;
        }

        .lf-section-head h2 {
            margin: 0;
            color: var(--lf-title);
            font-size: 1.55rem;
            line-height: 1.2;
            letter-spacing: -0.015em;
            font-weight: 800;
        }

        /* ---------------------------------------------------------------
           CARDS / PANELS / EXPANDERS
           --------------------------------------------------------------- */
        .lf-inline-panel {
            border: 1px solid #dfe4f2;
            border-radius: 12px;
            background: linear-gradient(135deg, #fbfcff 0%, #f7f8fe 100%);
            padding: 0.9rem 1.1rem;
            color: #2f3550;
            margin: 0.25rem 0 1rem;
            box-shadow: var(--lf-shadow-sm);
        }

        .lf-inline-panel ol {
            margin: 0.5rem 0 0.2rem 1rem;
        }

        /* Info/stat card */
        .lf-stat-card {
            background: linear-gradient(135deg, #ffffff 0%, #fafbff 100%);
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            padding: 1rem 1.2rem;
            box-shadow: var(--lf-shadow-sm);
            transition: box-shadow 0.18s ease, transform 0.18s ease;
        }
        .lf-stat-card:hover {
            box-shadow: var(--lf-shadow-md);
            transform: translateY(-1px);
        }

        /* Global dedup info box */
        .lf-dedup-box {
            background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
            border: 1px solid #86efac;
            border-radius: 12px;
            padding: 0.85rem 1.1rem;
            margin: 0.5rem 0 1rem;
        }

        .lf-dedup-box.warn {
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
            border-color: #fbbf24;
        }

        .lf-dedup-box.info {
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
            border-color: #93c5fd;
        }

        .upload-card {
            border: 1px solid var(--lf-border);
            border-radius: var(--lf-radius);
            padding: 1rem 1.25rem;
            background: linear-gradient(135deg, #ffffff 0%, #fafbff 100%);
            color: var(--lf-body);
            font-weight: 600;
            box-shadow: var(--lf-shadow-sm);
            margin-bottom: 1rem;
            border-left: 4px solid var(--lf-primary);
        }

        [data-testid="stExpander"] {
            border: 1px solid #dfe4f2 !important;
            border-radius: var(--lf-radius) !important;
            background: linear-gradient(135deg, #fbfcff 0%, #f9faff 100%) !important;
            box-shadow: var(--lf-shadow-sm);
            margin-bottom: 0.75rem;
            overflow: hidden;
            transition: box-shadow 0.15s ease !important;
        }

        [data-testid="stExpander"]:hover {
            box-shadow: var(--lf-shadow-md) !important;
        }

        [data-testid="stExpander"] summary {
            font-weight: 700 !important;
            color: var(--lf-title) !important;
            padding: 0.75rem 1rem !important;
        }

        [data-testid="stExpander"] summary:hover {
            color: var(--lf-primary) !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: var(--lf-radius) !important;
        }

        /* ---------------------------------------------------------------
           FILE UPLOADERS
           --------------------------------------------------------------- */
        .lf-upload-label {
            font-weight: 700;
            font-size: 0.92rem;
            color: var(--lf-title);
            margin-bottom: 0.2rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .lf-upload-required {
            font-size: 0.68rem;
            font-weight: 700;
            color: var(--lf-primary);
            background: var(--lf-primary-soft);
            border-radius: 999px;
            padding: 0.08rem 0.55rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .lf-upload-optional {
            font-size: 0.68rem;
            font-weight: 700;
            color: var(--lf-muted);
            background: #eef0f5;
            border-radius: 999px;
            padding: 0.08rem 0.55rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        [data-testid="stFileUploaderDropzone"] svg {display: none;}
        [data-testid="stFileUploaderDropzone"] {
            border: 2px dashed #c7cdea;
            border-radius: 12px;
            background: linear-gradient(135deg, #fbfcff 0%, #f7f8fe 100%);
            transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
        }
        [data-testid="stFileUploaderDropzone"]:hover {
            border-color: var(--lf-primary);
            background: #f0f1ff;
            box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.07);
        }
        [data-testid="stFileUploaderDropzoneInstructions"] {padding-top: 0.5rem;}

        /* Remove-file chip row */
        .lf-file-chip {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin-top: 0.4rem;
            padding: 0.3rem 0.6rem;
            background: #fbfcff;
            border: 1px solid var(--lf-border);
            border-radius: 10px;
        }

        .lf-file-chip-name {
            font-size: 0.82rem;
            color: var(--lf-body);
            font-weight: 600;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

    /* ---------------------------------------------------------------
       FILE REMOVE BUTTON
       --------------------------------------------------------------- */

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
            border-radius: 12px;
            border: 1px solid #d7ddef;
            box-shadow: var(--lf-shadow-sm);
        }

        [data-testid="stMetric"] {
            border: 1px solid var(--lf-border);
            border-radius: 12px;
            background: linear-gradient(135deg, #ffffff 0%, #fafbff 100%);
            padding: 0.85rem 1rem;
            box-shadow: var(--lf-shadow-sm);
            transition: box-shadow 0.18s ease, transform 0.18s ease;
            position: relative;
            overflow: hidden;
        }

        [data-testid="stMetric"]::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--lf-primary), var(--lf-primary-2));
            border-radius: 12px 12px 0 0;
        }

        [data-testid="stMetric"]:hover {
            box-shadow: var(--lf-shadow-md);
            transform: translateY(-2px);
        }

        [data-testid="stMetricLabel"] {
            color: var(--lf-muted) !important;
            font-weight: 600 !important;
            font-size: 0.8rem !important;
        }

        [data-testid="stMetricValue"] {
            color: var(--lf-title) !important;
            font-weight: 800 !important;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid #dde3f0;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: var(--lf-shadow-sm);
        }

        /* ---------------------------------------------------------------
           BUTTONS  (unified button system)
           --------------------------------------------------------------- */
        .stButton > button, [data-testid="stDownloadButton"] > button {
            border-radius: 10px !important;
            font-weight: 700 !important;
            min-height: 2.6rem;
            font-size: 0.92rem !important;
            transition: all 0.18s ease-in-out !important;
            border: 1px solid transparent !important;
            letter-spacing: 0.01em;
        }

        /* Primary CTAs */
        .stButton > button[kind="primary"],
        [data-testid="stDownloadButton"] > button[kind="primary"] {
            background: linear-gradient(135deg, var(--lf-primary), var(--lf-primary-2)) !important;
            color: #ffffff !important;
            box-shadow: var(--lf-shadow-primary) !important;
            border: 1px solid transparent !important;
        }

        .stButton > button[kind="primary"]:hover,
        [data-testid="stDownloadButton"] > button[kind="primary"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 14px 28px rgba(79, 70, 229, 0.35) !important;
            filter: brightness(1.05);
        }

        .stButton > button[kind="primary"]:active,
        [data-testid="stDownloadButton"] > button[kind="primary"]:active {
            transform: translateY(0);
            box-shadow: var(--lf-shadow-primary) !important;
        }

        /* Secondary buttons */
        .stButton > button[kind="secondary"],
        [data-testid="stDownloadButton"] > button[kind="secondary"] {
            background: #ffffff !important;
            color: var(--lf-primary) !important;
            border: 1.5px solid var(--lf-primary) !important;
            box-shadow: none !important;
        }

        .stButton > button[kind="secondary"]:hover,
        [data-testid="stDownloadButton"] > button[kind="secondary"]:hover {
            background: var(--lf-primary-soft) !important;
            color: var(--lf-primary) !important;
            border-color: var(--lf-primary) !important;
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
        }



        /* "How it works" pill */
        div[data-testid="stButton"] div.st-key-how_it_works_btn button {
            min-width: 130px !important;
            height: 40px !important;
            min-height: 40px !important;
            padding: 0 18px !important;
            border-radius: 10px !important;
            white-space: nowrap !important;
            background: #ffffff !important;
            color: var(--lf-primary) !important;
            border: 1.5px solid var(--lf-primary) !important;
            box-shadow: var(--lf-shadow-sm) !important;
        }

        div[data-testid="stButton"] div.st-key-how_it_works_btn button:hover {
            background: var(--lf-primary-soft) !important;
            border-color: var(--lf-primary) !important;
        }

        /* ---------------------------------------------------------------
           TABS
           --------------------------------------------------------------- */
        [data-testid="stTabs"] [role="tablist"] {
            gap: 0.5rem;
            border-bottom: none;
            flex-wrap: wrap;
            padding-bottom: 0.25rem;
        }

        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {
            display: none !important;
        }

        [data-testid="stTabs"] [role="tab"] {
            border: 1.5px solid var(--lf-border);
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.875rem;
            color: var(--lf-muted);
            padding: 0.6rem 1.1rem;
            background: #ffffff;
            transition: all 0.18s ease-in-out;
        }

        [data-testid="stTabs"] [role="tab"]:hover {
            color: var(--lf-primary);
            border-color: var(--lf-primary);
            background: var(--lf-primary-soft);
        }

        [data-testid="stTabs"] [aria-selected="true"] {
            color: #ffffff !important;
            background: linear-gradient(135deg, var(--lf-primary), var(--lf-primary-2)) !important;
            border: 1.5px solid var(--lf-primary) !important;
            box-shadow: var(--lf-shadow-primary);
        }

        /* ---------------------------------------------------------------
           FORM CONTROLS (radio / checkbox / select)
           --------------------------------------------------------------- */
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
            border-color: #c7cdea !important;
        }

        div[data-baseweb="radio"] input:checked + div,
        [data-testid="stCheckbox"] input:checked + span > div:first-child {
            background-color: var(--lf-primary) !important;
            border-color: var(--lf-primary) !important;
        }

        [data-baseweb="select"] > div {
            border-radius: 10px !important;
            border-color: var(--lf-border) !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
        }

        [data-baseweb="select"] > div:hover {
            border-color: var(--lf-primary) !important;
        }

        [data-baseweb="select"] > div:focus-within {
            border-color: var(--lf-primary) !important;
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
        }

        /* Text inputs */
        [data-testid="stTextInput"] input {
            border-radius: 10px !important;
            border-color: var(--lf-border) !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
        }

        [data-testid="stTextInput"] input:focus {
            border-color: var(--lf-primary) !important;
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
        }

        /* ---------------------------------------------------------------
           GLOBAL LOADING OVERLAY & INTERACTION BLOCKER
           --------------------------------------------------------------- */
        @keyframes global-spinner-spin {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }

        [data-testid="stApp"][data-test-script-state="running"]::before {
            content: "";
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(10, 12, 28, 0.55);
            backdrop-filter: blur(5px);
            -webkit-backdrop-filter: blur(5px);
            z-index: 999990;
            pointer-events: all !important;
            cursor: wait !important;
        }

        [data-testid="stApp"][data-test-script-state="running"]::after {
            content: "";
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 58px;
            height: 58px;
            border: 4px solid rgba(255, 255, 255, 0.12);
            border-top: 4px solid var(--lf-primary);
            border-right: 4px solid var(--lf-primary-2);
            border-radius: 50%;
            z-index: 999999;
            animation: global-spinner-spin 0.75s cubic-bezier(0.4, 0, 0.2, 1) infinite;
            pointer-events: none !important;
            box-shadow: 0 0 30px rgba(79, 70, 229, 0.4), 0 12px 30px rgba(0, 0, 0, 0.35);
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
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 1px solid #e2e8f0;
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
           BADGE / PILL ELEMENTS
           --------------------------------------------------------------- */
        .lf-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }

        .lf-badge-success {
            background: var(--lf-success-soft);
            color: var(--lf-success);
        }

        .lf-badge-primary {
            background: var(--lf-primary-soft);
            color: var(--lf-primary);
        }

        .lf-badge-warning {
            background: var(--lf-warning-soft);
            color: var(--lf-warning);
        }

        @media (max-width: 900px) {
            .lf-topbar {
                flex-direction: column;
                align-items: flex-start;
            }
            .lf-section-head h2 {
                font-size: 1.35rem;
            }
            [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"] {
                padding-top: 4.75rem;
            }
            .lf-brand {
                font-size: 2.2rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

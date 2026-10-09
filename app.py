import streamlit as st
from tabs.admin_tab import render_admin_tab

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="Does4U | Admin Portal",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================
# HIDE STREAMLIT DEFAULTS + GLOBAL CSS
# ============================================
st.markdown(
    """
<style>
    /* Hide sidebar collapse button */
    [data-testid="collapsedControl"] { display: none !important; }

    /* Hide footer */
    footer { display: none !important; }

    /* Smooth tab transitions */
    .stTabs [role="tab"] { transition: all 0.3s ease; }

    /* Single admin header (only header in the app) */
    .admin-portal-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #3776ab 100%);
        color: white;
        padding: 24px;
        border-radius: 10px;
        margin-bottom: 20px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .admin-portal-header h1 { margin: 0; font-size: 2em; }
    .admin-portal-header p { margin: 6px 0 0 0; opacity: 0.85; }

    /* Section wrapper used inside tabs */
    .admin-section {
        background: white;
        border-left: 6px solid #3776ab;
        border-radius: 8px;
        padding: 20px;
        margin: 20px 0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .admin-section h2 {
        color: #3776ab;
        margin-top: 0;
        border-bottom: 2px solid #FFD43B;
        padding-bottom: 10px;
    }

    /* Draft + teaser cards */
    .draft-title {
        font-weight: 700; font-size: 1.1em;
        color: #3776ab; margin-bottom: 8px;
    }
    .draft-meta { font-size: 0.9em; color: #666; margin-bottom: 10px; }
    .status-badge {
        display: inline-block; padding: 4px 12px; border-radius: 20px;
        font-size: 0.85em; font-weight: 600;
    }
    .status-draft { background-color: #fff3cd; color: #856404; }
    .teaser-box {
        background: white; border: 1px solid #e9ecef;
        border-radius: 6px; padding: 12px; margin: 10px 0;
    }
    .teaser-platform {
        font-weight: 600; color: #3776ab;
        font-size: 0.9em; margin-bottom: 6px;
    }
    .teaser-text {
        font-size: 0.95em; color: #555; margin-bottom: 8px;
        font-style: italic; line-height: 1.4;
    }
    .char-count { font-size: 0.8em; color: #999; }
</style>
""",
    unsafe_allow_html=True,
)

# ============================================
# SINGLE ADMIN HEADER
# ============================================
st.markdown(
    """
<div class="admin-portal-header">
    <h1>⚙️ Does4U Admin Portal</h1>
    <p>Blog Management &amp; Strategy Center</p>
</div>
""",
    unsafe_allow_html=True,
)

# ============================================
# RENDER ADMIN TABS
# ============================================
render_admin_tab()
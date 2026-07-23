import streamlit as st
from tabs.admin_tab import render_admin_tab

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="Does4U | Admin Portal",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================
# HIDE STREAMLIT DEFAULTS
# ============================================
st.markdown("""
<style>
    /* Hide sidebar collapse button */
    [data-testid="collapsedControl"] { display: none !important; }
    
    /* Hide footer */
    footer { display: none !important; }
    
    /* Smooth transitions */
    .stTabs [role="tab"] {
        transition: all 0.3s ease;
    }
    
    /* Admin Header */
    .admin-portal-header {
        background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
        color: white;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        text-align: center;
    }
    
    .admin-portal-header h1 {
        margin: 0;
        font-size: 2em;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# ADMIN PORTAL - NO PASSWORD
# ============================================

st.markdown("""
<div class="admin-portal-header">
    <h1>⚙️ Does4U Admin Portal</h1>
    <p>Blog Management & Strategy Center</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# Render admin panel
render_admin_tab()
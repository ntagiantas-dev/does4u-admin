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
    
    .login-container {
        max-width: 500px;
        margin: 100px auto;
        background: white;
        border-left: 8px solid #3776ab;
        border-radius: 8px;
        padding: 40px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.15);
    }
    
    .login-title {
        color: #3776ab;
        font-weight: 700;
        font-size: 1.8em;
        text-align: center;
        margin-bottom: 30px;
    }
    
    .login-hint {
        color: #666;
        font-size: 0.95em;
        text-align: center;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# ADMIN PASSWORD CHECK
# ============================================
def check_admin_password(password: str) -> bool:
    """Check if password matches the admin password from secrets"""
    try:
        admin_password = st.secrets.get("ADMIN_PASSWORD", "")
        return password == admin_password and password != ""
    except:
        return False

# ============================================
# INITIALIZE SESSION STATE
# ============================================
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

# ============================================
# ADMIN PORTAL
# ============================================

if st.session_state.admin_authenticated:
    # ADMIN IS LOGGED IN - SHOW ADMIN PANEL
    st.markdown("""
    <div class="admin-portal-header">
        <h1>⚙️ Does4U Admin Portal</h1>
        <p>Blog Management & Strategy Center</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Logout button in top right
    col1, col2 = st.columns([5, 1])
    with col2:
        if st.button("🚪 Logout", key="logout_btn", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()
    
    st.markdown("---")
    
    # Render admin panel
    render_admin_tab()

else:
    # ADMIN IS NOT LOGGED IN - SHOW LOGIN FORM
    st.markdown("""
    <div class="login-container">
        <div class="login-title">🔐 Admin Access</div>
        <p class="login-hint">Enter your admin password to access the portal</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("")  # spacing
        admin_password = st.text_input(
            "Admin Password",
            type="password",
            placeholder="Enter password",
            key="admin_login_password"
        )
        
        st.markdown("")  # spacing
        
        if st.button("🔓 Unlock Admin Panel", use_container_width=True):
            if check_admin_password(admin_password):
                st.session_state.admin_authenticated = True
                st.success("✅ Welcome to the admin panel!")
                st.rerun()
            else:
                st.error("❌ Incorrect password. Access denied.")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #999; font-size: 0.9em; padding: 20px;">
        <p>Does4U Admin Portal</p>
        <p>🔒 This is a secure area. Only authorized personnel can access.</p>
    </div>
    """, unsafe_allow_html=True)
"""
Blog Tab for Does4U Admin
3 Tabs: Generate (with OpenAI), Drafts (manage), Published (view)
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import datetime
import openai

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import init_database
from utils.db import (
    save_blog_article, get_blog_articles, update_blog_article, 
    save_blog_traffic, get_blog_traffic
)

# Initialize database on first run
if "db_initialized" not in st.session_state:
    st.session_state.db_initialized = init_database()

def blog_tab():
    """Main blog interface - 3 tabs"""
    
    st.markdown("## 📝 Blog Management")
    
    tab1, tab2, tab3 = st.tabs(["✨ Generate", "📋 Drafts", "🚀 Published"])
    
    # ====================================================================
    # TAB 1: GENERATE (with OpenAI)
    # ====================================================================
    with tab1:
        st.markdown("### Generate New Article with AI")
        
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("📌 Article Topic", placeholder="e.g., AI Automation for Greek SMBs")
        with col2:
            article_topic = st.selectbox(
                "📁 Topic Category",
                ["AI Automation", "Python Development", "Business Strategy", "Marketing", "General"]
            )
        
        keywords = st.text_area("🔑 Keywords (comma-separated)", placeholder="automation, AI, business, python")
        tone = st.radio("💬 Tone", ["Professional", "Casual", "Educational"], horizontal=True)
        
        col1, col2 = st.columns(2)
        with col1:
            max_tokens = st.slider("📏 Article Length", 500, 3000, 1500, step=100)
        with col2:
            generate_button = st.button("🤖 Generate Article", use_container_width=True)
        
        if generate_button:
            if not topic:
                st.error("❌ Please enter a topic")
            else:
                with st.spinner("⏳ Generating article with OpenAI..."):
                    try:
                        # OpenAI prompt
                        prompt = f"""
Create a comprehensive blog article about: {topic}

Keywords: {keywords}
Tone: {tone}

Structure:
1. Engaging Introduction (hook the reader)
2. 3-4 Main sections with detailed insights
3. Key Takeaways (bullet points)
4. Call-to-Action (what readers should do next)

Write in {tone.lower()} tone. Target audience: Greek small-medium businesses.
Output ONLY the article content, no metadata or titles.
"""
                        
                        # Call OpenAI API
                        openai.api_key = os.getenv("OPENAI_API_KEY")
                        response = openai.ChatCompletion.create(
                            model="gpt-4",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.7,
                            max_tokens=max_tokens
                        )
                        
                        article_content = response.choices[0].message.content
                        
                        # Save to database
                        article_id = f"article_{datetime.now().timestamp()}"
                        saved_id = save_blog_article(article_id, topic, article_topic)
                        
                        if saved_id:
                            # Update with content
                            update_blog_article(article_id, content=article_content, status='draft')
                            
                            st.success(f"✅ Article saved to drafts! (ID: {article_id})")
                            st.markdown("---")
                            st.markdown("**Preview:**")
                            st.markdown(article_content[:800] + "...")
                            
                            # Store in session for quick edit
                            st.session_state.last_generated = {
                                'id': article_id,
                                'title': topic,
                                'content': article_content,
                                'topic': article_topic
                            }
                        else:
                            st.error("❌ Failed to save article to database")
                    
                    except Exception as e:
                        st.error(f"❌ Generation error: {str(e)}")
    
    # ====================================================================
    # TAB 2: DRAFTS (Manage)
    # ====================================================================
    with tab2:
        st.markdown("### 📋 Draft Articles")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_topic = st.selectbox(
                "Filter by topic",
                ["All", "AI Automation", "Python Development", "Business Strategy", "Marketing", "General"],
                key="draft_filter"
            )
        with col2:
            sort_by = st.selectbox("Sort by", ["Newest", "Oldest", "A-Z"], key="draft_sort")
        with col3:
            if st.button("🔄 Refresh", use_container_width=True):
                st.rerun()
        
        # Fetch drafts
        if filter_topic == "All":
            drafts = get_blog_articles(status='draft')
        else:
            drafts = get_blog_articles(status='draft', topic=filter_topic)
        
        # Sort
        if drafts:
            if sort_by == "Oldest":
                drafts = sorted(drafts, key=lambda x: x[6])
            elif sort_by == "A-Z":
                drafts = sorted(drafts, key=lambda x: x[2])
            else:  # Newest
                drafts = sorted(drafts, reverse=True, key=lambda x: x[6])
        
        if drafts:
            st.info(f"📊 Total drafts: {len(drafts)}")
            
            for draft in drafts:
                id, article_id, title, topic, status, slug, created_at, published_at = draft
                
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{title}**")
                        st.caption(f"Topic: {topic} | Created: {created_at}")
                    with col2:
                        st.caption(f"Status: 📝 {status}")
                    
                    # Action buttons
                    col1, col2, col3, col4, col5 = st.columns(5)
                    
                    with col1:
                        if st.button("✏️ Edit", key=f"edit_{id}", use_container_width=True):
                            st.session_state[f"edit_{id}"] = True
                    
                    with col2:
                        if st.button("📤 Publish", key=f"pub_{id}", use_container_width=True):
                            update_blog_article(article_id, status='published')
                            st.success(f"✅ Published!")
                            st.rerun()
                    
                    with col3:
                        if st.button("👁️ Preview", key=f"view_{id}", use_container_width=True):
                            st.session_state[f"view_{id}"] = True
                    
                    with col4:
                        if st.button("🔗 Slug", key=f"slug_{id}", use_container_width=True):
                            st.info(f"URL Slug: `{slug}`")
                    
                    with col5:
                        if st.button("🗑️ Delete", key=f"del_{id}", use_container_width=True):
                            update_blog_article(article_id, status='archived')
                            st.warning("✅ Archived!")
                            st.rerun()
        else:
            st.info("📭 No drafts yet. Generate one in the **Generate** tab!")
    
    # ====================================================================
    # TAB 3: PUBLISHED (View)
    # ====================================================================
    with tab3:
        st.markdown("### 🚀 Published Articles")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_topic = st.selectbox(
                "Filter by topic",
                ["All", "AI Automation", "Python Development", "Business Strategy", "Marketing", "General"],
                key="pub_filter"
            )
        with col2:
            limit = st.slider("Articles to show", 5, 50, 15)
        with col3:
            if st.button("🔄 Refresh", use_container_width=True, key="refresh_pub"):
                st.rerun()
        
        # Fetch published articles
        if filter_topic == "All":
            articles = get_blog_articles(status='published', limit=limit)
        else:
            articles = get_blog_articles(status='published', topic=filter_topic, limit=limit)
        
        if articles:
            st.success(f"✅ {len(articles)} published articles found")
            
            for article in articles:
                id, article_id, title, topic, status, slug, created_at, published_at = article
                
                with st.container(border=True):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.markdown(f"# {title}")
                    with col2:
                        st.caption(f"📁 {topic}")
                    with col3:
                        st.caption(f"📅 {published_at}")
                    
                    # Traffic summary
                    traffic = get_blog_traffic(article_id=id, days=30)
                    if traffic:
                        total_visitors = sum([t[3] for t in traffic])
                        st.metric("👥 Visitors (30 days)", total_visitors)
                    
                    # Action buttons
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.caption(f"🔗 Slug: `{slug}`")
                    with col2:
                        if st.button("📊 View Full", key=f"view_full_{id}", use_container_width=True):
                            st.session_state[f"view_full_{id}"] = True
                    with col3:
                        if st.button("🗂️ Archive", key=f"archive_{id}", use_container_width=True):
                            update_blog_article(article_id, status='archived')
                            st.info("✅ Archived!")
                            st.rerun()
        else:
            st.info("📭 No published articles yet.")

# Export function to call from main.py
if __name__ == "__main__":
    blog_tab()
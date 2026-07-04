import streamlit as st
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import uuid


# ============================================
# CONSTANTS
# ============================================
DRAFTS_FILE = "drafts.json"
BLOG_FILE = "blog_data.json"
MAX_DRAFTS_IN_HISTORY = 30

# ============================================
# UTILITY FUNCTIONS
# ============================================

def load_drafts() -> List[Dict]:
    """Load all drafts from drafts.json"""
    if not os.path.exists(DRAFTS_FILE):
        return []
    
    try:
        with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []
    except Exception as e:
        st.error(f"Error loading drafts: {str(e)}")
        return []


def save_drafts(drafts: List[Dict]) -> bool:
    """Save drafts to drafts.json"""
    try:
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving drafts: {str(e)}")
        return False


def load_blog() -> List[Dict]:
    """Load published articles from blog_data.json"""
    if not os.path.exists(BLOG_FILE):
        return []
    
    try:
        with open(BLOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []
    except Exception as e:
        st.error(f"Error loading blog data: {str(e)}")
        return []


def save_blog(articles: List[Dict]) -> bool:
    """Save blog articles to blog_data.json"""
    try:
        with open(BLOG_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving blog data: {str(e)}")
        return False


def create_draft_object(
    article_data: Dict,
    teasers_data: Dict,
    target_point: str,
    category: str,
    source_url: str
) -> Dict:
    """Create a draft object with all necessary data"""
    return {
        "id": str(uuid.uuid4()),
        "title": article_data.get("title", "Untitled"),
        "content": article_data.get("content", ""),
        "category": category,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "author": "Does4U",
        "social_teaser": {
            "twitter": teasers_data.get("twitter", {}).get("text", ""),
            "linkedin": teasers_data.get("linkedin", {}).get("text", ""),
            "facebook": teasers_data.get("facebook", {}).get("text", "")
        },
        "keywords": article_data.get("keywords", []),
        "target_point": target_point,
        "source_url": source_url,
        "status": "draft",
        "word_count": article_data.get("word_count", 0),
        "created_at": datetime.now().isoformat()
    }


def publish_draft(draft: Dict) -> bool:
    """Move draft to published blog"""
    try:
        # Load current blog
        blog_articles = load_blog()
        
        # Update draft status
        draft["status"] = "published"
        draft["published_at"] = datetime.now().isoformat()
        
        # Add to blog
        blog_articles.append(draft)
        
        # Save blog
        if not save_blog(blog_articles):
            return False
        
        # Remove from drafts
        drafts = load_drafts()
        drafts = [d for d in drafts if d.get("id") != draft.get("id")]
        
        if not save_drafts(drafts):
            return False
        
        return True
    
    except Exception as e:
        st.error(f"Error publishing draft: {str(e)}")
        return False


def delete_draft(draft_id: str) -> bool:
    """Delete a draft"""
    try:
        drafts = load_drafts()
        drafts = [d for d in drafts if d.get("id") != draft_id]
        return save_drafts(drafts)
    except Exception as e:
        st.error(f"Error deleting draft: {str(e)}")
        return False


# ============================================
# MAIN RENDER FUNCTION
# ============================================

def render_admin_tab():
    """Admin panel for blog management"""
    
    # ============================================
    # CUSTOM CSS
    # ============================================
    st.markdown("""
    <style>
        .admin-header {
            background: linear-gradient(135deg, #3776ab 0%, #1e3a5f 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            text-align: center;
        }
        
        .admin-header h1 {
            margin: 0;
            font-size: 2.5em;
        }
        
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
        
        .draft-card {
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            transition: all 0.3s ease;
        }
        
        .draft-card:hover {
            border-color: #3776ab;
            box-shadow: 0 4px 12px rgba(55, 118, 171, 0.2);
        }
        
        .draft-title {
            font-weight: 700;
            font-size: 1.1em;
            color: #3776ab;
            margin-bottom: 8px;
        }
        
        .draft-meta {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 10px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }
        
        .status-draft {
            background-color: #fff3cd;
            color: #856404;
        }
        
        .teaser-box {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 12px;
            margin: 10px 0;
        }
        
        .teaser-platform {
            font-weight: 600;
            color: #3776ab;
            font-size: 0.9em;
            margin-bottom: 6px;
        }
        
        .teaser-text {
            font-size: 0.95em;
            color: #555;
            margin-bottom: 8px;
            font-style: italic;
            line-height: 1.4;
        }
        
        .char-count {
            font-size: 0.8em;
            color: #999;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # ============================================
    # HEADER
    # ============================================
    st.markdown("""
    <div class="admin-header">
        <h1>⚙️ Admin Panel</h1>
        <p>Generate, manage, and publish blog articles</p>
    </div>
    """, unsafe_allow_html=True)
    
    # ============================================
    # TABS
    # ============================================
    admin_tabs = st.tabs(["📝 Generate Article", "📚 Drafts History", "📊 Analytics"])
    
    # ============================================
    # TAB 1: GENERATE ARTICLE
    # ============================================
    with admin_tabs[0]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📝 Generate New Article</h2>", unsafe_allow_html=True)
        
        # Form
        col1, col2 = st.columns(2)
        
        with col1:
            target_point = st.text_input(
                "Target Point (Keywords) *",
                placeholder="e.g., automation excel outreach",
                help="Keywords to search for content"
            )
        
        with col2:
            category = st.selectbox(
                "Category *",
                options=[
                    "Web Scraping",
                    "Excel & Reporting",
                    "Data Collection",
                    "AI Workflows",
                    "Custom Python Scripts"
                ],
                help="Select article category"
            )
        
        # Generate button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            generate_btn = st.button("🚀 Generate Article", use_container_width=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # ============================================
        # GENERATION LOGIC - LAZY LOADING
        # ============================================
        if generate_btn:
            if not target_point or not category:
                st.error("❌ Please fill in all required fields")
            else:
                # Step 1: Extract content with Jina (LAZY LOAD)
                with st.spinner("🔍 Extracting content from web..."):
                    try:
                        from utils.jina_service import JinaService
                        jina_service = JinaService()
                        extracted_data = jina_service.search_and_extract(target_point)
                    except Exception as e:
                        st.error(f"❌ Error with Jina service: {str(e)}")
                        extracted_data = None
                
                if extracted_data:
                    # Step 2: Generate article + teasers (LAZY LOAD)
                    try:
                        from utils.article_generator import ArticleGenerator
                        generator = ArticleGenerator()
                        result = generator.full_pipeline(
                            extracted_content=extracted_data.get("content", ""),
                            target_point=target_point,
                            category=category
                        )
                    except Exception as e:
                        st.error(f"❌ Error with article generation: {str(e)}")
                        result = None
                    
                    if result:
                        article_data, teasers_data = result
                        
                        # Step 3: Create draft
                        draft = create_draft_object(
                            article_data=article_data,
                            teasers_data=teasers_data,
                            target_point=target_point,
                            category=category,
                            source_url=extracted_data.get("source_url", "")
                        )
                        
                        # Display generated article
                        st.success("✅ Article generated successfully!")
                        
                        # ============================================
                        # DISPLAY ARTICLE PREVIEW
                        # ============================================
                        with st.container(border=True):
                            st.markdown("### 📄 Article Preview")
                            st.markdown(f"**Title:** {draft['title']}")
                            st.markdown(f"**Category:** {category}")
                            st.markdown(f"**Word Count:** {draft['word_count']} words")
                            st.markdown(f"**Keywords:** {', '.join(draft['keywords'])}")
                            st.markdown("---")
                            st.markdown(draft['content'])
                        
                        # ============================================
                        # DISPLAY SOCIAL TEASERS
                        # ============================================
                        with st.container(border=True):
                            st.markdown("### 📱 Social Media Teasers")
                            
                            # Twitter
                            st.markdown("<div class='teaser-box'>", unsafe_allow_html=True)
                            st.markdown("<div class='teaser-platform'>🐦 Twitter/X</div>", unsafe_allow_html=True)
                            twitter_text = draft['social_teaser']['twitter']
                            st.markdown(f"<div class='teaser-text'>{twitter_text}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div class='char-count'>{len(twitter_text)} / 280 characters</div>", unsafe_allow_html=True)
                            col1, col2 = st.columns([3, 1])
                            with col2:
                                if st.button("📋 Copy", key="copy_twitter"):
                                    st.write(twitter_text)
                                    st.success("Copied!")
                            st.markdown("</div>", unsafe_allow_html=True)
                            
                            # LinkedIn
                            st.markdown("<div class='teaser-box'>", unsafe_allow_html=True)
                            st.markdown("<div class='teaser-platform'>💼 LinkedIn</div>", unsafe_allow_html=True)
                            linkedin_text = draft['social_teaser']['linkedin']
                            st.markdown(f"<div class='teaser-text'>{linkedin_text}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div class='char-count'>{len(linkedin_text)} / 300 characters</div>", unsafe_allow_html=True)
                            col1, col2 = st.columns([3, 1])
                            with col2:
                                if st.button("📋 Copy", key="copy_linkedin"):
                                    st.write(linkedin_text)
                                    st.success("Copied!")
                            st.markdown("</div>", unsafe_allow_html=True)
                            
                            # Facebook
                            st.markdown("<div class='teaser-box'>", unsafe_allow_html=True)
                            st.markdown("<div class='teaser-platform'>📘 Facebook</div>", unsafe_allow_html=True)
                            facebook_text = draft['social_teaser']['facebook']
                            st.markdown(f"<div class='teaser-text'>{facebook_text}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div class='char-count'>{len(facebook_text)} / 150 characters</div>", unsafe_allow_html=True)
                            col1, col2 = st.columns([3, 1])
                            with col2:
                                if st.button("📋 Copy", key="copy_facebook"):
                                    st.write(facebook_text)
                                    st.success("Copied!")
                            st.markdown("</div>", unsafe_allow_html=True)
                        
                        # ============================================
                        # SAVE OR PUBLISH
                        # ============================================
                        st.markdown("---")
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if st.button("💾 Save as Draft", use_container_width=True):
                                drafts = load_drafts()
                                # Keep only last MAX_DRAFTS_IN_HISTORY
                                drafts = drafts[-MAX_DRAFTS_IN_HISTORY+1:] if len(drafts) >= MAX_DRAFTS_IN_HISTORY else drafts
                                drafts.append(draft)
                                if save_drafts(drafts):
                                    st.success("✅ Draft saved! Check the 'Drafts History' tab")
                                else:
                                    st.error("❌ Failed to save draft")
                        
                        with col2:
                            if st.button("🚀 Publish Immediately", use_container_width=True):
                                if publish_draft(draft):
                                    st.success("✅ Article published to blog!")
                                    st.balloons()
                                else:
                                    st.error("❌ Failed to publish article")
    
    # ============================================
    # TAB 2: DRAFTS HISTORY
    # ============================================
    with admin_tabs[1]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📚 Drafts History</h2>", unsafe_allow_html=True)
        
        drafts = load_drafts()
        
        if not drafts:
            st.info("📭 No drafts yet. Generate your first article in the 'Generate Article' tab!")
        else:
            st.markdown(f"**Total Drafts:** {len(drafts)} (Max {MAX_DRAFTS_IN_HISTORY})")
            st.markdown("---")
            
            # Display drafts in reverse order (newest first)
            for idx, draft in enumerate(reversed(drafts)):
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    
                    with col1:
                        st.markdown(f"<div class='draft-title'>{draft['title']}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='draft-meta'>", unsafe_allow_html=True)
                        st.markdown(f"📅 {draft['date']} | 📂 {draft['category']} | 📝 {draft['word_count']} words", unsafe_allow_html=True)
                        st.markdown(f"🎯 Target: {draft['target_point']}", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
                    
                    with col2:
                        st.markdown(f"<span class='status-badge status-draft'>DRAFT</span>", unsafe_allow_html=True)
                    
                    # Action buttons
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        if st.button("👁️ Preview", key=f"preview_{draft['id']}"):
                            st.markdown("**Preview:**")
                            st.markdown(draft['content'][:300] + "...")
                    
                    with col2:
                        if st.button("🚀 Publish", key=f"publish_{draft['id']}"):
                            if publish_draft(draft):
                                st.success("✅ Published!")
                                st.rerun()
                            else:
                                st.error("❌ Failed to publish")
                    
                    with col3:
                        if st.button("🗑️ Delete", key=f"delete_{draft['id']}"):
                            if delete_draft(draft['id']):
                                st.success("✅ Deleted!")
                                st.rerun()
                            else:
                                st.error("❌ Failed to delete")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # ============================================
    # TAB 3: ANALYTICS
    # ============================================
    with admin_tabs[2]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📊 Analytics</h2>", unsafe_allow_html=True)
        
        drafts = load_drafts()
        blog = load_blog()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("📚 Published Articles", len(blog))
        
        with col2:
            st.metric("📝 Draft Articles", len(drafts))
        
        with col3:
            total_articles = len(blog) + len(drafts)
            st.metric("📊 Total Articles", total_articles)
        
        # Category breakdown
        if blog:
            st.markdown("---")
            st.markdown("**📂 Categories (Published):**")
            categories = {}
            for article in blog:
                cat = article.get("category", "Uncategorized")
                categories[cat] = categories.get(cat, 0) + 1
            
            for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                st.markdown(f"- {cat}: **{count}** articles")
        
        st.markdown("</div>", unsafe_allow_html=True)


# ============================================
# EXPORT FUNCTION
# ============================================
if __name__ == "__main__":
    render_admin_tab()
import streamlit as st
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from utils.prompts import BLOG_CATEGORIES


# ============================================
# CONSTANTS
# ============================================
DRAFTS_FILE = "drafts.json"
BLOG_FILE = "blog_data.json"
MAX_DRAFTS_IN_HISTORY = 30

LANGUAGE_CHOICES: Dict[str, str] = {
    "🇬🇷 Greek": "Greek",
    "🇬🇧 English": "English",
    "🌐 Both (Greek + English)": "Both",
}

# Only the two CEO-approved categories exist.
CATEGORY_NAMES: List[str] = list(BLOG_CATEGORIES.keys())


# ============================================
# JSON PERSISTENCE
# ============================================

def load_drafts() -> List[Dict]:
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
    try:
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving drafts: {str(e)}")
        return False


def load_blog() -> List[Dict]:
    if not os.path.exists(BLOG_FILE):
        return []
    try:
        with open(BLOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []
    except Exception as e:
        st.error(f"Error loading blog: {str(e)}")
        return []


def save_blog(articles: List[Dict]) -> bool:
    try:
        with open(BLOG_FILE, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving blog: {str(e)}")
        return False


# ============================================
# DRAFT OBJECT
# ============================================

def create_draft_object(
    article_data: Dict,
    teasers_data: Dict,
    target_point: str,
    category: str,
    category_slug: str,
    source_url: str,
    language: str,
    translation_id: Optional[str],
) -> Dict:
    """Build a draft dict ready for JSON storage.

    FastAPI-consumed URL fields:
        category_slug + slug + language  ->  builds the final URL:
            /blog/{category_slug}/{slug}/           (en)
            /el/blog/{category_slug}/{slug}/        (el)
    """
    return {
        "id": str(uuid.uuid4()),
        "title": article_data.get("title", "Untitled"),
        "slug": article_data.get("slug", ""),
        "content": article_data.get("content_markdown", ""),
        "meta_description": article_data.get("meta_description", ""),
        "reading_time_minutes": article_data.get("reading_time_minutes", 0),
        "category": category,
        "category_slug": category_slug,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "author": "Does4U",
        "language": language,
        "translation_id": translation_id,
        "social_teaser": {
            "twitter": teasers_data.get("twitter", {}).get("text", ""),
            "linkedin": teasers_data.get("linkedin", {}).get("text", ""),
            "facebook": teasers_data.get("facebook", {}).get("text", ""),
        },
        "keywords": article_data.get("keywords", []),
        "target_point": target_point,
        "source_url": source_url,
        "status": "draft",
        "word_count": article_data.get("word_count", 0),
        "created_at": datetime.now().isoformat(),
    }


# ============================================
# DRAFT LIFECYCLE
# ============================================

def publish_draft(draft: Dict) -> bool:
    try:
        blog = load_blog()
        draft["status"] = "published"
        draft["published_at"] = datetime.now().isoformat()
        blog.append(draft)
        if not save_blog(blog):
            return False
        drafts = [d for d in load_drafts() if d.get("id") != draft.get("id")]
        return save_drafts(drafts)
    except Exception as e:
        st.error(f"Error publishing: {str(e)}")
        return False


def delete_draft(draft_id: str) -> bool:
    try:
        drafts = [d for d in load_drafts() if d.get("id") != draft_id]
        return save_drafts(drafts)
    except Exception as e:
        st.error(f"Error deleting: {str(e)}")
        return False


def save_bundles_as_drafts(
    bundles: List[Dict[str, Any]],
    target_point: str,
    category: str,
    category_slug: str,
    source_url: str,
) -> bool:
    drafts = load_drafts()
    new_drafts = [
        create_draft_object(
            article_data=b["article"],
            teasers_data=b["teasers"],
            target_point=target_point,
            category=category,
            category_slug=category_slug,
            source_url=source_url,
            language=b["language"],
            translation_id=b["translation_id"],
        )
        for b in bundles
    ]
    combined = drafts + new_drafts
    if len(combined) > MAX_DRAFTS_IN_HISTORY:
        combined = combined[-MAX_DRAFTS_IN_HISTORY:]
    return save_drafts(combined)


def publish_bundles(
    bundles: List[Dict[str, Any]],
    target_point: str,
    category: str,
    category_slug: str,
    source_url: str,
) -> bool:
    blog = load_blog()
    for b in bundles:
        draft = create_draft_object(
            article_data=b["article"],
            teasers_data=b["teasers"],
            target_point=target_point,
            category=category,
            category_slug=category_slug,
            source_url=source_url,
            language=b["language"],
            translation_id=b["translation_id"],
        )
        draft["status"] = "published"
        draft["published_at"] = datetime.now().isoformat()
        blog.append(draft)
    return save_blog(blog)


# ============================================
# RENDER HELPERS
# ============================================

def _render_article_preview(bundle: Dict[str, Any], category: str) -> None:
    a = bundle["article"]
    with st.container(border=True):
        st.markdown(
            f"### 📄 Article Preview — {bundle['language_name']} ({bundle['language']})"
        )
        if bundle.get("translation_id"):
            st.caption(f"🔗 translation_id: `{bundle['translation_id']}`")
        st.markdown(f"**Title:** {a.get('title', '—')}")
        if a.get("slug"):
            st.markdown(f"**Slug:** `{a['slug']}`")
        if a.get("meta_description"):
            st.markdown(f"**Meta description:** {a['meta_description']}")
        st.markdown(f"**Category:** {category}")
        st.markdown(
            f"**Word count:** {a.get('word_count', 0)} "
            f"| **Reading time:** {a.get('reading_time_minutes', 0)} min"
        )
        kws = a.get("keywords") or []
        st.markdown(f"**Keywords:** {', '.join(kws) if kws else '—'}")
        st.markdown("---")
        st.markdown(a.get("content_markdown", ""))


def _render_teasers(bundle: Dict[str, Any]) -> None:
    teasers = bundle["teasers"]
    lang_code = bundle["language"]
    with st.container(border=True):
        st.markdown("### 📱 Social Media Teasers")
        for key, label, limit in (
            ("twitter", "🐦 Twitter/X", 280),
            ("linkedin", "💼 LinkedIn", 300),
            ("facebook", "📘 Facebook", 150),
        ):
            text = (teasers.get(key) or {}).get("text", "")
            st.markdown("<div class='teaser-box'>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='teaser-platform'>{label}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(f"<div class='teaser-text'>{text}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='char-count'>{len(text)} / {limit} characters</div>",
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("📋 Copy", key=f"copy_{key}_{lang_code}"):
                    st.code(text)
            st.markdown("</div>", unsafe_allow_html=True)


def _render_cleaner_debug(cleaner_output: Dict[str, Any]) -> None:
    with st.expander("🔧 Cleaner output (debug)", expanded=False):
        if cleaner_output.get("_fallback"):
            st.warning("⚠️ Cleaner failed — showing raw content fallback.")
        st.markdown(f"**Topic summary:** {cleaner_output.get('topic_summary') or '—'}")
        st.markdown("**Key facts:**")
        facts = cleaner_output.get("key_facts") or []
        if facts:
            for f in facts:
                st.markdown(f"- {f}")
        else:
            st.markdown("_(none)_")
        st.markdown("**Cleaned content (first 800 chars):**")
        st.code((cleaner_output.get("cleaned_content") or "")[:800])


def _render_bundle(bundle: Dict[str, Any], category: str) -> None:
    _render_article_preview(bundle, category)
    _render_teasers(bundle)


# ============================================
# MAIN RENDER — no header (header lives in app.py)
# ============================================

def render_admin_tab() -> None:
    """Render the three admin tabs (Generate / Drafts / Analytics)."""

    if "last_gen" not in st.session_state:
        st.session_state["last_gen"] = None

    admin_tabs = st.tabs(["📝 Generate Article", "📚 Drafts History", "📊 Analytics"])

    # ---------- TAB 1: GENERATE ----------
    with admin_tabs[0]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📝 Generate New Article</h2>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            target_point = st.text_input(
                "Target Point (Keywords) *",
                placeholder="e.g., automation excel outreach",
                help="Keywords to search for content",
            )
        with col2:
            category = st.selectbox(
                "Category *",
                options=CATEGORY_NAMES,
                help="Determines section + writing angle (traffic vs conversion)",
            )

        language_label = st.selectbox(
            "Language *",
            options=list(LANGUAGE_CHOICES.keys()),
            index=0,  # Greek-first (D-010)
            help=(
                "🌐 Both generates 2 articles (Greek + English) sharing a "
                "translation_id, for hreflang pairing on the FastAPI site."
            ),
        )
        language_value = LANGUAGE_CHOICES[language_label]

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            generate_btn = st.button("🚀 Generate Article", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if generate_btn:
            if not target_point or not category:
                st.error("❌ Please fill in all required fields")
            else:
                # Fetch (Jina)
                extracted_data: Optional[Dict] = None
                with st.spinner("🔍 Fetching content from web..."):
                    try:
                        from utils.jina_service import JinaService
                        extracted_data = JinaService().search_and_extract(target_point)
                    except Exception as e:
                        st.error(f"❌ Jina error: {e}")

                if not extracted_data:
                    st.warning("⚠️ No content extracted. Pipeline aborted.")
                else:
                    try:
                        from utils.article_generator import ArticleGenerator
                        generator = ArticleGenerator()
                    except Exception as e:
                        st.error(f"❌ Error initializing ArticleGenerator: {e}")
                        generator = None

                    if generator is not None:
                        output = generator.full_pipeline(
                            extracted_content=extracted_data.get("content", ""),
                            target_point=target_point,
                            category=category,
                            language_selection=language_value,
                        )
                        st.session_state["last_gen"] = {
                            "cleaner": output.get("cleaner", {}),
                            "bundles": output.get("bundles", []),
                            "category": category,
                            "category_slug": output.get("category_slug", ""),
                            "target_point": target_point,
                            "source_url": extracted_data.get("source_url", ""),
                            "saved": False,
                            "published": False,
                        }

        # ---------- DISPLAY LAST GENERATION ----------
        gen = st.session_state.get("last_gen")
        if gen and gen.get("bundles"):
            bundles = gen["bundles"]
            category = gen["category"]
            target_point = gen["target_point"]
            source_url = gen["source_url"]
            category_slug = gen["category_slug"]

            st.success(f"✅ Generated {len(bundles)} article bundle(s) successfully!")
            _render_cleaner_debug(gen["cleaner"])

            if len(bundles) == 1:
                _render_bundle(bundles[0], category)
            else:
                flag = {"el": "🇬🇷", "en": "🇬🇧"}
                tabs = st.tabs(
                    [f"{flag.get(b['language'], '🌐')} {b['language_name']}" for b in bundles]
                )
                for tab, bundle in zip(tabs, bundles):
                    with tab:
                        _render_bundle(bundle, category)

            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    "💾 Save as Draft",
                    use_container_width=True,
                    disabled=gen.get("saved") or gen.get("published"),
                ):
                    if save_bundles_as_drafts(
                        bundles, target_point, category, category_slug, source_url
                    ):
                        gen["saved"] = True
                        st.success(f"✅ Saved {len(bundles)} draft(s).")
                    else:
                        st.error("❌ Failed to save draft(s)")
            with col2:
                if st.button(
                    "🚀 Publish Immediately",
                    use_container_width=True,
                    disabled=gen.get("published"),
                ):
                    if publish_bundles(
                        bundles, target_point, category, category_slug, source_url
                    ):
                        gen["published"] = True
                        st.success(f"✅ Published {len(bundles)} article(s)!")
                        st.balloons()
                    else:
                        st.error("❌ Failed to publish")

            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🗑️ Clear Result", use_container_width=True):
                    st.session_state["last_gen"] = None
                    st.rerun()

    # ---------- TAB 2: DRAFTS ----------
    with admin_tabs[1]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📚 Drafts History</h2>", unsafe_allow_html=True)

        drafts = load_drafts()
        if not drafts:
            st.info("📭 No drafts yet. Generate your first article first!")
        else:
            st.markdown(f"**Total Drafts:** {len(drafts)} (Max {MAX_DRAFTS_IN_HISTORY})")
            st.markdown("---")
            for draft in reversed(drafts):
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(
                            f"<div class='draft-title'>{draft['title']}</div>",
                            unsafe_allow_html=True,
                        )
                        lang_badge = {"el": "🇬🇷", "en": "🇬🇧"}.get(
                            draft.get("language", ""), "🌐"
                        )
                        st.markdown(
                            f"📅 {draft['date']} | 📂 {draft['category']} "
                            f"| 📝 {draft['word_count']} words | {lang_badge} {draft.get('language','—')}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"🎯 Target: {draft['target_point']}")
                        if draft.get("translation_id"):
                            st.caption(f"🔗 translation_id: `{draft['translation_id']}`")
                    with col2:
                        st.markdown(
                            "<span class='status-badge status-draft'>DRAFT</span>",
                            unsafe_allow_html=True,
                        )
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("👁️ Preview", key=f"pv_{draft['id']}"):
                            st.markdown(draft["content"][:300] + "...")
                    with c2:
                        if st.button("🚀 Publish", key=f"pub_{draft['id']}"):
                            if publish_draft(draft):
                                st.success("✅ Published!")
                                st.rerun()
                    with c3:
                        if st.button("🗑️ Delete", key=f"del_{draft['id']}"):
                            if delete_draft(draft["id"]):
                                st.success("✅ Deleted!")
                                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # ---------- TAB 3: ANALYTICS ----------
    with admin_tabs[2]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📊 Analytics</h2>", unsafe_allow_html=True)
        drafts = load_drafts()
        blog = load_blog()

        c1, c2, c3 = st.columns(3)
        c1.metric("📚 Published", len(blog))
        c2.metric("📝 Drafts", len(drafts))
        c3.metric("📊 Total", len(blog) + len(drafts))

        if blog:
            st.markdown("---")
            st.markdown("**🌐 By language:**")
            lang_counts: Dict[str, int] = {}
            for a in blog:
                code = a.get("language", "—")
                lang_counts[code] = lang_counts.get(code, 0) + 1
            for code, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                badge = {"el": "🇬🇷", "en": "🇬🇧"}.get(code, "🌐")
                st.markdown(f"- {badge} `{code}`: **{count}** articles")

            st.markdown("---")
            st.markdown("**📂 By category:**")
            cat_counts: Dict[str, int] = {}
            for a in blog:
                cat = a.get("category", "—")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                st.markdown(f"- {cat}: **{count}** articles")
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    render_admin_tab()
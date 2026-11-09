import streamlit as st
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from collections import defaultdict
import uuid

from utils.prompts import BLOG_CATEGORIES
from utils.article_generator import (
    INGESTION_MODE_RSS,
    INGESTION_MODE_RESTRICTED,
    INGESTION_MODE_MANUAL,
    INGESTION_MODE_CUSTOM,
    INGESTION_MODES,
)
from utils.sources import list_companies, get_company


# ============================================
# ΣΤΑΘΕΡΕΣ
# ============================================
DRAFTS_FILE = "drafts.json"
BLOG_FILE = "blog_data.json"
WATCHLIST_FILE = "watchlist_queue.json"
MAX_DRAFTS_IN_HISTORY = 30

DEEP_RESEARCH_MAX_CANDIDATES = 10

TRANSLATION_MODEL = "gpt-4o-mini"
TRANSLATION_MAX_TOKENS = 500

LANGUAGE_CHOICES: Dict[str, str] = {
    "🇬🇷 Greek": "Greek",
    "🇬🇧 English": "English",
    "🌐 Both (Greek + English)": "Both",
}

CATEGORY_NAMES: List[str] = list(BLOG_CATEGORIES.keys())


# ============================================
# ΦΙΛΤΡΑ DEEP RESEARCH
# ============================================
URL_BLACKLIST = [
    "/pricing", "/privacy", "/terms", "/legal", "/docs/", "/support/",
    "/careers", "/contact", "/about", "/login", "/signup", "/security",
    "/trust", "/cookie", "/gdpr", "/tos",
]

URL_WHITELIST = [
    "/news", "/blog", "/research", "/index", "/articles", "/posts",
    "/insights", "/updates", "/announcements",
]

GENERIC_TITLES = {
    "pricing", "privacy", "terms", "contact", "about", "login", "signup",
    "sign in", "sign up", "home", "homepage", "docs", "documentation",
    "support", "careers", "legal", "security", "cookie", "cookie policy",
    "privacy policy", "terms of service", "terms of use", "untitled",
    "(untitled)", "no title",
}

DEFAULT_STATE = {
    "content_provider": "jina",
    "last_gen": None,
    "pending_feed_item_url": None,
    "pending_company_key": None,
    "pending_target_point": None,
    "pending_source_title": None,
    "pending_source_date": None,  # <--- ΝΕΟ: Ημερομηνία πηγής
    "research_results": None,
    "research_query": None,
    "research_company_key": None,
    "translations_cache": {},
}


# ============================================
# ΑΠΟΘΗΚΕΥΣΗ JSON
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


def load_watchlist() -> List[Dict[str, Any]]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except json.JSONDecodeError:
        return []
    except Exception as e:
        st.error(f"Error loading watchlist: {str(e)}")
        return []


def load_watchlist_for_company(company_key: str) -> List[Dict[str, Any]]:
    return [i for i in load_watchlist() if i.get("company_key") == company_key]


def delete_watchlist_item(url: str) -> bool:
    if not os.path.exists(WATCHLIST_FILE):
        return False
    try:
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            return False

        original_len = len(items)
        filtered = [i for i in items if i.get("url") != url]

        if len(filtered) == original_len:
            return False

        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)

        cache = st.session_state.get("translations_cache", {})
        keys_to_delete = [k for k in cache if k.startswith(f"{url}|")]
        for k in keys_to_delete:
            del cache[k]
        st.session_state["translations_cache"] = cache

        return True
    except Exception as e:
        st.error(f"Σφάλμα διαγραφής: {e}")
        return False


# ============================================
# ΜΕΤΑΦΡΑΣΗ
# ============================================

def _get_openai_client():
    if "openai_client" in st.session_state:
        return st.session_state["openai_client"]
    try:
        from openai import OpenAI
        api_key = st.secrets.get("OPENAI_API_KEY")
        if not api_key:
            return None
        client = OpenAI(api_key=api_key)
        st.session_state["openai_client"] = client
        return client
    except Exception:
        return None


def _translate_text(text: str, target_lang: str = "Greek") -> Optional[str]:
    if not text or not text.strip():
        return ""
    client = _get_openai_client()
    if client is None:
        return None
    prompt = (
        f"Translate the following text to {target_lang}. "
        f"Return ONLY the translation, no explanations, no quotes:\n\n{text}"
    )
    try:
        response = client.chat.completions.create(
            model=TRANSLATION_MODEL,
            max_completion_tokens=TRANSLATION_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        return content.strip() if content else None
    except Exception as e:
        st.warning(f"⚠️ Σφάλμα μετάφρασης: {e}")
        return None


def _get_or_create_translation(
    url: str, title: str, snippet: str, target_lang: str = "Greek",
) -> Optional[Dict[str, str]]:
    cache = st.session_state.get("translations_cache", {})
    cache_key = f"{url}|{target_lang}"
    if cache_key in cache:
        return cache[cache_key]

    translated_title = _translate_text(title, target_lang) or title
    translated_snippet = _translate_text(snippet, target_lang) if snippet else ""

    result = {"title": translated_title, "snippet": translated_snippet}
    cache[cache_key] = result
    st.session_state["translations_cache"] = cache
    return result


# ============================================
# ΦΙΛΤΡΑ DEEP RESEARCH
# ============================================

def _is_article_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()

    for blocked in URL_BLACKLIST:
        if blocked in path:
            return False
    for allowed in URL_WHITELIST:
        if allowed in path:
            return True

    stripped = path.rstrip("/")
    if stripped in ("", "/en", "/el", "/gr"):
        return True

    segments = [s for s in path.split("/") if s]
    if segments:
        last = segments[-1]
        if len(last) >= 15 and "-" in last:
            return True
    return False


def _is_valid_article_title(title: str) -> bool:
    if not title or not title.strip():
        return False
    normalized = title.strip().lower()
    if normalized in GENERIC_TITLES:
        return False
    words = [w for w in normalized.split() if w.strip()]
    if len(words) < 3:
        return False
    return True


def _filter_research_results(
    results: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], int]:
    if not results:
        return [], 0
    filtered: List[Dict[str, str]] = []
    rejected = 0
    for r in results:
        url = r.get("url") or ""
        title = r.get("title") or ""
        if not _is_article_url(url):
            rejected += 1
            continue
        if not _is_valid_article_title(title):
            rejected += 1
            continue
        filtered.append(r)
    return filtered, rejected


# ============================================
# DRAFT OBJECT
# ============================================

def create_draft_object(
    article_data: Dict, teasers_data: Dict, target_point: str,
    category: str, category_slug: str, language: str,
    translation_id: Optional[str], sources: List[Dict[str, str]],
    company_key: str,
) -> Dict:
    return {
        "id": str(uuid.uuid4()),
        "title": article_data.get("title", "Untitled"),
        "slug": article_data.get("slug", ""),
        "content": article_data.get("content_markdown", ""),
        "meta_description": article_data.get("meta_description", ""),
        "reading_time_minutes": article_data.get("reading_time_minutes", 0),
        "category": category,
        "category_slug": category_slug,
        "company_key": company_key,
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
        "sources": sources,
        "target_point": target_point,
        "status": "draft",
        "word_count": article_data.get("word_count", 0),
        "created_at": datetime.now().isoformat(),
    }


# ============================================
# ΚΥΚΛΟΣ ΖΩΗΣ DRAFT
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
    bundles: List[Dict[str, Any]], target_point: str, category: str,
    category_slug: str, company_key: str,
) -> bool:
    drafts = load_drafts()
    new_drafts = [
        create_draft_object(
            article_data=b["article"], teasers_data=b["teasers"],
            target_point=target_point, category=category,
            category_slug=category_slug, language=b["language"],
            translation_id=b["translation_id"],
            sources=b.get("sources") or [],
            company_key=b.get("company_key") or company_key,
        )
        for b in bundles
    ]
    combined = drafts + new_drafts
    if len(combined) > MAX_DRAFTS_IN_HISTORY:
        combined = combined[-MAX_DRAFTS_IN_HISTORY:]
    return save_drafts(combined)


def publish_bundles(
    bundles: List[Dict[str, Any]], target_point: str, category: str,
    category_slug: str, company_key: str,
) -> bool:
    blog = load_blog()
    for b in bundles:
        draft = create_draft_object(
            article_data=b["article"], teasers_data=b["teasers"],
            target_point=target_point, category=category,
            category_slug=category_slug, language=b["language"],
            translation_id=b["translation_id"],
            sources=b.get("sources") or [],
            company_key=b.get("company_key") or company_key,
        )
        draft["status"] = "published"
        draft["published_at"] = datetime.now().isoformat()
        blog.append(draft)
    return save_blog(blog)


# ============================================
# DEEP RESEARCH
# ============================================

def _deep_research(provider, query: str, site: str) -> Tuple[List[Dict[str, str]], int]:
    if not query or not query.strip():
        return [], 0

    results_by_url: Dict[str, Dict[str, str]] = {}

    exact_query = f'"{query}"'
    try:
        merged_a = provider.search_and_extract(
            exact_query, max_results=10, site=site,
            max_sources=DEEP_RESEARCH_MAX_CANDIDATES,
        )
        if merged_a and merged_a.get("sources"):
            for s in merged_a["sources"]:
                url = s.get("url")
                if url and url not in results_by_url:
                    results_by_url[url] = s
    except Exception as exc:
        st.warning(f"⚠️ Exact-match query απέτυχε: {exc}")

    try:
        merged_b = provider.search_and_extract(
            query, max_results=10, site=site,
            max_sources=DEEP_RESEARCH_MAX_CANDIDATES,
        )
        if merged_b and merged_b.get("sources"):
            for s in merged_b["sources"]:
                url = s.get("url")
                if url and url not in results_by_url:
                    results_by_url[url] = s
    except Exception as exc:
        st.warning(f"⚠️ Loose query απέτυχε: {exc}")

    raw_results = list(results_by_url.values())
    filtered, rejected = _filter_research_results(raw_results)
    return filtered[:DEEP_RESEARCH_MAX_CANDIDATES], rejected


# ============================================
# HELPERS RENDERING
# ============================================

def _set_pending_generation(
    url: str, company_key: str, target_point: str, title: str, source_date: Optional[str] = None
) -> None:
    st.session_state["pending_feed_item_url"] = url
    st.session_state["pending_company_key"] = company_key
    st.session_state["pending_target_point"] = target_point
    st.session_state["pending_source_title"] = title
    st.session_state["pending_source_date"] = source_date  # <--- ΝΕΟ


def _render_news_card(
    item: Dict[str, Any],
    *,
    target_point: str,
    company_key: Optional[str] = None,
    button_key_prefix: str = "gen",
    show_delete: bool = False,
) -> None:
    company_name = (
        item.get("company_name")
        or item.get("company_key", "")
        or company_key
        or "—"
    )
    
    # Παίρνουμε την ημερομηνία (είτε από το RSS, είτε από το Deep Research αν υπάρχει)
    published_raw = item.get("published_at") or item.get("published") or ""
    published = str(published_raw)[:10] if published_raw else "—"
    
    title = item.get("title") or "(χωρίς τίτλο)"
    url = item.get("url") or ""

    snippet = (
        item.get("snippet")
        or item.get("summary")
        or item.get("description")
        or ""
    ).strip()

    cache = st.session_state.get("translations_cache", {})
    cache_key = f"{url}|Greek"
    translated = cache.get(cache_key)

    with st.container(border=True):
        if translated:
            st.markdown(f"### 🇬🇷 {translated.get('title', title)}")
        else:
            st.markdown(f"### {title}")

        st.caption(f"{company_name} | {published}")

        if translated:
            st.caption(f"🇬🇧 *{title}*")

        if snippet:
            if translated and translated.get("snippet"):
                st.write(translated["snippet"])
                st.caption(f"🇬🇧 *{snippet}*")
            else:
                st.write(snippet)

        if show_delete:
            col1, col2, col3 = st.columns([1, 1, 1])
        else:
            col1, col2, col3 = st.columns([1, 1, 2])

        with col1:
            if translated:
                if st.button("🔄 Επαναφορά", key=f"untr_{button_key_prefix}_{url}"):
                    cache.pop(cache_key, None)
                    st.session_state["translations_cache"] = cache
                    st.rerun()
            else:
                if st.button("🌐 Μετάφραση", key=f"tr_{button_key_prefix}_{url}"):
                    with st.spinner("🌐 Μετάφραση..."):
                        _get_or_create_translation(url, title, snippet, "Greek")
                    st.rerun()

        with col2:
            if st.button("🚀 Generate", key=f"{button_key_prefix}_{url}"):
                _set_pending_generation(
                    url=url,
                    company_key=item.get("company_key") or company_key or "",
                    target_point=target_point or title,
                    title=title,
                    source_date=published if published != "—" else None,
                )
                st.success("✅ Έτοιμο! Πήγαινε στην καρτέλα **📝 Generate Article**.")

        if show_delete:
            with col3:
                if st.button("🗑️ Διαγραφή", key=f"del_{button_key_prefix}_{url}", help="Διαγραφή από το queue"):
                    if delete_watchlist_item(url):
                        st.success("✅ Διαγράφηκε")
                        st.rerun()
                    else:
                        st.error("❌ Αποτυχία διαγραφής")

        if url:
            st.markdown(f"[🔗 Open Original]({url})")


def _render_article_preview(bundle: Dict[str, Any], category: str) -> None:
    a = bundle["article"]
    with st.container(border=True):
        st.markdown(f"### 📄 Άρθρο — {bundle['language_name']} ({bundle['language']})")
        if bundle.get("translation_id"):
            st.caption(f"🔗 translation_id: `{bundle['translation_id']}`")
        st.markdown(f"**Τίτλος:** {a.get('title', '—')}")
        if a.get("slug"):
            st.markdown(f"**Slug:** `{a['slug']}`")
        if a.get("meta_description"):
            st.markdown(f"**Meta description:** {a['meta_description']}")
        st.markdown(f"**Κατηγορία:** {category}")
        st.markdown(
            f"**Λέξεις:** {a.get('word_count', 0)} "
            f"| **Χρόνος ανάγνωσης:** {a.get('reading_time_minutes', 0)} λεπτά"
        )
        kws = a.get("keywords") or []
        st.markdown(f"**Λέξεις-κλειδιά:** {', '.join(kws) if kws else '—'}")

        # Εμφάνιση Flags από το backend (v4.4)
        flags = bundle.get("flags") or []
        for flag in flags:
            # Το backend τα έχει ήδη τυπώσει με st.warning/error, 
            # αλλά τα δείχνουμε ξανά εδώ συγκεντρωμένα για ευκολία.
            pass

        used_sources = bundle.get("sources") or []
        if used_sources:
            st.markdown("**Πρωτογενής πηγή:**")
            for s in used_sources:
                title = s.get("title", "") or s.get("url", "")
                url = s.get("url", "")
                st.markdown(f"- [{title}]({url})")

        st.markdown("---")
        st.markdown(a.get("content_markdown", ""))


def _render_teasers(bundle: Dict[str, Any]) -> None:
    teasers = bundle["teasers"]
    lang_code = bundle["language"]
    with st.container(border=True):
        st.markdown("### 📱 Teasers Κοινωνικών Δικτύων")
        for key, label, limit in (
            ("twitter", "🐦 Twitter/X", 280),
            ("linkedin", "💼 LinkedIn", 300),
            ("facebook", "📘 Facebook", 150),
        ):
            text = (teasers.get(key) or {}).get("text", "")
            st.markdown("<div class='teaser-box'>", unsafe_allow_html=True)
            st.markdown(f"<div class='teaser-platform'>{label}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='teaser-text'>{text}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='char-count'>{len(text)} / {limit} χαρακτήρες</div>", unsafe_allow_html=True)
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("📋 Copy", key=f"copy_{key}_{lang_code}"):
                    st.code(text)
            st.markdown("</div>", unsafe_allow_html=True)


def _render_cleaner_debug(cleaner_output: Dict[str, Any]) -> None:
    with st.expander("🔧 Cleaner output (debug)", expanded=False):
        if cleaner_output.get("_fallback"):
            st.warning("⚠️ Cleaner απέτυχε — fallback στο raw content.")
        st.markdown(f"**Σύνοψη θέματος:** {cleaner_output.get('topic_summary') or '—'}")
        st.markdown(f"**Ημερομηνία Πηγής:** {cleaner_output.get('source_date') or 'Άγνωστη'}")
        st.markdown("**Βασικά facts:**")
        facts = cleaner_output.get("key_facts") or []
        if facts:
            for f in facts:
                st.markdown(f"- {f}")
        else:
            st.markdown("_(κανένα)_")
        st.markdown("**Cleaned content (πρώτοι 800 χαρακτήρες):**")
        st.code((cleaner_output.get("cleaned_content") or "")[:800])


def _render_bundle(bundle: Dict[str, Any], category: str) -> None:
    _render_article_preview(bundle, category)
    _render_teasers(bundle)


# ============================================
# ΚΥΡΙΩΣ RENDER
# ============================================

def render_admin_tab() -> None:
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            if isinstance(value, (dict, list)):
                st.session_state[key] = value.copy()
            else:
                st.session_state[key] = value

    admin_tabs = st.tabs(
        [
            "📥 Inbox & Research",
            "📝 Generate Article",
            "📚 Drafts History",
            "📊 Analytics",
        ]
    )

    # ============================================================
    # ΚΑΡΤΕΛΑ 1: INBOX & RESEARCH
    # ============================================================
    with admin_tabs[0]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📥 Inbox & Research</h2>", unsafe_allow_html=True)

        st.markdown("### 📰 Fresh News (ανά εταιρία)")
        watchlist = load_watchlist()
        watchlist.sort(key=lambda i: i.get("published_at") or "", reverse=True)

        if not watchlist:
            st.info("📭 Δεν υπάρχουν φρέσκα νέα. Τρέξε `python scripts/poll_feeds.py`.")
        else:
            by_company: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for item in watchlist:
                ck = item.get("company_key") or "unknown"
                by_company[ck].append(item)

            company_map = {c.key: c.display_name for c in list_companies()}
            sorted_company_keys = sorted(by_company.keys(), key=lambda k: company_map.get(k, k).lower())

            st.markdown(f"**Σύνολο: {len(watchlist)} items από {len(by_company)} εταιρίες**")
            st.caption("💡 Κάθε εταιρία σε δικό της expander. Πάτα 🗑️ για να διαγράψεις.")

            for ck in sorted_company_keys:
                items = by_company[ck]
                company_name = company_map.get(ck, ck)
                with st.expander(f"🏢 {company_name} — {len(items)} items", expanded=False):
                    for item in items:
                        _render_news_card(
                            item,
                            target_point=item.get("title") or "",
                            button_key_prefix=f"rss_{ck}",
                            show_delete=True,
                        )

        st.markdown("---")

        st.markdown("### 🔍 Deep Research (Επίσημες Ιστοσελίδες)")
        companies = list_companies()
        company_map_dr = {c.key: c.display_name for c in companies}

        col1, col2 = st.columns([2, 3])
        with col1:
            research_company_key = st.selectbox("Εταιρία", options=list(company_map_dr.keys()), format_func=lambda k: company_map_dr[k], key="research_company_select")
        with col2:
            research_query = st.text_input("Λέξη-κλειδί αναζήτησης", placeholder="π.χ. V3 release", key="research_query_input")

        search_clicked = st.button("🔎 Search Official Site")
        if search_clicked:
            if not research_query or not research_query.strip():
                st.error("❌ Γράψε μια λέξη-κλειδί.")
            else:
                try:
                    company = get_company(research_company_key)
                    primary = company.primary_domain
                    if not primary:
                        st.error(f"❌ Η {company.display_name} δεν έχει domain.")
                    else:
                        provider_name = st.session_state.get("content_provider", "jina")
                        from utils.providers import get_provider
                        provider = get_provider(name=provider_name)

                        with st.spinner("🔍 Βαθιά αναζήτηση..."):
                            candidates, rejected = _deep_research(provider, research_query, primary)

                        if not candidates:
                            st.warning(f"⚠️ Δεν βρέθηκαν αποτελέσματα (απορρίφθηκαν {rejected}).")
                            st.session_state["research_results"] = None
                        else:
                            st.session_state["research_results"] = candidates
                            st.session_state["research_query"] = research_query
                            st.session_state["research_company_key"] = research_company_key
                except Exception as e:
                    st.error(f"❌ Σφάλμα: {e}")

        research_results = st.session_state.get("research_results")
        research_company_key_stored = st.session_state.get("research_company_key")
        research_query_stored = st.session_state.get("research_query")

        if research_results:
            st.markdown(f"**Βρέθηκαν {len(research_results)} candidates:**")
            for src in research_results:
                _render_news_card(
                    {
                        "title": src.get("title") or src.get("url"),
                        "url": src.get("url"),
                        "snippet": src.get("snippet", ""),
                        "company_key": research_company_key_stored,
                        "company_name": company_map_dr.get(research_company_key_stored or "", ""),
                    },
                    target_point=research_query_stored or "",
                    company_key=research_company_key_stored,
                    button_key_prefix="research",
                    show_delete=False,
                )
        st.markdown("</div>", unsafe_allow_html=True)

    # ============================================================
    # ΚΑΡΤΕΛΑ 2: GENERATE ARTICLE
    # ============================================================
    with admin_tabs[1]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📝 Δημιουργία Νέου Άρθρου</h2>", unsafe_allow_html=True)

        pending_url = st.session_state.get("pending_feed_item_url")
        pending_company = st.session_state.get("pending_company_key")
        pending_topic = st.session_state.get("pending_target_point")
        pending_title = st.session_state.get("pending_source_title")
        pending_source_date = st.session_state.get("pending_source_date")

        if pending_url:
            st.info(
                f"📥 Προ-συμπληρωμένο από Inbox/Research:\n"
                f"- **Πηγή:** {pending_title or pending_url}\n"
                f"- **URL:** {pending_url}\n"
                f"- **Εταιρία:** {pending_company or '—'}\n"
                f"- **Ημερομηνία:** {pending_source_date or '—'}"
            )

        col1, col2 = st.columns(2)
        with col1:
            category = st.selectbox("Κατηγορία *", options=CATEGORY_NAMES)
        with col2:
            language_label = st.selectbox("Γλώσσα *", options=list(LANGUAGE_CHOICES.keys()), index=0)
            language_value = LANGUAGE_CHOICES[language_label]

        default_mode_idx = 1
        if pending_url:
            default_mode_idx = 2

        ingestion_mode = st.radio(
            "Ingestion Mode *",
            options=INGESTION_MODES,
            index=default_mode_idx,
            horizontal=True,
        )

        company_key = ""
        custom_idea: Optional[str] = None
        feed_item_url: Optional[str] = None
        target_point = ""

        if ingestion_mode == INGESTION_MODE_CUSTOM:
            st.info("💡 **Custom Idea mode:**")
            custom_idea = st.text_area("Ιδέα *", height=200)
            first_line = (custom_idea or "").strip().split("\n")[0].strip()
            target_point = first_line[:120] if first_line else ""
        else:
            companies = list_companies()
            company_map = {c.key: c.display_name for c in companies}
            company_keys = list(company_map.keys())
            default_company_idx = 0
            if pending_company and pending_company in company_keys:
                default_company_idx = company_keys.index(pending_company)

            company_key = st.selectbox("Εταιρία *", options=company_keys, index=default_company_idx, format_func=lambda k: company_map[k])

            try:
                company = get_company(company_key)
            except Exception:
                st.stop()

            provider_choice = st.radio("Content Provider", options=["jina", "tavily"], index=0, horizontal=True)
            st.session_state["content_provider"] = provider_choice

            if ingestion_mode == INGESTION_MODE_RSS:
                if not company.has_rss:
                    st.warning(f"⚠️ Η {company.display_name} δεν έχει RSS feed.")
                else:
                    items = load_watchlist_for_company(company_key)
                    if not items:
                        st.info(f"📭 Δεν υπάρχουν items.")
                    else:
                        idx = st.selectbox(f"Feed item *", options=range(len(items)), format_func=lambda i: f"{items[i].get('title')} ({items[i].get('published_at') or '—'})")
                        feed_item_url = items[idx].get("url")
                        st.caption(f"🔗 {feed_item_url}")

                target_point = st.text_input("Θέμα *", value=pending_topic or "")

            elif ingestion_mode == INGESTION_MODE_MANUAL:
                feed_item_url = st.text_input("URL *", value=pending_url or "")
                target_point = st.text_input("Θέμα *", value=pending_topic or "")

            elif ingestion_mode == INGESTION_MODE_RESTRICTED:
                target_point = st.text_input("Θέμα *", value=pending_topic or "")

        st.markdown("</div>", unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            generate_btn = st.button("🚀 Generate Article", use_container_width=True)

        if generate_btn:
            missing: List[str] = []
            if not category: missing.append("Κατηγορία")
            if ingestion_mode == INGESTION_MODE_CUSTOM:
                if not custom_idea or not custom_idea.strip(): missing.append("Custom Idea")
            else:
                if not target_point.strip(): missing.append("Θέμα")
                if ingestion_mode in (INGESTION_MODE_RSS, INGESTION_MODE_MANUAL) and not feed_item_url:
                    missing.append("URL / Feed item")

            if missing:
                st.error(f"❌ Λείπουν: {', '.join(missing)}")
            else:
                try:
                    from utils.article_generator import ArticleGenerator
                    generator = ArticleGenerator()
                    
                    # Περνάμε το source_date στο pipeline
                    output = generator.full_pipeline(
                        target_point=target_point,
                        category=category,
                        company_key=company_key,
                        ingestion_mode=ingestion_mode,
                        feed_item_url=feed_item_url,
                        language_selection=language_value,
                        custom_idea=custom_idea,
                        source_date=pending_source_date,
                    )

                    st.session_state["last_gen"] = {
                        "cleaner": output.get("cleaner", {}),
                        "bundles": output.get("bundles", []),
                        "sources": output.get("sources", []),
                        "company": output.get("company", {}),
                        "category": category,
                        "category_slug": output.get("category_slug", ""),
                        "target_point": target_point,
                        "provider": st.session_state.get("content_provider", "jina"),
                        "saved": False,
                        "published": False,
                    }

                    # Καθαρισμός
                    st.session_state["pending_feed_item_url"] = None
                    st.session_state["pending_company_key"] = None
                    st.session_state["pending_target_point"] = None
                    st.session_state["pending_source_title"] = None
                    st.session_state["pending_source_date"] = None

                except Exception as e:
                    st.error(f"❌ Σφάλμα: {e}")

        # Display Last Generation
        gen = st.session_state.get("last_gen")
        if gen and gen.get("bundles"):
            bundles = gen["bundles"]
            category_v = gen["category"]
            category_slug = gen["category_slug"]
            target_point_v = gen["target_point"]
            company_key_v = (gen.get("company") or {}).get("key") or company_key

            st.success(f"✅ Δημιουργήθηκαν {len(bundles)} bundle(s) μέσω **{gen.get('provider')}**")
            _render_cleaner_debug(gen["cleaner"])

            if len(bundles) == 1:
                _render_bundle(bundles[0], category_v)
            else:
                flag = {"el": "🇬🇷", "en": "🇬🇧"}
                tabs = st.tabs([f"{flag.get(b['language'], '🌐')} {b['language_name']}" for b in bundles])
                for tab, bundle in zip(tabs, bundles):
                    with tab:
                        _render_bundle(bundle, category_v)

            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 Αποθήκευση ως Draft", use_container_width=True, disabled=gen.get("saved") or gen.get("published")):
                    if save_bundles_as_drafts(bundles, target_point_v, category_v, category_slug, company_key_v):
                        gen["saved"] = True
                        st.success(f"✅ Αποθηκεύτηκαν {len(bundles)} draft(s).")
                    else:
                        st.error("❌ Αποτυχία αποθήκευσης draft(s)")
            with col2:
                if st.button("🚀 Άμεση Δημοσίευση", use_container_width=True, disabled=gen.get("published")):
                    if publish_bundles(bundles, target_point_v, category_v, category_slug, company_key_v):
                        gen["published"] = True
                        st.success(f"✅ Δημοσιεύτηκαν {len(bundles)} άρθρα!")
                        st.balloons()
                    else:
                        st.error("❌ Αποτυχία δημοσίευσης")

            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🗑️ Καθαρισμός Αποτελέσματος", use_container_width=True):
                    st.session_state["last_gen"] = None
                    st.rerun()

    # ============================================================
    # ΚΑΡΤΕΛΑ 3: DRAFTS HISTORY
    # ============================================================
    with admin_tabs[2]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📚 Ιστορικό Drafts</h2>", unsafe_allow_html=True)

        drafts = load_drafts()
        if not drafts:
            st.info("📭 Δεν υπάρχουν drafts ακόμα.")
        else:
            st.markdown(f"**Σύνολο Drafts:** {len(drafts)} (Μέγιστο {MAX_DRAFTS_IN_HISTORY})")
            st.markdown("---")
            for draft in reversed(drafts):
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"<div class='draft-title'>{draft['title']}</div>", unsafe_allow_html=True)
                        lang_badge = {"el": "🇬🇷", "en": "🇬🇧"}.get(draft.get("language", ""), "🌐")
                        st.markdown(
                            f"📅 {draft['date']} | 📂 {draft['category']} "
                            f"| 🏢 {draft.get('company_key', '—')} "
                            f"| 📝 {draft['word_count']} λέξεις "
                            f"| {lang_badge} {draft.get('language','—')}",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"🎯 Θέμα: {draft['target_point']}")
                        if draft.get("translation_id"):
                            st.caption(f"🔗 translation_id: `{draft['translation_id']}`")
                    with col2:
                        st.markdown("<span class='status-badge status-draft'>DRAFT</span>", unsafe_allow_html=True)
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("👁️ Προεπισκόπηση", key=f"pv_{draft['id']}"):
                            st.markdown(draft["content"][:300] + "...")
                    with c2:
                        if st.button("🚀 Δημοσίευση", key=f"pub_{draft['id']}"):
                            if publish_draft(draft):
                                st.success("✅ Δημοσιεύτηκε!")
                                st.rerun()
                    with c3:
                        if st.button("🗑️ Διαγραφή", key=f"del_{draft['id']}"):
                            if delete_draft(draft["id"]):
                                st.success("✅ Διαγράφηκε!")
                                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # ============================================================
    # ΚΑΡΤΕΛΑ 4: ANALYTICS
    # ============================================================
    with admin_tabs[3]:
        st.markdown("<div class='admin-section'>", unsafe_allow_html=True)
        st.markdown("<h2>📊 Στατιστικά</h2>", unsafe_allow_html=True)
        drafts = load_drafts()
        blog = load_blog()

        c1, c2, c3 = st.columns(3)
        c1.metric("📚 Δημοσιευμένα", len(blog))
        c2.metric("📝 Drafts", len(drafts))
        c3.metric("📊 Σύνολο", len(blog) + len(drafts))

        if blog:
            st.markdown("---")
            st.markdown("**🌐 Ανά γλώσσα:**")
            lang_counts: Dict[str, int] = {}
            for a in blog:
                code = a.get("language", "—")
                lang_counts[code] = lang_counts.get(code, 0) + 1
            for code, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                badge = {"el": "🇬🇷", "en": "🇬🇧"}.get(code, "🌐")
                st.markdown(f"- {badge} `{code}`: **{count}** άρθρα")

            st.markdown("---")
            st.markdown("**📂 Ανά κατηγορία:**")
            cat_counts: Dict[str, int] = {}
            for a in blog:
                cat = a.get("category", "—")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                st.markdown(f"- {cat}: **{count}** άρθρα")
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    render_admin_tab()
"""
Pipeline δημιουργίας άρθρου για το does4u admin panel (v4.0, D-020).

PRIMARY-SOURCE-ONLY pipeline:
    Fetch (ακριβώς 1 πρωτογενής πηγή)
        -> Cleaner (καθαρισμός περιεχομένου)
        -> Writer (Sol — φυσικό ελληνικό ύφος + inline citations)
        -> Teasers (Sol, fallback σε 4o-mini)
        -> ## Sources section (programmatic append)

Ingestion modes:
    - "RSS (today's items)"  : item από watchlist_queue.json.
    - "Restricted Search"    : SERP περιορισμένο στο domain της εταιρίας.
    - "Manual URL"           : URL που δίνει ο χρήστης.
    - "Custom Idea"          : Η ιδέα του CEO (χωρίς εξωτερική πηγή).
"""
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import streamlit as st
from openai import OpenAI

from utils.prompts import (
    BLOG_CATEGORIES,
    CITATION_INSTRUCTIONS,
    CLEANER_PROMPT,
)

logger = logging.getLogger(__name__)


# ============================================
# ΓΛΩΣΣΕΣ & MODES
# ============================================
LANGUAGE_OPTIONS: Dict[str, Dict[str, str]] = {
    "greek": {"name": "Greek", "native": "Ελληνικά", "code": "el"},
    "english": {"name": "English", "native": "English", "code": "en"},
}

INGESTION_MODE_RSS = "RSS (today's items)"
INGESTION_MODE_RESTRICTED = "Restricted Search"
INGESTION_MODE_MANUAL = "Manual URL"
INGESTION_MODE_CUSTOM = "Custom Idea (Growth Hack)"
INGESTION_MODES = [
    INGESTION_MODE_RSS,
    INGESTION_MODE_RESTRICTED,
    INGESTION_MODE_MANUAL,
    INGESTION_MODE_CUSTOM,
]

# ============================================
# ΜΟΝΤΕΛΑ
# ============================================
CLEANER_MODEL = "gpt-5.6-luna"
WRITER_MODEL = "gpt-5.6-sol"
TEASER_MODEL = "gpt-5.6-luna"
TEASER_FALLBACK_MODEL = "gpt-4o-mini"

CLEANER_MAX_TOKENS = 4000
WRITER_MAX_TOKENS = 8000
TEASER_MAX_TOKENS = 8000
TEASER_FALLBACK_MAX_TOKENS = 1000

EMPTY_RESPONSE_RETRY_MULTIPLIER = 2

MAX_RAW_CONTENT_CHARS = 12000
MAX_CLEANED_CONTENT_CHARS = 6000
FALLBACK_RAW_CONTENT_CHARS = 4000


# ============================================
# MODULE HELPERS
# ============================================
def generate_fallback_teasers(article_text: str) -> Dict[str, Dict[str, Any]]:
    """Fallback teasers από τις πρώτες προτάσεις."""
    sentences = [s.strip() for s in article_text.split(".") if s.strip()]
    first = ". ".join(sentences[:2]) + "." if sentences else ""
    if not first:
        first = "Read our latest article."
    return {
        "twitter": {"text": first[:280], "length": 280},
        "linkedin": {"text": first[:300], "length": 300},
        "facebook": {"text": first[:150], "length": 150},
    }


def append_sources_section(
    article_markdown: str, sources: List[Dict[str, str]]
) -> str:
    """Προσάρτηση ## Sources section, αντικαθιστώντας τυχόν υπάρχον."""
    if "## Sources" in article_markdown:
        idx = article_markdown.find("## Sources")
        article_markdown = article_markdown[:idx].rstrip()

    if not sources:
        return article_markdown

    lines: List[str] = ["## Sources"]
    for s in sources:
        title = s.get("title") or s.get("url", "Source")
        url = s.get("url", "")
        if not url:
            continue
        lines.append(f"- [{title}]({url})")

    if len(lines) == 1:
        return article_markdown

    return article_markdown.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def check_hallucinations(article_text: str, source_text: str) -> None:
    """Έλεγχος για αριθμούς στο άρθρο που δεν υπάρχουν στην πηγή.

    Σκανάρει το τελικό κείμενο για αριθμούς (π.χ. 2026, 45%, 1.5) και
    εμφανίζει warning στο Streamlit αν δεν βρεθούν στο source_text.
    """
    # Regex για ακέραιους, δεκαδικούς και ποσοστά (π.χ. 1,000 ή 45.5%)
    pattern = r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\b'
    article_numbers = set(re.findall(pattern, article_text))
    source_numbers = set(re.findall(pattern, source_text))

    def clean_num(n: str) -> str:
        # Αφαιρούμε κόμμα χιλιάδων και περιττά μηδενικά
        return n.replace(',', '').replace('.0', '')

    clean_article = {clean_num(n) for n in article_numbers}
    clean_source = {clean_num(n) for n in source_numbers}

    # Αγνοούμε πολύ μικρούς αριθμούς (π.χ. 1, 2, 3) για να μην έχουμε false positives
    missing_numbers = set()
    for num in clean_article - clean_source:
        try:
            val = float(num.replace('%', ''))
            if val > 10:
                missing_numbers.add(num)
        except ValueError:
            continue

    for num in missing_numbers:
        st.warning(f"⚠️ Προσοχή: Ο αριθμός {num} δεν βρέθηκε στην πηγή!")


# ============================================
# ΚΥΡΙΑ ΚΛΑΣΗ
# ============================================
class ArticleGenerator:
    """Pipeline δημιουργίας άρθρου (primary-source-only, v4.1)."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = st.secrets.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Streamlit secrets")
        self.client: OpenAI = OpenAI(api_key=self.api_key)

    @staticmethod
    def resolve_languages(selection: str) -> List[Dict[str, str]]:
        sel = (selection or "").strip().lower()
        if sel in ("both", "bilingual", "el+en", "gr+en"):
            return [LANGUAGE_OPTIONS["greek"], LANGUAGE_OPTIONS["english"]]
        if sel in ("greek", "gr", "el", "ελληνικά"):
            return [LANGUAGE_OPTIONS["greek"]]
        if sel in ("english", "en", "αγγλικά"):
            return [LANGUAGE_OPTIONS["english"]]
        logger.warning("Unknown language %r — default Greek", selection)
        return [LANGUAGE_OPTIONS["greek"]]

    @staticmethod
    def get_category_config(category: str) -> Dict[str, Any]:
        if category not in BLOG_CATEGORIES:
            raise ValueError(
                f"Unknown category {category!r}. "
                f"Valid: {list(BLOG_CATEGORIES.keys())}"
            )
        return BLOG_CATEGORIES[category]

    @staticmethod
    def _resolve_provider_name() -> Optional[str]:
        try:
            return st.session_state.get("content_provider")
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------
    def _call_llm(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        stage: str,
    ) -> Optional[str]:
        try:
            response = self.client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                retry_tokens = max_tokens * EMPTY_RESPONSE_RETRY_MULTIPLIER
                logger.warning(
                    "[%s] Empty response from %s — retry with %d tokens",
                    stage, model, retry_tokens,
                )
                response = self.client.chat.completions.create(
                    model=model,
                    max_completion_tokens=retry_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    logger.error("[%s] Empty response from %s after retry", stage, model)
                    return None
            return content
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] LLM call failed: %s", stage, exc)
            st.error(f"❌ [{stage}] LLM call failed: {exc}")
            return None

    def _call_llm_json(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        stage: str,
        max_retries: int = 1,
    ) -> Optional[Dict[str, Any]]:
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            raw = self._call_llm(
                model=model, prompt=prompt,
                max_tokens=max_tokens, stage=stage,
            )
            if raw is None:
                return None
            parsed = self._parse_json_response(raw, stage=stage)
            if parsed is not None:
                return parsed
            logger.warning("[%s] JSON parse failed (%d/%d)", stage, attempt, attempts)
        return None

    def _parse_json_response(
        self, response_text: str, *, stage: str = "unknown"
    ) -> Optional[Dict[str, Any]]:
        if not response_text:
            return None
        text = response_text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                logger.error("[%s] JSON decode error: %s", stage, exc)
        logger.error("[%s] No JSON object found in response", stage)
        return None

    # ------------------------------------------------------------------
    # Stage 1 — Cleaner
    # ------------------------------------------------------------------
    def clean_content(
        self, raw_content: str, target_keywords: str
    ) -> Optional[Dict[str, Any]]:
        if not raw_content or not raw_content.strip():
            logger.error("[Cleaner] Empty raw content")
            return None
        prompt = CLEANER_PROMPT.format(
            target_keywords=target_keywords or "(none)",
            raw_content=raw_content[:MAX_RAW_CONTENT_CHARS],
        )
        result = self._call_llm_json(
            model=CLEANER_MODEL, prompt=prompt,
            max_tokens=CLEANER_MAX_TOKENS, stage="Cleaner",
        )
        if not result or not result.get("cleaned_content"):
            logger.error("[Cleaner] Missing cleaned_content")
            return None
        facts = result.get("key_facts")
        result["key_facts"] = (
            [str(f) for f in facts if f] if isinstance(facts, list) else []
        )
        return result

    # ------------------------------------------------------------------
    # Stage 2 — Writer
    # ------------------------------------------------------------------
    def generate_article(
        self,
        cleaned_content: str,
        target_point: str,
        category: str,
        key_facts: Optional[List[str]] = None,
        language: str = "Greek",
        sources: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not cleaned_content or not cleaned_content.strip():
            logger.error("[Writer/%s] Empty cleaned content", language)
            return None

        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return None

        key_facts = key_facts or []
        key_facts_str = (
            "\n".join(f"- {f}" for f in key_facts) if key_facts else "- (none provided)"
        )

        sources = sources or []
        sources_str = self._format_sources_for_prompt(sources)
        citation_instructions = CITATION_INSTRUCTIONS.format(sources=sources_str)

        prompt = cfg["article_prompt"].format(
            target_point=target_point,
            category=category,
            language=language,
            cleaned_content=cleaned_content[:MAX_CLEANED_CONTENT_CHARS],
            key_facts=key_facts_str,
            citation_instructions=citation_instructions,
        )
        result = self._call_llm_json(
            model=WRITER_MODEL, prompt=prompt,
            max_tokens=WRITER_MAX_TOKENS,
            stage=f"Writer/{category}/{language}",
        )
        if not result:
            return None
        if not result.get("content_markdown"):
            logger.error("[Writer] Missing content_markdown")
            return None
        if not result.get("slug"):
            result["slug"] = self._fallback_slug(result.get("title", ""))
        return result

    # ------------------------------------------------------------------
    # Stage 3 — Teasers
    # ------------------------------------------------------------------
    def generate_social_teasers(
        self,
        title: str,
        category: str,
        keywords: List[str],
        language: str = "Greek",
        article_text: str = "",
    ) -> Dict[str, Dict[str, Any]]:
        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return generate_fallback_teasers(article_text)

        prompt = cfg["teaser_prompt"].format(
            title=title or "(untitled)",
            category=category,
            keywords=", ".join(keywords) if keywords else "(none)",
            language=language,
        )

        result = self._call_llm_json(
            model=TEASER_MODEL, prompt=prompt,
            max_tokens=TEASER_MAX_TOKENS,
            stage=f"Teasers/{category}/{language}",
        )
        if result and all(k in result for k in ("twitter", "linkedin", "facebook")):
            return result

        logger.warning(
            "[Teasers/%s/%s] Primary model failed, trying %s",
            category, language, TEASER_FALLBACK_MODEL,
        )
        result = self._call_llm_json(
            model=TEASER_FALLBACK_MODEL, prompt=prompt,
            max_tokens=TEASER_FALLBACK_MAX_TOKENS,
            stage=f"Teasers-fallback/{category}/{language}",
        )
        if result and all(k in result for k in ("twitter", "linkedin", "facebook")):
            return result

        return generate_fallback_teasers(article_text)

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def full_pipeline(
        self,
        target_point: str,
        category: str,
        company_key: str,
        ingestion_mode: str = INGESTION_MODE_RESTRICTED,
        feed_item_url: Optional[str] = None,
        language_selection: str = "Greek",
        custom_idea: Optional[str] = None,
    ) -> Dict[str, Any]:
        empty_result: Dict[str, Any] = {
            "cleaner": {},
            "sources": [],
            "company": {},
            "category_slug": "",
            "bundles": [],
        }

        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return empty_result
        empty_result["category_slug"] = cfg["slug"]

        if ingestion_mode == INGESTION_MODE_CUSTOM:
            if not custom_idea or not custom_idea.strip():
                st.error("❌ Custom Idea mode requires an idea description.")
                return empty_result
            logger.info("[Pipeline] Custom Idea mode — using %d chars", len(custom_idea))
            raw_content = custom_idea.strip()
            sources: List[Dict[str, str]] = []
            cleaner_output: Dict[str, Any] = {
                "cleaned_content": raw_content,
                "key_facts": [],
                "topic_summary": "(custom idea — no external source)",
                "_fallback": True,
            }
            empty_result["company"] = {"key": "does4u", "display_name": "Does4U", "domains": []}
            final_target_point = target_point
        else:
            try:
                from utils.sources import get_company
                company = get_company(company_key)
                empty_result["company"] = {
                    "key": company.key,
                    "display_name": company.display_name,
                    "domains": company.domains,
                }
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Unknown company: {exc}")
                return empty_result

            # Επιστρέφει πλέον 3 τιμές (προστέθηκε το final_target_point λόγω Source Gate)
            raw_content, sources, final_target_point = self._fetch_content(
                ingestion_mode=ingestion_mode,
                target_point=target_point,
                company_key=company_key,
                feed_item_url=feed_item_url,
            )
            if not raw_content:
                st.error("❌ No content could be fetched. Pipeline aborted.")
                return empty_result

            with st.spinner("🧹 Cleaning content..."):
                cleaner_output = self.clean_content(raw_content, final_target_point)

            if not cleaner_output:
                truncated = raw_content[:FALLBACK_RAW_CONTENT_CHARS]
                logger.warning("[Pipeline] Cleaner failed — fallback (%d chars)", len(truncated))
                st.warning(f"⚠️ Cleaner failed — fallback στο raw content ({FALLBACK_RAW_CONTENT_CHARS} chars).")
                cleaner_output = {
                    "cleaned_content": truncated,
                    "key_facts": [],
                    "topic_summary": "(fallback — cleaner unavailable)",
                    "_fallback": True,
                }

        targets = self.resolve_languages(language_selection)
        translation_id: Optional[str] = str(uuid.uuid4()) if len(targets) > 1 else None

        bundles: List[Dict[str, Any]] = []
        for target in targets:
            lang_name = target["name"]
            lang_code = target["code"]

            with st.spinner(f"✍️ Writing article ({target['native']})..."):
                article = self.generate_article(
                    cleaned_content=cleaner_output.get("cleaned_content", ""),
                    target_point=final_target_point,
                    category=category,
                    key_facts=cleaner_output.get("key_facts") or [],
                    language=lang_name,
                    sources=sources,
                )
            if not article:
                logger.error("[Pipeline] Writer failed for %s", lang_name)
                continue

            article["content_markdown"] = append_sources_section(
                article.get("content_markdown", ""),
                sources,
            )

            # Έλεγχος Παραπληροφόρησης (Hallucinations)
            check_hallucinations(article["content_markdown"], cleaner_output.get("cleaned_content", ""))

            with st.spinner(f"📱 Generating teasers ({target['native']})..."):
                teasers = self.generate_social_teasers(
                    title=article.get("title", ""),
                    category=category,
                    keywords=article.get("keywords") or [],
                    language=lang_name,
                    article_text=article.get("content_markdown", ""),
                )

            bundles.append(
                {
                    "language": lang_code,
                    "language_name": lang_name,
                    "translation_id": translation_id,
                    "article": article,
                    "teasers": teasers,
                    "sources": sources,
                    "company_key": empty_result["company"].get("key", company_key),
                }
            )

        return {
            "cleaner": cleaner_output,
            "sources": sources,
            "company": empty_result["company"],
            "category_slug": cfg["slug"],
            "bundles": bundles,
        }

    # ------------------------------------------------------------------
    # Fetch (1 πρωτογενής πηγή) — Με Source Gate
    # ------------------------------------------------------------------
    def _fetch_content(
        self,
        *,
        ingestion_mode: str,
        target_point: str,
        company_key: str,
        feed_item_url: Optional[str] = None,
    ) -> tuple[str, List[Dict[str, str]], str]:
        """Fetch 1 source βάσει ingestion_mode.

        Returns:
            (raw_content, sources, final_target_point)
        """
        if ingestion_mode == INGESTION_MODE_CUSTOM:
            return "", [], target_point

        from utils.providers import get_provider
        from utils.sources import get_company

        try:
            provider_name = self._resolve_provider_name()
            provider = get_provider(name=provider_name)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Could not initialize content provider: {exc}")
            return "", [], target_point

        try:
            company = get_company(company_key)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Unknown company: {exc}")
            return "", [], target_point

        raw_content = ""
        sources: List[Dict[str, str]] = []

        if ingestion_mode in (INGESTION_MODE_RSS, INGESTION_MODE_MANUAL):
            if not feed_item_url:
                st.error(f"❌ {ingestion_mode} requires a URL (feed_item_url empty).")
                return "", [], target_point
            with st.spinner("🔍 Extracting from URL..."):
                result = provider.extract_from_url(feed_item_url)
            if not result:
                st.error(f"❌ Could not extract content from: {feed_item_url}")
                return "", [], target_point
            url = result.get("url", feed_item_url)
            sources = [{
                "url": url,
                "title": result.get("title", "") or url,
                "domain": urlparse(url).netloc.lower(),
                "snippet": result.get("snippet", "") or "",
            }]
            raw_content = result.get("content", "")

        elif ingestion_mode == INGESTION_MODE_RESTRICTED:
            primary = company.primary_domain
            if not primary:
                st.error(f"❌ {company.display_name} has no domain for restricted search.")
                return "", [], target_point
            if not target_point or not target_point.strip():
                st.error("❌ Restricted Search requires a topic.")
                return "", [], target_point
            with st.spinner(f"🔍 Searching {primary} (restricted)..."):
                merged = provider.search_and_extract(target_point, max_results=6, site=primary)
            if not merged or not merged.get("sources"):
                st.error(f"❌ No results for {target_point!r} on {primary}.")
                return "", [], target_point
            sources = merged["sources"][:1]
            raw_content = merged.get("content", "")

        # ---------------------------------------------------------
        # SOURCE GATE: Έλεγχος αν το topic υπάρχει στην πηγή
        # ---------------------------------------------------------
        final_target = target_point
        if raw_content and target_point.strip():
            # Απλός έλεγχος (case-insensitive)
            if target_point.lower() not in raw_content.lower():
                # Αν η πηγή έχει τίτλο, αλλάζουμε το topic σε αυτόν
                if sources and sources[0].get("title"):
                    final_target = sources[0]["title"]
                    st.warning(
                        f"⚠️ Το θέμα άλλαξε σε '{final_target}' επειδή η πηγή δεν αναφέρει το αρχικό query."
                    )

        return raw_content, sources, final_target

    @staticmethod
    def _format_sources_for_prompt(sources: List[Dict[str, str]]) -> str:
        if not sources:
            return "(no sources provided)"
        lines = []
        for idx, src in enumerate(sources, start=1):
            title = src.get("title", "") or src.get("url", "")
            url = src.get("url", "")
            lines.append(f"[{idx}] {title} - {url}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_slug(title: str) -> str:
        if not title:
            return "untitled"
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s-]+", "-", slug).strip("-")
        return slug[:80] or "untitled"


# ============================================
# LOCAL TEST ENTRYPOINT
# ============================================
if __name__ == "__main__":
    generator = ArticleGenerator()
    output = generator.full_pipeline(
        target_point="GPT-6 release",
        category="AI Updates",
        company_key="openai",
        ingestion_mode=INGESTION_MODE_RESTRICTED,
        feed_item_url=None,
        language_selection="Greek",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
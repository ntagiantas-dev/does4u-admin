"""
Article generation pipeline for the does4u admin panel.

Pipeline (self-contained — handles fetch internally):
    Fetch (via provider abstraction)
        -> Cleaner (language-agnostic)
        -> Writer (per language, per category, with citations)
        -> Teasers (per language, per category, with fallback)
        -> ## Sources section appended programmatically (REPLACES any LLM section)

Provider abstraction: see utils.providers.
    - JinaProvider: SERP search + per-URL reader.
    - TavilyProvider: search + extract in one call.

Source modes:
    - "Auto (Jina)"           : provider search + extract (domain diversity ON).
    - "Manual (URLs)"         : user URLs only (domain diversity OFF).
    - "Hybrid (Jina + URLs)"  : user URLs first (no domain dedup), then
                                provider search (domain dedup), merged.

Model notes:
    - All stages use gpt-5.6-luna during the test phase.
    - GPT-5.x require ``max_completion_tokens`` and reject custom
      ``temperature``; both are handled in ``_call_llm``.
    - Teasers may fall back to gpt-4o-mini if Luna returns empty, and further
      to a sentence-extraction fallback if both fail.
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
# LANGUAGE OPTIONS
# ============================================
LANGUAGE_OPTIONS: Dict[str, Dict[str, str]] = {
    "greek": {"name": "Greek", "native": "Ελληνικά", "code": "el"},
    "english": {"name": "English", "native": "English", "code": "en"},
}

# ============================================
# SOURCE MODES
# ============================================
SOURCE_MODE_AUTO = "Auto (Jina)"
SOURCE_MODE_MANUAL = "Manual (URLs)"
SOURCE_MODE_HYBRID = "Hybrid (Jina + URLs)"
SOURCE_MODES = [SOURCE_MODE_AUTO, SOURCE_MODE_MANUAL, SOURCE_MODE_HYBRID]

# ============================================
# MODEL CONFIG
# ============================================
BLOG_MODEL = "gpt-5.6-luna"

CLEANER_MODEL = BLOG_MODEL
WRITER_MODEL = BLOG_MODEL
TEASER_MODEL = BLOG_MODEL
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
# MODULE-LEVEL HELPERS
# ============================================
def generate_fallback_teasers(article_text: str) -> Dict[str, Dict[str, Any]]:
    """Build teasers from the first sentences when the LLM fails.

    Returns the same shape as a successful LLM teaser response so the UI
    doesn't need to branch.
    """
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
    """Append a '## Sources' section, REPLACING any existing one.

    The LLM often adds its own partial Sources section (sometimes only 1 source
    even when 5 were provided). We override it programmatically so the final
    article always lists every fetched source.

    Args:
        article_markdown: The article body (may already contain '## Sources').
        sources: The authoritative list of fetched sources.

    Returns:
        The article with a single, correct '## Sources' section at the end.
    """
    # Step 1: Remove any existing Sources section (usually from the LLM).
    if "## Sources" in article_markdown:
        idx = article_markdown.find("## Sources")
        article_markdown = article_markdown[:idx].rstrip()

    if not sources:
        return article_markdown

    # Step 2: Build the authoritative Sources section.
    lines: List[str] = ["## Sources"]
    for s in sources:
        title = s.get("title") or s.get("url", "Source")
        url = s.get("url", "")
        if not url:
            continue
        lines.append(f"- [{title}]({url})")

    if len(lines) == 1:
        # No valid sources after filtering
        return article_markdown

    return article_markdown.rstrip() + "\n\n" + "\n".join(lines) + "\n"


# ============================================
# MAIN CLASS
# ============================================
class ArticleGenerator:
    """Blog article generation pipeline with category + language + sources."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = st.secrets.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Streamlit secrets")
        self.client: OpenAI = OpenAI(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_languages(selection: str) -> List[Dict[str, str]]:
        sel = (selection or "").strip().lower()
        if sel in ("both", "bilingual", "el+en", "gr+en"):
            return [LANGUAGE_OPTIONS["greek"], LANGUAGE_OPTIONS["english"]]
        if sel in ("greek", "gr", "el", "ελληνικά"):
            return [LANGUAGE_OPTIONS["greek"]]
        if sel in ("english", "en", "αγγλικά"):
            return [LANGUAGE_OPTIONS["english"]]
        logger.warning("Unknown language %r — defaulting to Greek", selection)
        return [LANGUAGE_OPTIONS["greek"]]

    @staticmethod
    def get_category_config(category: str) -> Dict[str, Any]:
        if category not in BLOG_CATEGORIES:
            raise ValueError(
                f"Unknown category {category!r}. "
                f"Valid: {list(BLOG_CATEGORIES.keys())}"
            )
        return BLOG_CATEGORIES[category]

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_provider_name() -> Optional[str]:
        """Read the provider name from Streamlit session state, if available."""
        try:
            return st.session_state.get("content_provider")
        except Exception:  # noqa: BLE001 — script mode / no context
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
        """Call OpenAI. Empty response triggers a single retry with 2x budget."""
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
                    stage,
                    model,
                    retry_tokens,
                )
                response = self.client.chat.completions.create(
                    model=model,
                    max_completion_tokens=retry_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content

                if not content or not content.strip():
                    logger.error(
                        "[%s] Empty response from %s after retry", stage, model
                    )
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
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                stage=stage,
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
            model=CLEANER_MODEL,
            prompt=prompt,
            max_tokens=CLEANER_MAX_TOKENS,
            stage="Cleaner",
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
            model=WRITER_MODEL,
            prompt=prompt,
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
    # Stage 3 — Teasers (with fallback chain)
    # ------------------------------------------------------------------
    def generate_social_teasers(
        self,
        title: str,
        category: str,
        keywords: List[str],
        language: str = "Greek",
        article_text: str = "",
    ) -> Dict[str, Dict[str, Any]]:
        """Generate teasers. Never returns None — falls back to text extraction."""
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

        # Attempt 1: primary model
        result = self._call_llm_json(
            model=TEASER_MODEL,
            prompt=prompt,
            max_tokens=TEASER_MAX_TOKENS,
            stage=f"Teasers/{category}/{language}",
        )
        if result and all(k in result for k in ("twitter", "linkedin", "facebook")):
            return result

        # Attempt 2: fallback model
        logger.warning(
            "[Teasers/%s/%s] Primary model failed, trying %s",
            category,
            language,
            TEASER_FALLBACK_MODEL,
        )
        result = self._call_llm_json(
            model=TEASER_FALLBACK_MODEL,
            prompt=prompt,
            max_tokens=TEASER_FALLBACK_MAX_TOKENS,
            stage=f"Teasers-fallback/{category}/{language}",
        )
        if result and all(k in result for k in ("twitter", "linkedin", "facebook")):
            return result

        # Attempt 3: text fallback
        logger.warning(
            "[Teasers/%s/%s] Both models failed — using text fallback",
            category,
            language,
        )
        return generate_fallback_teasers(article_text)

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def full_pipeline(
        self,
        target_point: str,
        category: str,
        source_mode: str = SOURCE_MODE_AUTO,
        language_selection: str = "Greek",
        urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        empty_result: Dict[str, Any] = {
            "cleaner": {},
            "sources": [],
            "category_slug": "",
            "bundles": [],
        }

        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return empty_result
        empty_result["category_slug"] = cfg["slug"]

        # ---- Fetch ----
        raw_content, sources = self._fetch_content(
            source_mode=source_mode,
            target_point=target_point,
            urls=urls,
        )
        if not raw_content:
            st.error("❌ No content could be fetched. Pipeline aborted.")
            return empty_result

        # ---- Cleaner ----
        with st.spinner("🧹 Cleaning content..."):
            cleaner_output = self.clean_content(raw_content, target_point)

        if not cleaner_output:
            truncated = raw_content[:FALLBACK_RAW_CONTENT_CHARS]
            logger.warning(
                "[Pipeline] Cleaner failed — fallback to truncated raw (%d chars)",
                len(truncated),
            )
            st.warning(
                f"⚠️ Cleaner failed — falling back to raw content "
                f"(truncated to {FALLBACK_RAW_CONTENT_CHARS} chars)."
            )
            cleaner_output = {
                "cleaned_content": truncated,
                "key_facts": [],
                "topic_summary": "(fallback — cleaner unavailable)",
                "_fallback": True,
            }

        # ---- Writer + Teasers per language ----
        targets = self.resolve_languages(language_selection)
        translation_id: Optional[str] = str(uuid.uuid4()) if len(targets) > 1 else None

        bundles: List[Dict[str, Any]] = []
        for target in targets:
            lang_name = target["name"]
            lang_code = target["code"]

            with st.spinner(f"✍️ Writing article ({target['native']})..."):
                article = self.generate_article(
                    cleaned_content=cleaner_output.get("cleaned_content", ""),
                    target_point=target_point,
                    category=category,
                    key_facts=cleaner_output.get("key_facts") or [],
                    language=lang_name,
                    sources=sources,
                )
            if not article:
                logger.error("[Pipeline] Writer failed for %s", lang_name)
                continue

            # Enforce ## Sources section programmatically.
            # This REPLACES any partial section the LLM may have written.
            article["content_markdown"] = append_sources_section(
                article.get("content_markdown", ""),
                sources,
            )

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
                    # Always expose the AUTHORITATIVE fetched sources, not the
                    # (possibly incomplete) list the LLM produced.
                    "sources": sources,
                }
            )

        return {
            "cleaner": cleaner_output,
            "sources": sources,
            "category_slug": cfg["slug"],
            "bundles": bundles,
        }

    # ------------------------------------------------------------------
    # Fetch (provider-aware, mode-aware)
    # ------------------------------------------------------------------
    def _fetch_content(
        self,
        *,
        source_mode: str,
        target_point: str,
        urls: Optional[List[str]],
    ) -> tuple[str, List[Dict[str, str]]]:
        """Fetch content via the selected provider, respecting source_mode.

        - Manual: only user URLs; domain diversity OFF.
        - Auto:   provider search; domain diversity ON.
        - Hybrid: manual (no domain dedup) + auto (domain dedup) merged;
                  final URL-only dedup to remove cross-mode duplicates.

        Returns:
            (raw_content, sources). Both empty on total failure.
        """
        from utils.providers import get_provider

        # Resolve provider (may raise if Tavily selected but not configured)
        try:
            provider_name = self._resolve_provider_name()
            provider = get_provider(name=provider_name)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Could not initialize content provider: {exc}")
            return "", []

        manual_urls = urls or []
        raw_parts: List[str] = []
        sources: List[Dict[str, str]] = []

        # ---- Manual URLs (Manual or Hybrid) ----
        if source_mode in (SOURCE_MODE_MANUAL, SOURCE_MODE_HYBRID) and manual_urls:
            with st.spinner(f"🔍 Extracting content from {len(manual_urls)} URL(s)..."):
                manual_extractions: List[Dict[str, Any]] = []
                for url in manual_urls:
                    result = provider.extract_from_url(url)
                    if result:
                        manual_extractions.append(result)
                    else:
                        st.warning(f"⚠️ Could not extract content from: {url}")

            if manual_extractions:
                merged_manual = provider.merge_extractions(manual_extractions)
                manual_sources = self._dedupe_sources(
                    merged_manual["sources"], enforce_domain_diversity=False
                )
                sources.extend(manual_sources)
                raw_parts.append(merged_manual["content"])

        # ---- Auto search (Auto or Hybrid) ----
        if source_mode in (SOURCE_MODE_AUTO, SOURCE_MODE_HYBRID):
            with st.spinner("🔍 Searching + extracting..."):
                merged_auto = provider.search_and_extract(
                    target_point, max_results=6
                )

            if merged_auto:
                auto_sources = self._dedupe_sources(
                    merged_auto.get("sources", []),
                    enforce_domain_diversity=True,
                )
                # Avoid duplicating manual URLs
                manual_urls_set = {s.get("url") for s in sources if s.get("url")}
                auto_sources = [
                    s for s in auto_sources if s.get("url") not in manual_urls_set
                ]
                if auto_sources:
                    sources.extend(auto_sources)
                    raw_parts.append(merged_auto.get("content", ""))

        # Final URL-only dedup across all sources
        sources = self._dedupe_sources(sources, enforce_domain_diversity=False)

        raw_content = "\n\n---\n\n".join(p for p in raw_parts if p)
        return raw_content, sources

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _dedupe_sources(
        sources: List[Dict[str, str]],
        enforce_domain_diversity: bool = False,
    ) -> List[Dict[str, str]]:
        """Remove duplicate sources.

        Args:
            sources: List of {"url", "title", "domain"} dicts.
            enforce_domain_diversity: If True, allow at most one source per
                domain (used in Auto mode for credibility diversity). If False,
                keep all unique URLs (used in Manual mode to honor user choice).
        """
        if not sources:
            return []

        seen_urls: set = set()
        seen_domains: set = set()
        result: List[Dict[str, str]] = []

        for s in sources:
            url = (s.get("url") or "").strip()
            if not url or url in seen_urls:
                continue

            if enforce_domain_diversity:
                domain = urlparse(url).netloc.lower()
                if domain and domain in seen_domains:
                    continue
                if domain:
                    seen_domains.add(domain)

            seen_urls.add(url)
            result.append(s)

        return result

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
        target_point="automation excel",
        category="Growth Hack",
        source_mode=SOURCE_MODE_AUTO,
        language_selection="Both",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
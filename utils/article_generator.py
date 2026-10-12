"""
Article generation pipeline for the does4u admin panel.

Pipeline (self-contained — handles fetch internally):
    Fetch (Jina search and/or manual URLs)
        -> Cleaner (language-agnostic)
        -> Writer (per language, per category, with citations)
        -> Teasers (per language, per category)

Categories (see BLOG_CATEGORIES in utils.prompts):
    - "AI Updates"  : traffic-focused (news/curiosity angle)
    - "Growth Hack" : conversion-focused (problem/solution angle)

Source modes:
    - "Auto (Jina)"           : Jina SERP search -> extract top results
    - "Manual (URLs)"         : user-provided URLs only
    - "Hybrid (Jina + URLs)"  : user URLs first, then Jina search, merged

Language handling:
    - Cleaner runs ONCE.
    - Writer + Teasers run ONCE PER target language.
    - For "Both", articles share a common ``translation_id`` (uuid).

Model notes:
    - All stages currently use a single model: gpt-5.6-luna.
    - GPT-5.x models require ``max_completion_tokens`` (not ``max_tokens``).
    - GPT-5.x models reject custom ``temperature``; only the default is
      accepted, so the parameter is omitted entirely.
    - GPT-5.x are reasoning models: a large portion of ``max_completion_tokens``
      is consumed by internal reasoning before any output is produced. Token
      budgets are therefore generous, and an empty response triggers a single
      retry with a doubled budget.
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
# MODEL CONFIG — single model across all stages
# ============================================
BLOG_MODEL = "gpt-5.6-luna"

CLEANER_MODEL = BLOG_MODEL
WRITER_MODEL = BLOG_MODEL
TEASER_MODEL = BLOG_MODEL

# Token budgets (generous — reasoning models consume tokens internally).
CLEANER_MAX_TOKENS = 4000
WRITER_MAX_TOKENS = 8000
TEASER_MAX_TOKENS = 2000

# Retry multiplier when the model returns an empty response.
EMPTY_RESPONSE_RETRY_MULTIPLIER = 2

MAX_RAW_CONTENT_CHARS = 12000
MAX_CLEANED_CONTENT_CHARS = 6000
# Bug #3 fix: cap fallback content so we never send the full raw blob to the model.
FALLBACK_RAW_CONTENT_CHARS = 4000


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
        """Map UI language selection to a list of language target dicts."""
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
        """Call the OpenAI Chat Completions API and return the text content.

        Empty responses trigger a single retry with a doubled token budget.
        This is necessary because GPT-5.x reasoning models occasionally consume
        the entire completion budget on internal reasoning and emit no output.

        Note: GPT-5.x rejects custom temperature, so it is not sent.
        """
        try:
            response = self.client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content

            if not content or not content.strip():
                # Retry once with a doubled budget.
                retry_tokens = max_tokens * EMPTY_RESPONSE_RETRY_MULTIPLIER
                logger.warning(
                    "[%s] Empty response from %s — retrying with %d tokens",
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
                    st.error(
                        f"❌ [{stage}] Model returned an empty response twice. "
                        f"Try a different topic or check the model name."
                    )
                    return None

                logger.info("[%s] Retry succeeded for %s", stage, model)

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
        st.error(f"❌ [{stage}] Failed to parse JSON after {attempts} attempt(s).")
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
            st.error("❌ [Cleaner] Empty raw content received.")
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
    # Stage 2 — Writer (per language, per category)
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
            st.error(f"❌ [Writer/{language}] Empty cleaned content.")
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
            st.error("❌ [Writer] Response missing 'content_markdown'.")
            return None
        if not result.get("slug"):
            result["slug"] = self._fallback_slug(result.get("title", ""))
        if not isinstance(result.get("sources"), list):
            result["sources"] = []
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
    ) -> Optional[Dict[str, Any]]:
        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return None

        prompt = cfg["teaser_prompt"].format(
            title=title or "(untitled)",
            category=category,
            keywords=", ".join(keywords) if keywords else "(none)",
            language=language,
        )
        result = self._call_llm_json(
            model=TEASER_MODEL,
            prompt=prompt,
            max_tokens=TEASER_MAX_TOKENS,
            stage=f"Teasers/{category}/{language}",
        )
        if not result:
            return None
        for platform in ("twitter", "linkedin", "facebook"):
            value = result.get(platform)
            if not isinstance(value, dict) or "text" not in value:
                logger.warning("[Teasers] Platform %s malformed", platform)
        return result

    # ------------------------------------------------------------------
    # Full pipeline (self-contained — handles fetch)
    # ------------------------------------------------------------------
    def full_pipeline(
        self,
        target_point: str,
        category: str,
        source_mode: str = SOURCE_MODE_AUTO,
        language_selection: str = "Greek",
        urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run the full pipeline: fetch -> clean -> write -> teasers.

        Args:
            target_point: SEO topic.
            category: One of BLOG_CATEGORIES keys.
            source_mode: SOURCE_MODE_AUTO / SOURCE_MODE_MANUAL / SOURCE_MODE_HYBRID.
            language_selection: "Greek" | "English" | "Both".
            urls: User-provided URLs. Required for Manual, optional for Hybrid.

        Returns:
            {
              "cleaner": {...},
              "sources": [{"url","title","domain"}],
              "category_slug": "ai-updates" | "growth-hack",
              "bundles": [ {language, language_name, translation_id,
                            article, teasers, sources}, ... ],
            }
        """
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

        # ---- Fetch content (mode-aware) ----
        raw_content, sources = self._fetch_content(
            source_mode=source_mode,
            target_point=target_point,
            urls=urls,
        )
        if not raw_content:
            st.error("❌ No content could be fetched. Pipeline aborted.")
            return empty_result

        # ---- Cleaner (once) ----
        with st.spinner("🧹 Cleaning content..."):
            cleaner_output = self.clean_content(raw_content, target_point)

        if not cleaner_output:
            # Bug #3 fix: truncate fallback content before sending to the model.
            truncated = raw_content[:FALLBACK_RAW_CONTENT_CHARS]
            logger.warning(
                "[Pipeline] Cleaner failed — falling back to truncated raw "
                "content (%d chars)",
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

            with st.spinner(f"📱 Generating teasers ({target['native']})..."):
                teasers = self.generate_social_teasers(
                    title=article.get("title", ""),
                    category=category,
                    keywords=article.get("keywords") or [],
                    language=lang_name,
                )
            if not teasers:
                logger.error("[Pipeline] Teasers failed for %s", lang_name)
                continue

            bundles.append(
                {
                    "language": lang_code,
                    "language_name": lang_name,
                    "translation_id": translation_id,
                    "article": article,
                    "teasers": teasers,
                    "sources": article.get("sources") or sources,
                }
            )

        return {
            "cleaner": cleaner_output,
            "sources": sources,
            "category_slug": cfg["slug"],
            "bundles": bundles,
        }

    # ------------------------------------------------------------------
    # Internal — fetch
    # ------------------------------------------------------------------
    def _fetch_content(
        self,
        *,
        source_mode: str,
        target_point: str,
        urls: Optional[List[str]],
    ) -> tuple[str, List[Dict[str, str]]]:
        """Fetch raw content based on source_mode.

        Bug #5 fix: a single JinaService instance is used across both stages
        so the rate-limit state (``_last_reader_call``) is preserved.

        Bug #4 fix: sources are deduplicated by URL before returning.
        TASK-213-followup: sources are also deduplicated by domain.

        Returns:
            ``(raw_content, sources)``. Both empty on failure.
        """
        # Lazy import to avoid circular imports
        from utils.jina_service import JinaService

        jina = JinaService()  # Bug #5: single instance for rate limit state
        manual_urls = urls or []
        raw_content = ""
        sources: List[Dict[str, str]] = []

        # --- Manual URLs (Manual mode, or Hybrid mode) ---
        if source_mode in (SOURCE_MODE_MANUAL, SOURCE_MODE_HYBRID) and manual_urls:
            with st.spinner(f"🔍 Extracting content from {len(manual_urls)} URL(s)..."):
                merged = jina.extract_multiple(manual_urls, show_errors=True)
            if merged:
                raw_content = merged.get("content", "")
                sources = merged.get("sources", [])

        # --- Jina search (Auto mode, or Hybrid mode) ---
        if source_mode in (SOURCE_MODE_AUTO, SOURCE_MODE_HYBRID):
            with st.spinner("🔍 Searching + extracting (Jina)..."):
                merged = jina.search_and_extract(target_point)
            if merged:
                auto_content = merged.get("content", "")
                auto_sources = merged.get("sources", [])
                if raw_content and auto_content:
                    # Hybrid: manual content first, then auto
                    raw_content = raw_content + "\n\n---\n\n" + auto_content
                    sources = sources + auto_sources
                elif auto_content:
                    raw_content = auto_content
                    sources = auto_sources

        # Bug #4 + TASK-213-followup: dedupe by URL and by domain
        return raw_content, self._dedupe_sources(sources)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _dedupe_sources(
        sources: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Remove duplicate sources by URL AND by domain (max 1 per domain).

        Bug #4 fix: in Hybrid mode the same URL may appear both in the manual
        list and in the Jina SERP, which caused duplicate citations in the
        article.

        TASK-213-followup: domain-level dedup ensures diverse sources so the
        article doesn't rely on a single site (e.g. n8n.io + github.com/n8n-io).
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

            domain = urlparse(url).netloc.lower()
            if domain and domain in seen_domains:
                continue  # skip same-domain source

            seen_urls.add(url)
            if domain:
                seen_domains.add(domain)
            result.append(s)

        return result

    @staticmethod
    def _format_sources_for_prompt(sources: List[Dict[str, str]]) -> str:
        """Format sources as a numbered list for the citation prompt.

        Example output:
            [1] Title A - https://example.com/a
            [2] Title B - https://example.com/b
        """
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
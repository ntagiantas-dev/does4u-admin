"""
Article generation pipeline for the does4u admin panel.

Pipeline:
    Jina (fetch) -> Cleaner -> Writer (per language, per category)
                             -> Teasers (per language, per category)

Categories (see BLOG_CATEGORIES in utils.prompts):
    - "AI Updates"  : traffic-focused (news/curiosity angle)
    - "Growth Hack" : conversion-focused (problem/solution angle)

Language handling:
    - Cleaner runs ONCE (language-agnostic fact extraction).
    - Writer + Teasers run ONCE PER target language.
    - For "Both", the two articles share a common ``translation_id`` (uuid)
      so the FastAPI site can emit hreflang tags (x-default -> Greek).
"""
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

import streamlit as st
from openai import OpenAI

from utils.prompts import BLOG_CATEGORIES, CLEANER_PROMPT

logger = logging.getLogger(__name__)


# ============================================
# LANGUAGE OPTIONS
# ============================================
LANGUAGE_OPTIONS: Dict[str, Dict[str, str]] = {
    "greek": {"name": "Greek", "native": "Ελληνικά", "code": "el"},
    "english": {"name": "English", "native": "English", "code": "en"},
}


# ============================================
# MODEL CONFIG
# ============================================
CLEANER_MODEL = "gpt-5.6-luna"
WRITER_MODEL = "gpt-5.6-sol"
TEASER_MODEL = "gpt-5.6-sol"

CLEANER_MAX_TOKENS = 2000
WRITER_MAX_TOKENS = 3000
TEASER_MAX_TOKENS = 1000

CLEANER_TEMPERATURE = 0.3
WRITER_TEMPERATURE = 0.7
TEASER_TEMPERATURE = 0.8

MAX_RAW_CONTENT_CHARS = 8000
MAX_CLEANED_CONTENT_CHARS = 6000


class ArticleGenerator:
    """Blog article generation pipeline with category + language support."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = st.secrets.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Streamlit secrets")
        self.client: OpenAI = OpenAI(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Language + category resolution
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_languages(selection: str) -> List[Dict[str, str]]:
        """Map UI language selection to a list of language target dicts.

        "Both" returns [greek, english] (Greek first, per D-010).
        """
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
        """Return the category config dict (prompts, slug, mission).

        Raises:
            ValueError: if the category is not registered in BLOG_CATEGORIES.
        """
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
        temperature: float,
        stage: str,
    ) -> Optional[str]:
        try:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                logger.error("[%s] Empty response from %s", stage, model)
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
        temperature: float,
        stage: str,
        max_retries: int = 1,
    ) -> Optional[Dict[str, Any]]:
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            raw = self._call_llm(
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
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
            temperature=CLEANER_TEMPERATURE,
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

        prompt = cfg["article_prompt"].format(
            target_point=target_point,
            category=category,
            language=language,
            cleaned_content=cleaned_content[:MAX_CLEANED_CONTENT_CHARS],
            key_facts=key_facts_str,
        )
        result = self._call_llm_json(
            model=WRITER_MODEL,
            prompt=prompt,
            max_tokens=WRITER_MAX_TOKENS,
            temperature=WRITER_TEMPERATURE,
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
        return result

    # ------------------------------------------------------------------
    # Stage 3 — Teasers (per language, per category)
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
            temperature=TEASER_TEMPERATURE,
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
    # Full pipeline
    # ------------------------------------------------------------------
    def full_pipeline(
        self,
        extracted_content: str,
        target_point: str,
        category: str,
        language_selection: str = "Greek",
    ) -> Dict[str, Any]:
        """Run Cleaner once, then Writer + Teasers per language.

        Returns:
            {
              "cleaner": {...},
              "category_slug": "ai-updates" | "growth-hack",
              "bundles": [
                 {"language": "el", "language_name": "Greek",
                  "translation_id": str | None,
                  "article": {...}, "teasers": {...}},
                 ...
              ],
            }
        """
        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return {"cleaner": {}, "category_slug": "", "bundles": []}

        targets = self.resolve_languages(language_selection)
        translation_id = str(uuid.uuid4()) if len(targets) > 1 else None

        with st.spinner("🧹 Cleaning content..."):
            cleaner_output = self.clean_content(extracted_content, target_point)

        if not cleaner_output:
            logger.warning("[Pipeline] Cleaner failed — fallback to raw content")
            st.warning("⚠️ Cleaner failed — falling back to raw content.")
            cleaner_output = {
                "cleaned_content": extracted_content,
                "key_facts": [],
                "topic_summary": "(fallback — cleaner unavailable)",
                "_fallback": True,
            }

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
                }
            )

        return {
            "cleaner": cleaner_output,
            "category_slug": cfg["slug"],
            "bundles": bundles,
        }

    # ------------------------------------------------------------------
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
        extracted_content="Sample about automation and Excel workflows...",
        target_point="automation excel",
        category="Growth Hack",
        language_selection="Both",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
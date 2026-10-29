"""
Content providers for the does4u admin panel.

Abstraction over "search + extract" backends so the article generator
doesn't need to know which service is active.

v3.0 strategies:
    - Manual selection: get_provider(name=...) or CONTENT_PROVIDER env var.

Future (out of scope for v3.0):
    - v3.1: ParallelProvider (race both, first with >=5 sources wins).
    - v3.2: FallbackProvider (try one, fall back to other on failure).

Interface:
    - ContentProvider.extract_from_url(url) -> Optional[Dict]
    - ContentProvider.search_and_extract(target_point, max_results) -> Optional[Dict]

Both methods return dicts whose `sources` field has entries of the form
    {"url": str, "title": str, "domain": str}
with the merged plain text in the top-level `content` field.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


# ============================================
# CONSTANTS
# ============================================
# Strong CAPTCHA signals only (weak ones like "enable javascript" caused
# false positives in v2.0).
STRONG_CAPTCHA_KEYWORDS = [
    "prove your humanity",
    "captcha",
    "are you a robot",
    "not a robot",
    "verify you are human",
]

MIN_CONTENT_CHARS = 500
TARGET_VALID_SOURCES = 5

# Jina specific
JINA_SEARCH_BASE = "https://s.jina.ai"
JINA_READER_BASE = "https://r.jina.ai"
JINA_TIMEOUT = 30
JINA_RATE_LIMIT_SECONDS = 1.0


# ============================================
# ABSTRACT BASE
# ============================================
class ContentProvider(ABC):
    """Abstract base for content providers."""

    name: str = "base"

    @abstractmethod
    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract content from a single URL.

        Returns:
            {"url": str, "title": str, "content": str} or None on failure.
        """

    @abstractmethod
    def search_and_extract(
        self, target_point: str, max_results: int = 6
    ) -> Optional[Dict[str, Any]]:
        """Search + extract content for a target point.

        Returns:
            {
                "target_point": str,
                "sources": List[{"url": str, "title": str, "domain": str}],
                "content": str,  # merged content
            }
            or None on failure.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    @staticmethod
    def merge_extractions(
        extractions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge N extractions into one content blob + sources list.

        Each extraction is expected to have ``url``, ``title``, ``content``.

        Returns:
            {"content": str, "sources": List[{"url","title","domain"}]}
        """
        parts: List[str] = []
        sources: List[Dict[str, str]] = []

        for ext in extractions:
            url = ext.get("url", "")
            title = ext.get("title", "") or url
            domain = urlparse(url).netloc.lower() if url else ""

            sources.append({"url": url, "title": title, "domain": domain})
            parts.append(f"# Source: {title}\nURL: {url}\n\n{ext.get('content', '')}")

        return {
            "content": "\n\n---\n\n".join(parts),
            "sources": sources,
        }

    @staticmethod
    def is_captcha_content(
        data: Dict[str, Any],
        content: str,
        provider_name: str = "provider",
    ) -> bool:
        """Detect CAPTCHA / human-verification pages.

        Uses only strong signals (see STRONG_CAPTCHA_KEYWORDS) to avoid
        false positives on pages that merely mention "enable javascript".

        Args:
            data: The provider's response dict (may carry a "warning" field).
            content: The extracted text content.
            provider_name: Label used in log messages ("jina", "tavily", ...).

        Returns:
            True if the page should be rejected as CAPTCHA.
        """
        warning = str(data.get("warning", "")).lower()
        if "captcha" in warning or "humanity" in warning:
            logger.warning(
                "[%s] CAPTCHA warning field: %r",
                provider_name,
                warning[:120],
            )
            return True

        content_lower = content.lower()
        for kw in STRONG_CAPTCHA_KEYWORDS:
            if kw in content_lower:
                logger.warning(
                    "[%s] CAPTCHA keyword %r detected",
                    provider_name,
                    kw,
                )
                return True

        return False


# ============================================
# JINA PROVIDER
# ============================================
class JinaProvider(ContentProvider):
    """Jina AI provider.

    Search: s.jina.ai with ``X-Respond-With: no-content`` (SERP only).
    Extract: r.jina.ai (full page content).

    Rate limit: 1 reader call per second.
    """

    name = "jina"

    def __init__(
        self,
        search_helper: Optional[Callable[[str, int], List[Dict[str, str]]]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """
        Args:
            search_helper: Optional override for the search step. Signature:
                (target_point: str, max_results: int) -> List[{"url","title"}].
                If None, uses internal SERP search.
            api_key: Optional Jina API key. If None, reads st.secrets["JINA_API_KEY"].
        """
        self._search_helper = search_helper
        self._api_key = api_key
        self._last_reader_call: float = 0.0

    # ------------------------------------------------------------------
    # API key
    # ------------------------------------------------------------------
    def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        import streamlit as st

        key = st.secrets.get("JINA_API_KEY")
        if not key:
            raise ValueError("JINA_API_KEY not found in Streamlit secrets")
        self._api_key = key
        return key

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _internal_search(
        self, target_point: str, max_results: int = 6
    ) -> List[Dict[str, str]]:
        """Call s.jina.ai and return SERP links."""
        import requests

        if not target_point or not target_point.strip():
            return []

        try:
            headers = {
                "Authorization": f"Bearer {self._get_api_key()}",
                "Accept": "application/json",
                "X-Respond-With": "no-content",
            }
            url = f"{JINA_SEARCH_BASE}/{quote(target_point)}"
            response = requests.get(url, headers=headers, timeout=JINA_TIMEOUT)
            if response.status_code != 200:
                logger.error(
                    "[jina] Search failed (%s): %s",
                    response.status_code,
                    response.text[:300],
                )
                return []

            payload = response.json()
            raw = payload.get("data", [])
            if not isinstance(raw, list):
                return []

            links: List[Dict[str, str]] = []
            for item in raw[: max(1, min(int(max_results), 8))]:
                u = item.get("url") or item.get("link")
                if not u:
                    continue
                links.append(
                    {
                        "url": u,
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                    }
                )
            return links

        except Exception as exc:  # noqa: BLE001
            logger.exception("[jina] Search error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------
    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        import requests

        if not url or not url.strip():
            return None

        # Rate limit
        if self._last_reader_call > 0:
            elapsed = time.monotonic() - self._last_reader_call
            if elapsed < JINA_RATE_LIMIT_SECONDS:
                time.sleep(JINA_RATE_LIMIT_SECONDS - elapsed)

        try:
            headers = {
                "Authorization": f"Bearer {self._get_api_key()}",
                "Accept": "application/json",
            }
            reader_url = f"{JINA_READER_BASE}/{url}"
            response = requests.get(reader_url, headers=headers, timeout=JINA_TIMEOUT)
            self._last_reader_call = time.monotonic()

            if response.status_code != 200:
                logger.error(
                    "[jina] Reader failed (%s) for %s", response.status_code, url
                )
                return None

            payload = response.json()
            data = payload.get("data", payload)
            content = data.get("content", "") or ""

            # CAPTCHA detection (strong signals only) — Διόρθωση B
            if self.is_captcha_content(data, content, provider_name=self.name):
                return None

            if len(content.strip()) < MIN_CONTENT_CHARS:
                logger.warning(
                    "[jina] Content too short (%d chars, min %d): %s",
                    len(content),
                    MIN_CONTENT_CHARS,
                    url,
                )
                return None

            return {
                "url": url,
                "title": data.get("title", "") or url,
                "content": content,
            }

        except Exception as exc:  # noqa: BLE001
            logger.exception("[jina] Reader error for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------
    def search_and_extract(
        self, target_point: str, max_results: int = 6
    ) -> Optional[Dict[str, Any]]:
        search_fn = self._search_helper or self._internal_search
        links = search_fn(target_point, max_results)
        if not links:
            logger.warning("[jina] No SERP results for %r", target_point)
            return None

        extractions: List[Dict[str, Any]] = []
        for link in links:
            if len(extractions) >= TARGET_VALID_SOURCES:
                break
            result = self.extract_from_url(link["url"])
            if result:
                if not result.get("title") and link.get("title"):
                    result["title"] = link["title"]
                extractions.append(result)

        if not extractions:
            return None

        merged = self.merge_extractions(extractions)
        merged["target_point"] = target_point
        return merged


# ============================================
# TAVILY PROVIDER
# ============================================
class TavilyProvider(ContentProvider):
    """Tavily provider.

    Search + extract in one API call via ``client.search(include_raw_content=True)``.
    Requires TAVILY_API_KEY in env var OR Streamlit secrets.

    The ``tavily-python`` package is imported lazily so the app doesn't break
    if it's not installed and Jina is being used instead.
    """

    name = "tavily"

    def __init__(self, api_key: Optional[str] = None) -> None:
        try:
            from tavily import TavilyClient  # noqa: F401 (lazy import)
        except ImportError as exc:
            raise RuntimeError(
                "tavily-python is not installed. "
                "Run: pip install tavily-python"
            ) from exc

        # Διόρθωση A: env var → st.secrets fallback (Render-friendly).
        self._api_key = api_key or self._resolve_api_key()
        if not self._api_key:
            raise RuntimeError(
                "TAVILY_API_KEY not set. "
                "Add it to .env, environment, or Streamlit secrets."
            )

        from tavily import TavilyClient as _TC

        self._client = _TC(api_key=self._api_key)

    @staticmethod
    def _resolve_api_key() -> Optional[str]:
        """Resolve API key from env var, then Streamlit secrets."""
        key = os.getenv("TAVILY_API_KEY")
        if key:
            return key
        try:
            import streamlit as st

            return st.secrets.get("TAVILY_API_KEY")
        except Exception:  # noqa: BLE001 — no Streamlit context
            return None

    # ------------------------------------------------------------------
    # Extract single URL
    # ------------------------------------------------------------------
    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        if not url or not url.strip():
            return None
        try:
            response = self._client.extract([url])
            results = response.get("results", []) if isinstance(response, dict) else []
            if not results:
                return None
            r = results[0]
            content = (r.get("raw_content") or r.get("content") or "").strip()
            if len(content) < MIN_CONTENT_CHARS:
                logger.warning(
                    "[tavily] Content too short (%d chars) for %s", len(content), url
                )
                return None
            return {
                "url": r.get("url", url),
                "title": r.get("title", "") or url,
                "content": content,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("[tavily] Extract error for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------
    def search_and_extract(
        self, target_point: str, max_results: int = 6
    ) -> Optional[Dict[str, Any]]:
        try:
            response = self._client.search(
                target_point,
                max_results=max_results,
                include_raw_content=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[tavily] Search error: %s", exc)
            return None

        results = response.get("results", []) if isinstance(response, dict) else []
        if not results:
            logger.warning("[tavily] No results for %r", target_point)
            return None

        extractions: List[Dict[str, Any]] = []
        for r in results:
            if len(extractions) >= TARGET_VALID_SOURCES:
                break
            content = (r.get("raw_content") or r.get("content") or "").strip()
            if len(content) < MIN_CONTENT_CHARS:
                continue
            extractions.append(
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", "") or r.get("url", ""),
                    "content": content,
                }
            )

        if not extractions:
            return None

        merged = self.merge_extractions(extractions)
        merged["target_point"] = target_point
        return merged


# ============================================
# FACTORY
# ============================================
def get_provider(
    name: Optional[str] = None, **kwargs: Any
) -> ContentProvider:
    """Return a ContentProvider instance.

    Resolution order:
        1. Explicit ``name`` argument.
        2. CONTENT_PROVIDER env var.
        3. Default: "jina".

    v3.0: manual selection only.
    Future v3.1: wrap in ParallelProvider when CONTENT_PROVIDER_PARALLEL=true.
    Future v3.2: wrap in FallbackProvider when CONTENT_PROVIDER_FALLBACK set.
    """
    resolved = (name or os.getenv("CONTENT_PROVIDER", "jina")).lower().strip()

    if resolved == "jina":
        return JinaProvider(**kwargs)
    if resolved == "tavily":
        return TavilyProvider(**kwargs)
    raise ValueError(
        f"Unknown provider: {resolved!r}. Valid: ['jina', 'tavily']"
    )


__all__ = [
    "ContentProvider",
    "JinaProvider",
    "TavilyProvider",
    "get_provider",
    "STRONG_CAPTCHA_KEYWORDS",
    "MIN_CONTENT_CHARS",
]
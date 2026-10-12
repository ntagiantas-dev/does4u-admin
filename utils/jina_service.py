"""
Jina AI service for the does4u admin panel.

Capabilities:
    - search_links()      : SERP search via s.jina.ai (5 links, no content)
    - extract_from_url()  : read a single URL via r.jina.ai
    - extract_multiple()  : read N URLs, return merged content + sources
    - search_and_extract(): search + extract + merge (auto mode)

API reference:
    - Search:    https://s.jina.ai/<query>   (GET, X-Respond-With: no-content)
    - Reader:    https://r.jina.ai/<url>     (GET, Accept: application/json)

Rate limit: 1 request / second (enforced between r.jina.ai calls).
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests
import streamlit as st

logger = logging.getLogger(__name__)


# ============================================
# CONFIG
# ============================================
JINA_SEARCH_BASE = "https://s.jina.ai"
JINA_READER_BASE = "https://r.jina.ai"

DEFAULT_TIMEOUT = 30
DEFAULT_SEARCH_RESULTS = 6   # request more links so we can survive failures
MAX_SEARCH_RESULTS = 8
TARGET_VALID_SOURCES = 5     # stop extracting once we have this many
MAX_MANUAL_URLS = 5
RATE_LIMIT_SECONDS = 1.0     # between r.jina.ai calls

# Reject pages with too little text. Raised from 100 -> 500 because CAPTCHA
# pages and near-empty templates were slipping through the old threshold.
MIN_CONTENT_CHARS = 500

# Phrases that almost always indicate a CAPTCHA / human-verification page.
CAPTCHA_KEYWORDS = [
    "prove your humanity",
    "captcha",
    "are you a robot",
    "enable javascript",
    "checking your browser",
    "please verify you are human",
    "not a robot",
    "verify you are human",
]


class JinaService:
    """Jina AI wrapper: SERP search + URL content extraction + merge."""

    def __init__(self) -> None:
        """Initialize the Jina client using Streamlit secrets."""
        self.api_key: Optional[str] = st.secrets.get("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("JINA_API_KEY not found in Streamlit secrets")

        self.search_base = JINA_SEARCH_BASE
        self.reader_base = JINA_READER_BASE
        self._last_reader_call: float = 0.0  # for rate limiting

    # ------------------------------------------------------------------
    # Public API — Search
    # ------------------------------------------------------------------
    def search_links(self, query: str, max_results: int = 6) -> List[Dict[str, str]]:
        """Call s.jina.ai and return up to ``max_results`` SERP links.

        Uses ``X-Respond-With: no-content`` so Jina only returns the SERP
        (URLs + titles), not the page bodies — much faster.

        Returns:
            List of ``{"url": str, "title": str, "description": str}``.
            Empty list on failure.
        """
        if not query or not query.strip():
            logger.error("[Jina] Empty search query")
            return []

        limit = max(1, min(int(max_results), MAX_SEARCH_RESULTS))

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "X-Respond-With": "no-content",
            }
            search_url = f"{self.search_base}/{quote(query)}"

            response = requests.get(
                search_url, headers=headers, timeout=DEFAULT_TIMEOUT
            )
            if response.status_code != 200:
                logger.error(
                    "[Jina] Search failed (%s): %s",
                    response.status_code,
                    response.text[:300],
                )
                st.error(f"Search failed: {response.text[:300]}")
                return []

            payload = response.json()
            raw_results = payload.get("data", [])
            if not isinstance(raw_results, list) or not raw_results:
                logger.warning("[Jina] No SERP results for query: %s", query)
                return []

            links: List[Dict[str, str]] = []
            for item in raw_results[:limit]:
                url = item.get("url") or item.get("link")
                if not url:
                    continue
                links.append(
                    {
                        "url": url,
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                    }
                )
            return links

        except requests.exceptions.Timeout:
            st.error("Search request timeout.")
            return []
        except requests.exceptions.RequestException as exc:
            logger.exception("[Jina] Search request error: %s", exc)
            st.error(f"Search request error: {exc}")
            return []
        except json.JSONDecodeError:
            st.error("Failed to parse search response from Jina.")
            return []
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Jina] Unexpected error in search_links: %s", exc)
            st.error(f"Unexpected error in search: {exc}")
            return []

    # ------------------------------------------------------------------
    # Public API — Extraction
    # ------------------------------------------------------------------
    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch and extract content from a single URL via r.jina.ai.

        Enforces a 1-second gap between reader calls to respect rate limits.
        Rejects pages flagged with CAPTCHA warnings or whose text matches
        known human-verification phrases.

        Returns:
            ``{"title", "content", "url", "description"}`` or ``None``.
        """
        if not url or not url.strip():
            st.error("Empty URL passed to extract_from_url().")
            return None

        # Rate limit (skip wait on the very first call)
        if self._last_reader_call > 0:
            elapsed = time.monotonic() - self._last_reader_call
            if elapsed < RATE_LIMIT_SECONDS:
                time.sleep(RATE_LIMIT_SECONDS - elapsed)

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
            reader_url = f"{self.reader_base}/{url}"

            response = requests.get(
                reader_url, headers=headers, timeout=DEFAULT_TIMEOUT
            )
            self._last_reader_call = time.monotonic()

            if response.status_code != 200:
                logger.error(
                    "[Jina] Reader failed (%s) for %s: %s",
                    response.status_code,
                    url,
                    response.text[:300],
                )
                return None

            payload = response.json()
            data = payload.get("data", payload)

            content = data.get("content", "") or ""

            # --- CAPTCHA detection (warning field + content keywords) ---
            if self._is_captcha_content(data, content):
                return None

            if len(content.strip()) < MIN_CONTENT_CHARS:
                logger.warning(
                    "[Jina] Extracted content too short (%d chars, min %d): %s",
                    len(content),
                    MIN_CONTENT_CHARS,
                    url,
                )
                return None

            return {
                "url": url,
                "title": data.get("title", ""),
                "content": content,
                "description": data.get("description", ""),
            }

        except requests.exceptions.Timeout:
            logger.error("[Jina] Reader timeout: %s", url)
            return None
        except requests.exceptions.RequestException as exc:
            logger.exception("[Jina] Reader request error for %s: %s", url, exc)
            return None
        except json.JSONDecodeError:
            logger.error("[Jina] Reader JSON decode error for %s", url)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Jina] Unexpected error reading %s: %s", url, exc)
            return None

    def extract_multiple(
        self, urls: List[str], show_errors: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Extract content from up to ``MAX_MANUAL_URLS`` URLs and merge.

        Args:
            urls: List of URLs (1-5).
            show_errors: Whether to surface per-URL errors to the UI.

        Returns:
            Merged dict ``{"content", "sources"}`` or ``None`` if **all** URLs
            failed.
        """
        if not urls:
            if show_errors:
                st.error("No URLs provided.")
            return None

        # Deduplicate while preserving order
        seen: set = set()
        clean_urls: List[str] = []
        for u in urls:
            u = (u or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            clean_urls.append(u)

        if not clean_urls:
            if show_errors:
                st.error("No valid URLs provided.")
            return None

        if len(clean_urls) > MAX_MANUAL_URLS:
            if show_errors:
                st.warning(
                    f"⚠️ {len(clean_urls)} URLs provided — using the first "
                    f"{MAX_MANUAL_URLS} (max allowed)."
                )
            clean_urls = clean_urls[:MAX_MANUAL_URLS]

        extractions: List[Dict[str, Any]] = []
        for url in clean_urls:
            result = self.extract_from_url(url)
            if result:
                extractions.append(result)
            elif show_errors:
                st.warning(f"⚠️ Could not extract content from: {url}")

        if not extractions:
            if show_errors:
                st.error("❌ No content extracted from any of the provided URLs.")
            return None

        return self.merge_contents(extractions)

    # ------------------------------------------------------------------
    # Public API — Merge
    # ------------------------------------------------------------------
    @staticmethod
    def merge_contents(extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge N extractions into a single content + sources list.

        Returns:
            {
              "content": "<merged text with source separators>",
              "sources": [
                 {"url": "...", "title": "...", "domain": "..."},
                 ...
              ],
            }
        """
        parts: List[str] = []
        sources: List[Dict[str, str]] = []

        for ext in extractions:
            url = ext.get("url", "")
            title = ext.get("title", "") or url
            domain = urlparse(url).netloc or url

            sources.append({"url": url, "title": title, "domain": domain})
            parts.append(f"# Source: {title}\nURL: {url}\n\n{ext.get('content', '')}")

        return {
            "content": "\n\n---\n\n".join(parts),
            "sources": sources,
        }

    # ------------------------------------------------------------------
    # Public API — Combined (auto mode)
    # ------------------------------------------------------------------
    def search_and_extract(
        self, target_point: str, max_results: int = DEFAULT_SEARCH_RESULTS
    ) -> Optional[Dict[str, Any]]:
        """Search + extract top results + merge (auto mode).

        Requests more links than the target source count so that CAPTCHA /
        empty pages can be skipped. Stops extracting as soon as
        ``TARGET_VALID_SOURCES`` valid sources have been collected.

        Returns:
            ``{"content", "sources", "target_point"}`` or ``None``.
        """
        links = self.search_links(target_point, max_results=max_results)
        if not links:
            st.warning("No search results found for this target point.")
            return None

        extractions: List[Dict[str, Any]] = []
        for link in links:
            # Stop once we have enough valid sources.
            if len(extractions) >= TARGET_VALID_SOURCES:
                break

            result = self.extract_from_url(link["url"])
            if result:
                # Prefer SERP title if the reader didn't return one
                if not result.get("title") and link.get("title"):
                    result["title"] = link["title"]
                extractions.append(result)

        if not extractions:
            st.error("❌ Could not extract content from any search result.")
            return None

        merged = self.merge_contents(extractions)
        merged["target_point"] = target_point
        return merged

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_captcha_content(data: Dict[str, Any], content: str) -> bool:
        """Detect CAPTCHA / human-verification pages.

        Checks two signals:
            1. Jina's own ``warning`` field for words like "captcha".
            2. Known CAPTCHA phrases inside the extracted content.

        Returns:
            ``True`` if the page should be rejected.
        """
        # 1) Jina warning field
        warning = str(data.get("warning", "")).lower()
        if "captcha" in warning or "humanity" in warning:
            logger.warning("[Jina] CAPTCHA warning field: %r", warning[:120])
            return True

        # 2) Content keyword check
        content_lower = content.lower()
        for kw in CAPTCHA_KEYWORDS:
            if kw in content_lower:
                logger.warning("[Jina] CAPTCHA keyword %r detected in content", kw)
                return True

        return False


# ============================================
# LOCAL TEST ENTRYPOINT
# ============================================
if __name__ == "__main__":
    service = JinaService()
    result = service.search_and_extract("Python automation Excel")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
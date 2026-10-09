"""
Jina AI service for the does4u admin panel.

Provides two capabilities:
    - search_and_extract(): search the web via s.jina.ai, then extract
      the top result's content via r.jina.ai.
    - extract_from_url():   read a single URL via r.jina.ai.

API reference:
    - Search:    https://s.jina.ai/<query>   (GET, Accept: application/json)
    - Reader:    https://r.jina.ai/<url>     (GET, Accept: application/json)
"""
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
import streamlit as st

logger = logging.getLogger(__name__)


# ============================================
# CONFIG
# ============================================
JINA_SEARCH_BASE = "https://s.jina.ai"
JINA_READER_BASE = "https://r.jina.ai"

DEFAULT_TIMEOUT = 30
MAX_RESULTS_HARD_CAP = 5  # Jina search returns up to 5 entries


class JinaService:
    """Jina AI wrapper: web search + URL content extraction."""

    def __init__(self) -> None:
        """Initialize the Jina client using Streamlit secrets."""
        self.api_key: Optional[str] = st.secrets.get("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("JINA_API_KEY not found in Streamlit secrets")

        self.search_base = JINA_SEARCH_BASE
        self.reader_base = JINA_READER_BASE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search_and_extract(
        self, target_point: str, max_results: int = 1
    ) -> Optional[Dict[str, Any]]:
        """Search the web for ``target_point`` and extract the top result.

        Args:
            target_point: Search query (e.g. "automation excel outreach").
            max_results: How many search hits to consider (Jina returns up to 5).

        Returns:
            Extracted content dict (title, content, source_url, ...) or None.
        """
        results = self._search(target_point, max_results=max_results)
        if not results:
            return None

        source_url = results[0].get("url")
        if not source_url:
            logger.error("[Jina] Search hit had no URL: %s", results[0])
            st.error("No URL found in search results.")
            return None

        extracted = self.extract_from_url(source_url)
        if not extracted:
            return None

        extracted["target_point"] = target_point
        return extracted

    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch and extract the content of a single URL via r.jina.ai.

        Args:
            url: The full URL to read.

        Returns:
            Dict with title, content, source_url, description or None.
        """
        if not url:
            st.error("Empty URL passed to extract_from_url().")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
            # r.jina.ai reads the page at the given URL.
            reader_url = f"{self.reader_base}/{url}"

            response = requests.get(
                reader_url, headers=headers, timeout=DEFAULT_TIMEOUT
            )
            if response.status_code != 200:
                logger.error(
                    "[Jina] Reader failed (%s): %s",
                    response.status_code,
                    response.text[:300],
                )
                st.error(f"Extraction failed: {response.text[:300]}")
                return None

            payload = response.json()
            # r.jina.ai JSON mode returns {"data": {...}} with the page fields.
            data = payload.get("data", payload)

            extracted: Dict[str, Any] = {
                "title": data.get("title", "Untitled"),
                "content": data.get("content", ""),
                "source_url": url,
                "description": data.get("description", ""),
            }

            if not extracted["content"] or len(extracted["content"].strip()) < 100:
                logger.warning("[Jina] Extracted content too short: %s", url)
                st.warning(
                    "Extracted content is too short. Try a different target point."
                )
                return None

            return extracted

        except requests.exceptions.Timeout:
            st.error("Request timeout - Jina service took too long to respond.")
            return None
        except requests.exceptions.RequestException as exc:
            logger.exception("[Jina] Request error: %s", exc)
            st.error(f"Request error: {exc}")
            return None
        except json.JSONDecodeError:
            st.error("Failed to parse response from Jina.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Jina] Unexpected error in extract_from_url: %s", exc)
            st.error(f"Unexpected error in extract_from_url: {exc}")
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _search(
        self, query: str, max_results: int = 1
    ) -> Optional[List[Dict[str, Any]]]:
        """Call s.jina.ai and return a list of search hits.

        s.jina.ai accepts the query as part of the URL path:
            GET https://s.jina.ai/<url-encoded-query>
        and returns JSON when ``Accept: application/json`` is set.
        """
        if not query or not query.strip():
            st.error("Empty search query.")
            return None

        limit = max(1, min(int(max_results), MAX_RESULTS_HARD_CAP))

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            }
            # URL-encode the query for the path.
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
                return None

            payload = response.json()
            # s.jina.ai returns {"data": [ ... ]} in JSON mode.
            results = payload.get("data", [])
            if not isinstance(results, list) or not results:
                st.warning("No search results found for this target point.")
                return None

            return results[:limit]

        except requests.exceptions.Timeout:
            st.error("Search request timeout.")
            return None
        except requests.exceptions.RequestException as exc:
            logger.exception("[Jina] Search request error: %s", exc)
            st.error(f"Search request error: {exc}")
            return None
        except json.JSONDecodeError:
            st.error("Failed to parse search response from Jina.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Jina] Unexpected error in _search: %s", exc)
            st.error(f"Unexpected error in search: {exc}")
            return None


# ============================================
# LOCAL TEST ENTRYPOINT
# ============================================
if __name__ == "__main__":
    service = JinaService()
    result = service.search_and_extract("Python automation Excel")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
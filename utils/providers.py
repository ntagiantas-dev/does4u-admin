"""
Content providers για το does4u admin panel.

v4.0 (D-020): primary-source-only pipeline.
v4.1 (TASK-214-UI): max_sources για Deep Research candidates.
v4.2: snippet propagation (description από Jina, content από Tavily).
v4.3: ημερομηνία δημοσίευσης (`published`), επιλογή νεότερης σελίδας στο
      Restricted Search, πύλη επίσημου domain, επίλυση Google News links,
      πιο συντηρητικός έλεγχος CAPTCHA.
"""
from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


# ============================================
# ΣΤΑΘΕΡΕΣ
# ============================================
STRONG_CAPTCHA_KEYWORDS = [
    "prove your humanity",
    "captcha",
    "are you a robot",
    "not a robot",
    "verify you are human",
]

# v4.3: τα keywords ελέγχονται ΜΟΝΟ σε σύντομο περιεχόμενο. Μια μεγάλη
# σελίδα τεκμηρίωσης που απλώς αναφέρει τη λέξη "captcha" δεν είναι captcha wall.
CAPTCHA_MAX_CONTENT_CHARS = 2000

MIN_CONTENT_CHARS = 500
TARGET_VALID_SOURCES = 1

# v4.3: πόσες υποψήφιες σελίδες εξάγουμε στο Restricted Search (site=...)
# ώστε να διαλέξουμε τη νεότερη. Κοστίζει έως N κλήσεις reader αντί για 1.
RESTRICTED_CANDIDATE_POOL = 4

# Jina specific
JINA_SEARCH_BASE = "https://s.jina.ai"
JINA_READER_BASE = "https://r.jina.ai"
JINA_TIMEOUT = 30
JINA_RATE_LIMIT_SECONDS = 1.0
JINA_MAX_SERP_RESULTS = 20

# Μέγιστο μήκος snippet (για να μη γεμίζει η κάρτα με τεράστιο κείμενο)
MAX_SNIPPET_CHARS = 400


# ============================================
# ΗΜΕΡΟΜΗΝΙΑ ΔΗΜΟΣΙΕΥΣΗΣ (v4.3)
# ============================================
_MONTHS_EN = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december",
        ],
        1,
    )
}
_ISO_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_URL_DATE_RE = re.compile(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:[/_-]|$)")
# π.χ. https://api-docs.deepseek.com/news/news260821  ->  2026-08-21
_NEWS_YYMMDD_RE = re.compile(r"news(\d{2})(\d{2})(\d{2})(?:\D|$)")
_EN_DATE_RE = re.compile(r"\b([A-Z][a-z]+)\s+(\d{1,2}),\s+(20\d{2})\b")


def _iso(y: Any, m: Any, d: Any) -> Optional[str]:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def guess_published_date(
    url: str, content: str = "", provider_value: str = ""
) -> Optional[str]:
    """Εκτίμηση ημερομηνίας δημοσίευσης (YYYY-MM-DD).

    Σειρά: πεδίο provider -> URL -> αρχή του κειμένου.
    ΠΡΟΣΟΧΗ: είναι εκτίμηση, όχι επίσημο μεταδεδομένο. Επιστρέφει None αν
    δεν βρει τίποτα αξιόπιστο.
    """
    if provider_value:
        m = _ISO_DATE_RE.search(provider_value)
        if m:
            found = _iso(*m.groups())
            if found:
                return found
        try:
            from email.utils import parsedate_to_datetime

            return parsedate_to_datetime(provider_value).date().isoformat()
        except (TypeError, ValueError):
            pass

    m = _URL_DATE_RE.search(url or "")
    if m:
        found = _iso(*m.groups())
        if found:
            return found

    m = _NEWS_YYMMDD_RE.search(url or "")
    if m:
        found = _iso(2000 + int(m.group(1)), m.group(2), m.group(3))
        if found:
            return found

    head = (content or "")[:2000]
    m = _ISO_DATE_RE.search(head)
    if m:
        found = _iso(*m.groups())
        if found:
            return found

    m = _EN_DATE_RE.search(head)
    if m and m.group(1).lower() in _MONTHS_EN:
        return _iso(m.group(3), _MONTHS_EN[m.group(1).lower()], m.group(2))

    return None


# ============================================
# ΠΥΛΗ ΠΗΓΗΣ (v4.3)
# ============================================
def resolve_google_news_url(url: str) -> Optional[str]:
    """Επιστρέφει το πραγματικό URL ενός news.google.com/rss/articles/... link.

    Για URL άλλων domains επιστρέφει το ίδιο URL. Αν η αποκωδικοποίηση
    αποτύχει, επιστρέφει None. Χρειάζεται: pip install googlenewsdecoder
    """
    if not url:
        return None
    if "news.google.com" not in urlparse(url).netloc.lower():
        return url
    try:
        from googlenewsdecoder import gnewsdecoder

        res = gnewsdecoder(url, interval=1)
        if isinstance(res, dict) and res.get("status"):
            return res.get("decoded_url")
        logger.warning("Google News decode returned no URL: %r", res)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google News decode failed: %s", exc)
    return None


def is_official_url(url: str, domains: List[str]) -> bool:
    """True αν το host του URL ανήκει σε κάποιο από τα επίσημα domains."""
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return False
    norm = [d.lower().removeprefix("www.") for d in (domains or []) if d]
    return any(host == d or host.endswith("." + d) for d in norm)


# ============================================
# ABSTRACT BASE
# ============================================
class ContentProvider(ABC):
    """Abstract base για content providers."""

    name: str = "base"

    @abstractmethod
    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Εξαγωγή περιεχομένου από ένα URL.

        Επιστρέφει:
            {"url": str, "title": str, "content": str,
             "snippet": str, "published": Optional[str]} ή None σε αποτυχία.
        """

    @abstractmethod
    def search_and_extract(
        self,
        target_point: str,
        max_results: int = 6,
        site: Optional[str] = None,
        max_sources: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Αναζήτηση + εξαγωγή περιεχομένου.

        Args:
            target_point: Το query.
            max_results: Μέγιστα SERP hits.
            site: Προαιρετικό domain για περιορισμό (v4.0).
            max_sources: Override του TARGET_VALID_SOURCES.

        Επιστρέφει:
            {
                "target_point": str,
                "sources": List[{
                    "url": str, "title": str, "domain": str,
                    "snippet": str,    # v4.2 — μικρή περίληψη
                    "published": str,  # v4.3 — YYYY-MM-DD ή ""
                }],
                "content": str,
            }
            ή None.
        """

    # ------------------------------------------------------------------
    # Κοινά helpers
    # ------------------------------------------------------------------
    @staticmethod
    def merge_extractions(
        extractions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Συνένωση N extractions σε ένα content blob + λίστα sources.

        v4.2: διατηρεί το `snippet` αν υπάρχει στο extraction.
        v4.3: διατηρεί το `published` αν υπάρχει στο extraction.
        """
        parts: List[str] = []
        sources: List[Dict[str, str]] = []

        for ext in extractions:
            url = ext.get("url", "")
            title = ext.get("title", "") or url
            domain = urlparse(url).netloc.lower() if url else ""
            snippet = ext.get("snippet", "") or ""
            published = ext.get("published", "") or ""

            # Περιορισμός snippet
            if snippet and len(snippet) > MAX_SNIPPET_CHARS:
                snippet = snippet[:MAX_SNIPPET_CHARS].rstrip() + "…"

            sources.append(
                {
                    "url": url,
                    "title": title,
                    "domain": domain,
                    "snippet": snippet,
                    "published": published,
                }
            )
            parts.append(f"# Source: {title}\nURL: {url}\n\n{ext.get('content', '')}")

        return {
            "content": "\n\n---\n\n".join(parts),
            "sources": sources,
        }

    @staticmethod
    def pick_newest(
        extractions: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        """Ταξινόμηση κατά `published` (νεότερα πρώτα) και περικοπή σε `limit`.

        Items χωρίς ημερομηνία πηγαίνουν τελευταία. Η ταξινόμηση είναι
        σταθερή: σε ισοβαθμία μένει η σειρά συνάφειας του SERP.
        """
        ordered = sorted(
            extractions, key=lambda e: e.get("published") or "", reverse=True
        )
        return ordered[: max(1, limit)]

    @staticmethod
    def is_captcha_content(
        data: Dict[str, Any],
        content: str,
        provider_name: str = "provider",
    ) -> bool:
        """Ανίχνευση CAPTCHA (ισχυρά σήματα).

        v4.3: τα keywords ελέγχονται μόνο όταν το περιεχόμενο είναι σύντομο,
        ώστε να μην απορρίπτονται κανονικές σελίδες που αναφέρουν τη λέξη.
        """
        warning = str(data.get("warning", "")).lower()
        if "captcha" in warning or "humanity" in warning:
            logger.warning(
                "[%s] CAPTCHA warning field: %r", provider_name, warning[:120]
            )
            return True

        if len(content) > CAPTCHA_MAX_CONTENT_CHARS:
            return False

        content_lower = content.lower()
        for kw in STRONG_CAPTCHA_KEYWORDS:
            if kw in content_lower:
                logger.warning(
                    "[%s] CAPTCHA keyword %r detected", provider_name, kw
                )
                return True
        return False


# ============================================
# JINA PROVIDER
# ============================================
class JinaProvider(ContentProvider):
    """Jina AI provider."""

    name = "jina"

    def __init__(
        self,
        search_helper: Optional[Callable[[str, int], List[Dict[str, str]]]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._search_helper = search_helper
        self._api_key = api_key
        self._last_reader_call: float = 0.0

    def _get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        import streamlit as st

        key = st.secrets.get("JINA_API_KEY")
        if not key:
            raise ValueError("JINA_API_KEY not found in Streamlit secrets")
        self._api_key = key
        return key

    def _internal_search(
        self, target_point: str, max_results: int = 6
    ) -> List[Dict[str, str]]:
        """Κλήση s.jina.ai και επιστροφή SERP links.

        Κάθε link περιέχει url + title + description (snippet).
        """
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

            cap = max(1, min(int(max_results), JINA_MAX_SERP_RESULTS))

            links: List[Dict[str, str]] = []
            for item in raw[:cap]:
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

    def extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        import requests

        if not url or not url.strip():
            return None

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

            # Το description από τον reader μπορεί να είναι snippet, αν λείπει
            # θα το συμπληρώσουμε από το SERP στο search_and_extract.
            return {
                "url": url,
                "title": data.get("title", "") or url,
                "content": content,
                "snippet": data.get("description", "") or "",
                # v4.3: το publishedTime το επιστρέφει ο reader όταν το βρίσκει
                "published": guess_published_date(
                    url, content, str(data.get("publishedTime", "") or "")
                )
                or "",
            }

        except Exception as exc:  # noqa: BLE001
            logger.exception("[jina] Reader error for %s: %s", url, exc)
            return None

    def search_and_extract(
        self,
        target_point: str,
        max_results: int = 6,
        site: Optional[str] = None,
        max_sources: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        query = f"site:{site} {target_point}" if site else target_point

        target_sources = (
            max_sources if max_sources is not None else TARGET_VALID_SOURCES
        )
        # v4.3: στο Restricted Search (site=...) εξάγουμε περισσότερες
        # υποψήφιες σελίδες και κρατάμε τις νεότερες.
        pool = max(target_sources, RESTRICTED_CANDIDATE_POOL) if site else target_sources

        search_fn = self._search_helper or self._internal_search
        links = search_fn(query, max_results)
        if not links:
            logger.warning("[jina] No SERP results for %r", query)
            return None

        extractions: List[Dict[str, Any]] = []
        for link in links:
            if len(extractions) >= pool:
                break
            result = self.extract_from_url(link["url"])
            if result:
                if not result.get("title") and link.get("title"):
                    result["title"] = link["title"]
                # v4.2: snippet από SERP description (αν δεν το έχει ήδη ο reader)
                if not result.get("snippet") and link.get("description"):
                    result["snippet"] = link["description"]
                extractions.append(result)

        if not extractions:
            return None

        extractions = self.pick_newest(extractions, target_sources)

        merged = self.merge_extractions(extractions)
        merged["target_point"] = target_point
        return merged


# ============================================
# TAVILY PROVIDER
# ============================================
class TavilyProvider(ContentProvider):
    """Tavily provider (search + extract σε ένα API call)."""

    name = "tavily"

    def __init__(self, api_key: Optional[str] = None) -> None:
        try:
            from tavily import TavilyClient  # noqa: F401 (lazy import)
        except ImportError as exc:
            raise RuntimeError(
                "tavily-python is not installed. Run: pip install tavily-python"
            ) from exc

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
        key = os.getenv("TAVILY_API_KEY")
        if key:
            return key
        try:
            import streamlit as st

            return st.secrets.get("TAVILY_API_KEY")
        except Exception:  # noqa: BLE001
            return None

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

            # v4.2: snippet από τα πρώτα 400 chars του content
            snippet = content[:MAX_SNIPPET_CHARS].rstrip() + (
                "…" if len(content) > MAX_SNIPPET_CHARS else ""
            )

            final_url = r.get("url", url)
            return {
                "url": final_url,
                "title": r.get("title", "") or url,
                "content": content,
                "snippet": snippet,
                # v4.3
                "published": guess_published_date(final_url, content) or "",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("[tavily] Extract error for %s: %s", url, exc)
            return None

    def search_and_extract(
        self,
        target_point: str,
        max_results: int = 6,
        site: Optional[str] = None,
        max_sources: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        target_sources = (
            max_sources if max_sources is not None else TARGET_VALID_SOURCES
        )
        pool = max(target_sources, RESTRICTED_CANDIDATE_POOL) if site else target_sources

        kwargs: Dict[str, Any] = {
            "max_results": max_results,
            "include_raw_content": True,
        }
        if site:
            kwargs["include_domains"] = [site]

        try:
            response = self._client.search(target_point, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[tavily] Search error: %s", exc)
            return None

        results = response.get("results", []) if isinstance(response, dict) else []
        if not results:
            logger.warning("[tavily] No results for %r (site=%r)", target_point, site)
            return None

        extractions: List[Dict[str, Any]] = []
        for r in results:
            if len(extractions) >= pool:
                break
            content = (r.get("raw_content") or r.get("content") or "").strip()
            if len(content) < MIN_CONTENT_CHARS:
                continue

            # v4.2: snippet — προτιμάμε το content (είναι ήδη σύντομο στο SERP),
            # αλλιώς τα πρώτα 400 chars του raw_content.
            snippet = r.get("content") or ""
            if not snippet and content:
                snippet = content[:MAX_SNIPPET_CHARS].rstrip() + (
                    "…" if len(content) > MAX_SNIPPET_CHARS else ""
                )
            if snippet and len(snippet) > MAX_SNIPPET_CHARS:
                snippet = snippet[:MAX_SNIPPET_CHARS].rstrip() + "…"

            result_url = r.get("url", "")
            extractions.append(
                {
                    "url": result_url,
                    "title": r.get("title", "") or result_url,
                    "content": content,
                    "snippet": snippet,
                    # v4.3: το published_date υπάρχει μόνο σε news αποτελέσματα
                    "published": guess_published_date(
                        result_url, content, str(r.get("published_date", "") or "")
                    )
                    or "",
                }
            )

        if not extractions:
            return None

        extractions = self.pick_newest(extractions, target_sources)

        merged = self.merge_extractions(extractions)
        merged["target_point"] = target_point
        return merged


# ============================================
# FACTORY
# ============================================
def get_provider(
    name: Optional[str] = None, **kwargs: Any
) -> ContentProvider:
    """Επιστροφή ContentProvider instance."""
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
    "guess_published_date",
    "resolve_google_news_url",
    "is_official_url",
    "STRONG_CAPTCHA_KEYWORDS",
    "CAPTCHA_MAX_CONTENT_CHARS",
    "MIN_CONTENT_CHARS",
    "TARGET_VALID_SOURCES",
    "RESTRICTED_CANDIDATE_POOL",
    "JINA_MAX_SERP_RESULTS",
    "MAX_SNIPPET_CHARS",
]
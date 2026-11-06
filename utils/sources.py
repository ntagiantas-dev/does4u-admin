"""
Μητρώο πηγών εταιριών.

Διαβάζει το `config/sources.yaml`, το επικυρώνει και εκθέτει Company
dataclasses στην υπόλοιπη εφαρμογή (article_generator, admin_tab, poll_feeds).

Το YAML είναι η μοναδική πηγή αλήθειας για:
    - Ποιες εταιρίες θεωρούνται πρωτογενείς πηγές (D-020).
    - Ποια domains επιτρέπονται για restricted search.
    - Ποια RSS feeds (αν υπάρχουν) μπορούμε να διαβάσουμε.
    - Αν υπάρχει Google News RSS fallback (για εταιρίες χωρίς δικό τους RSS).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ============================================
# ΡΥΘΜΙΣΕΙΣ
# ============================================
# Διαδρομή: <project_root>/config/sources.yaml
SOURCES_FILE = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


# ============================================
# DATACLASS
# ============================================
@dataclass(frozen=True)
class Company:
    """Μια πρωτογενής πηγή AI εταιρίας από το whitelist."""

    key: str
    display_name: str
    domains: List[str] = field(default_factory=list)
    news_page: str = ""
    feeds: List[str] = field(default_factory=list)
    has_rss: bool = False
    # v4.0: fallback σε Google News RSS όταν has_rss=false
    google_news_fallback: bool = False

    @property
    def primary_domain(self) -> Optional[str]:
        """Το πρώτο domain στη λίστα, για restricted search."""
        return self.domains[0] if self.domains else None


# ============================================
# ΚΑΤΑΣΤΑΣΗ MODULE
# ============================================
_cache: Optional[Dict[str, Company]] = None


# ============================================
# ΔΗΜΟΣΙΟ API
# ============================================
def load_sources(path: Optional[Path] = None) -> Dict[str, Company]:
    """Φόρτωση και επικύρωση εταιριών από το sources.yaml.

    Args:
        path: Προαιρετικό override. Default: config/sources.yaml.

    Returns:
        Mapping από company key -> Company.

    Raises:
        FileNotFoundError: Αν το YAML δεν υπάρχει.
        ValueError: Αν το αρχείο είναι malformed.
    """
    global _cache
    if _cache is not None and path is None:
        return _cache

    file_path = Path(path) if path is not None else SOURCES_FILE
    if not file_path.exists():
        raise FileNotFoundError(f"sources.yaml not found at {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_companies = data.get("companies") or {}
    if not isinstance(raw_companies, dict) or not raw_companies:
        raise ValueError(
            f"Malformed sources.yaml: missing or empty 'companies' block "
            f"in {file_path}"
        )

    companies: Dict[str, Company] = {}
    for key, cfg in raw_companies.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Invalid company entry {key!r}: expected a mapping")

        display_name = cfg.get("display_name") or key
        domains = cfg.get("domains") or []
        feeds = cfg.get("feeds") or []

        if not isinstance(domains, list):
            raise ValueError(f"Company {key!r}: 'domains' must be a list")
        if not isinstance(feeds, list):
            raise ValueError(f"Company {key!r}: 'feeds' must be a list")

        companies[key] = Company(
            key=key,
            display_name=str(display_name),
            domains=[str(d) for d in domains],
            news_page=str(cfg.get("news_page") or ""),
            feeds=[str(f) for f in feeds],
            has_rss=bool(cfg.get("has_rss", False)),
            # v4.0: νέο πεδίο — fallback σε Google News RSS
            google_news_fallback=bool(cfg.get("google_news_fallback", False)),
        )

    logger.info("[sources] Loaded %d companies from %s", len(companies), file_path)

    if path is None:
        _cache = companies
    return companies


def get_company(key: str) -> Company:
    """Lookup μιας εταιρίας by key.

    Raises:
        ValueError: Αν το key δεν είναι εγγεγραμμένο.
    """
    companies = load_sources()
    if key not in companies:
        raise ValueError(
            f"Unknown company {key!r}. Valid: {sorted(companies.keys())}"
        )
    return companies[key]


def list_companies() -> List[Company]:
    """Επιστροφή όλων των εταιριών, ταξινομημένες κατά display_name."""
    return sorted(load_sources().values(), key=lambda c: c.display_name.lower())


__all__ = [
    "Company",
    "load_sources",
    "get_company",
    "list_companies",
    "SOURCES_FILE",
]
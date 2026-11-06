"""
Company source registry.

Loads `config/sources.yaml`, validates it, and exposes Company dataclasses
to the rest of the pipeline (article_generator, admin_tab, poll_feeds).

The YAML file is the single source of truth for:
    - Which companies we consider primary sources (D-020).
    - Which domains are allowed for restricted search.
    - Which RSS feeds (if any) we can poll.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ============================================
# CONFIG
# ============================================
# Path resolution: <project_root>/config/sources.yaml
SOURCES_FILE = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


# ============================================
# DATACLASS
# ============================================
@dataclass(frozen=True)
class Company:
    """A primary-source AI company from the whitelist."""

    key: str
    display_name: str
    domains: List[str] = field(default_factory=list)
    news_page: str = ""
    feeds: List[str] = field(default_factory=list)
    has_rss: bool = False

    @property
    def primary_domain(self) -> Optional[str]:
        """The first domain in the list, used for restricted search."""
        return self.domains[0] if self.domains else None


# ============================================
# MODULE STATE
# ============================================
_cache: Optional[Dict[str, Company]] = None


# ============================================
# PUBLIC API
# ============================================
def load_sources(path: Optional[Path] = None) -> Dict[str, Company]:
    """Load and validate companies from sources.yaml.

    Args:
        path: Optional override. Defaults to config/sources.yaml.

    Returns:
        Mapping of company key -> Company.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If the file is malformed.
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
        )

    logger.info("[sources] Loaded %d companies from %s", len(companies), file_path)

    if path is None:
        _cache = companies
    return companies


def get_company(key: str) -> Company:
    """Look up a single company by key.

    Raises:
        ValueError: If the key is not registered.
    """
    companies = load_sources()
    if key not in companies:
        raise ValueError(
            f"Unknown company {key!r}. Valid: {sorted(companies.keys())}"
        )
    return companies[key]


def list_companies() -> List[Company]:
    """Return all companies, sorted by display_name (stable order)."""
    return sorted(load_sources().values(), key=lambda c: c.display_name.lower())


__all__ = [
    "Company",
    "load_sources",
    "get_company",
    "list_companies",
    "SOURCES_FILE",
]
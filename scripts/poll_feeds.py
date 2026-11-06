"""
Poll RSS feeds from config/sources.yaml and write recent items to
watchlist_queue.json.

Usage (from project root):
    python scripts/poll_feeds.py

Only items published within the last MAX_AGE_HOURS are kept. Items are
deduplicated by URL. The output file is consumed by the Streamlit UI in
RSS ingestion mode.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path when running as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser is not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

from utils.sources import Company, list_companies  # noqa: E402


# ============================================
# CONFIG
# ============================================
QUEUE_FILE = _PROJECT_ROOT / "watchlist_queue.json"
MAX_AGE_HOURS = 48
SUMMARY_MAX_CHARS = 1000


# ============================================
# HELPERS
# ============================================
def _parse_published(entry: Any) -> Optional[datetime]:
    """Extract a timezone-aware publish date from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _poll_company(company: Company, cutoff: datetime) -> List[Dict[str, Any]]:
    """Fetch all feeds for a company and return recent items."""
    if not company.has_rss or not company.feeds:
        return []

    items: List[Dict[str, Any]] = []
    for feed_url in company.feeds:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as exc:  # noqa: BLE001
            print(f"    [{company.display_name}] feed error {feed_url}: {exc}")
            continue

        if getattr(feed, "bozo", False):
            print(f"    [{company.display_name}] malformed feed: {feed_url}")

        for entry in getattr(feed, "entries", []) or []:
            published = _parse_published(entry)
            # Keep items without a date (some feeds omit it) or recent ones.
            if published is not None and published < cutoff:
                continue

            url = entry.get("link", "")
            if not url:
                continue

            summary = (entry.get("summary") or "")[:SUMMARY_MAX_CHARS]

            items.append(
                {
                    "company_key": company.key,
                    "company_name": company.display_name,
                    "title": entry.get("title", "").strip(),
                    "url": url,
                    "published_at": published.isoformat() if published else None,
                    "summary": summary,
                    "feed_url": feed_url,
                }
            )
    return items


# ============================================
# MAIN
# ============================================
def main() -> int:
    print(f"Polling feeds (max age {MAX_AGE_HOURS}h)...")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    all_items: List[Dict[str, Any]] = []
    for company in list_companies():
        if not company.has_rss:
            print(f"  {company.display_name:<16} — no RSS configured")
            continue
        print(f"  {company.display_name:<16} — polling {len(company.feeds)} feed(s)")
        items = _poll_company(company, cutoff)
        print(f"    → {len(items)} recent item(s)")
        all_items.extend(items)

    # Deduplicate by URL
    seen_urls: set = set()
    unique: List[Dict[str, Any]] = []
    for item in all_items:
        url = item.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    # Sort newest-first (None dates last)
    unique.sort(
        key=lambda i: i.get("published_at") or "",
        reverse=True,
    )

    QUEUE_FILE.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nWrote {len(unique)} item(s) to {QUEUE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
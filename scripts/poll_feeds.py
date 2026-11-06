"""
Poll RSS feeds + Google News RSS fallback για το does4u admin.

Διορθώσεις v4.0.1:
    - Προσθήκη User-Agent header (αποφυγή μπλοκαρίσματος από sites)
    - Google News: φιλτράρουμε με βάση το entry.source, όχι το redirect URL
    - Χρήση requests για κατέβασμα, μετά feedparser.parse()
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Βεβαιωνόμαστε ότι το project root είναι στο sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import feedparser
    import requests
except ImportError:
    print("ERROR: feedparser/requests is not installed.")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)

from utils.sources import Company, list_companies  # noqa: E402


# ============================================
# ΡΥΘΜΙΣΕΙΣ
# ============================================
QUEUE_FILE = _PROJECT_ROOT / "watchlist_queue.json"

MAX_AGE_DAYS = 90
SUMMARY_MAX_CHARS = 1000

# User-Agent — απαραίτητο για πολλά sites
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

GOOGLE_NEWS_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q=site:{domain}&hl=en-US&gl=US&ceid=US:en"
)


# ============================================
# ΒΟΗΘΗΤΙΚΕΣ
# ============================================
def _fetch_feed(url: str) -> Any:
    """Κατέβασμα feed με User-Agent, μετά parsing.

    Χρησιμοποιούμε requests (με headers) αντί για feedparser.parse(url)
    απευθείας, γιατί πολλά sites μπλοκάρουν requests χωρίς User-Agent.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
        return feedparser.parse(response.content)
    except requests.RequestException as exc:
        print(f"    [HTTP error] {url}: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"    [Parse error] {url}: {exc}")
        return None


def _parse_published(entry: Any) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_from_company_domain(url: str, domains: List[str]) -> bool:
    url_domain = _extract_domain(url)
    if not url_domain:
        return False
    for official in domains:
        official = official.lower()
        if url_domain == official or url_domain.endswith("." + official):
            return True
    return False


def _get_entry_source_domain(entry: Any) -> Optional[str]:
    """Εξαγωγή domain από το <source> του entry (Google News).

    Το Google News RSS έχει:
        <source url="https://www.reuters.com">Reuters</source>
    Αυτό είναι το πραγματικό domain, όχι το redirect URL.
    """
    source = getattr(entry, "source", None)
    if source and hasattr(source, "href"):
        return _extract_domain(source.href)
    return None


def _resolve_google_news_url(entry: Any) -> str:
    """Προσπάθεια εξαγωγής πραγματικού URL από Google News entry.

    Το entry.link είναι πάντα redirect (news.google.com/rss/articles/...).
    Δεν μπορούμε να το λύσουμε χωρίς extra request, οπότε το κρατάμε ως έχει.
    Ο χρήστης θα κάνει ένα παραπάνω click, αλλά δουλεύει.
    """
    return entry.get("link", "") or ""


def _poll_company(company: Company, cutoff: datetime) -> List[Dict[str, Any]]:
    """Fetch feeds για μια εταιρία (RSS ή Google News fallback)."""
    feeds_to_poll: List[str] = []

    if company.has_rss and company.feeds:
        feeds_to_poll = company.feeds
        print(f"    → χρήση δικού της RSS ({len(feeds_to_poll)} feed/s)")
    elif getattr(company, "google_news_fallback", False):
        primary = company.primary_domain
        if primary:
            feeds_to_poll = [GOOGLE_NEWS_RSS_TEMPLATE.format(domain=primary)]
            print(f"    → Google News RSS fallback για {primary}")
    else:
        return []

    items: List[Dict[str, Any]] = []
    for feed_url in feeds_to_poll:
        feed = _fetch_feed(feed_url)
        if feed is None:
            print(f"    [{company.display_name}] αδυναμία φόρτωσης: {feed_url}")
            continue

        if getattr(feed, "bozo", False) and not getattr(feed, "entries", None):
            print(f"    [{company.display_name}] malformed feed: {feed_url}")
            continue

        is_google_news = "news.google.com" in feed_url

        for entry in getattr(feed, "entries", []) or []:
            published = _parse_published(entry)
            if published is not None and published < cutoff:
                continue

            if is_google_news:
                # Έλεγχος domain από το entry.source (πραγματικό domain)
                source_domain = _get_entry_source_domain(entry)
                if source_domain and not _is_from_company_domain(
                    f"https://{source_domain}", company.domains
                ):
                    # Είναι aggregator (reuters, techcrunch κλπ) — skip
                    continue
                url = _resolve_google_news_url(entry)
            else:
                url = entry.get("link", "") or ""

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
                    "source": "google_news" if is_google_news else "rss",
                }
            )

    return items


def _load_existing_queue() -> List[Dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        print("⚠️ Το watchlist_queue.json είναι malformed — ξεκινάμε από το μηδέν.")
        return []
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Σφάλμα ανάγνωσης watchlist: {exc} — ξεκινάμε από το μηδέν.")
        return []


# ============================================
# ΚΥΡΙΩΣ
# ============================================
def main() -> int:
    print(f"Polling feeds (max age {MAX_AGE_DAYS} days)...")
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    existing_items = _load_existing_queue()
    existing_urls = {i.get("url") for i in existing_items if i.get("url")}
    print(f"\nΥπάρχοντα items στο queue: {len(existing_items)}")

    new_items: List[Dict[str, Any]] = []
    for company in list_companies():
        print(f"\n  {company.display_name:<16}", end=" ")
        items = _poll_company(company, cutoff)
        if not items and not (
            company.has_rss or getattr(company, "google_news_fallback", False)
        ):
            print("— δεν έχει RSS ή fallback")
        else:
            print(f"→ {len(items)} νέα item(s)")
        new_items.extend(items)

    all_items = existing_items.copy()
    added_count = 0
    for item in new_items:
        url = item.get("url")
        if url and url not in existing_urls:
            all_items.append(item)
            existing_urls.add(url)
            added_count += 1

    print(f"\nΝέα items που προστέθηκαν: {added_count}")

    retained_items: List[Dict[str, Any]] = []
    expired_count = 0
    for item in all_items:
        published_str = item.get("published_at")
        if not published_str:
            retained_items.append(item)
            continue
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            retained_items.append(item)
            continue
        if published >= cutoff:
            retained_items.append(item)
        else:
            expired_count += 1

    print(f"Items που έληξαν (>{MAX_AGE_DAYS} μέρες): {expired_count}")

    retained_items.sort(
        key=lambda i: i.get("published_at") or "",
        reverse=True,
    )

    QUEUE_FILE.write_text(
        json.dumps(retained_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ Εγγράφηκαν {len(retained_items)} item(s) στο {QUEUE_FILE}")
    print(f"   (από τα οποία {added_count} νέα, {len(retained_items) - added_count} υπάρχοντα)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
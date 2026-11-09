"""
Έλεγχος αντικατάστασης (supersession): υπάρχει νεότερη ανακοίνωση για το ίδιο προϊόν;

Κρατά ιστορικό των items που έχει δει το pipeline (company, title, url, published)
και, για μια πηγή, επιστρέφει νεότερα items της ίδιας εταιρείας με κοινό όνομα
προϊόντος. Είναι ευρετικός έλεγχος: δίνει ΥΠΟΨΗΦΙΑ για έλεγχο από άνθρωπο, όχι
αυτόματες αποφάσεις.

ΠΡΟΣΟΧΗ: το ιστορικό γράφεται σε τοπικό JSON. Αν το admin panel τρέχει σε cloud με
εφήμερο δίσκο, ορίσε μέσω SEEN_ITEMS_PATH μια μόνιμη τοποθεσία ή αποθήκευσέ το στη
βάση όπου κρατάς τα drafts.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SEEN_PATH = Path(os.getenv("SEEN_ITEMS_PATH", "seen_items.json"))

_STOP = {
    "the", "and", "for", "with", "new", "release", "preview", "update",
    "updates", "announcing", "introducing", "api", "docs", "now", "available",
}


def _load() -> List[Dict[str, Any]]:
    if not SEEN_PATH.exists():
        return []
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[freshness] Could not read %s: %s", SEEN_PATH, exc)
        return []


def _tokens(text: str, exclude: set) -> set:
    toks = {t.strip(".") for t in re.findall(r"[a-z0-9.]+", (text or "").lower())}
    return {t for t in toks if len(t) > 1 and t not in _STOP and t not in exclude}


def record_items(items: List[Dict[str, Any]]) -> None:
    """Κάλεσέ το κάθε φορά που γεμίζει το watchlist (και για κάθε πηγή που χρησιμοποιείς).

    Κάθε item: {"company", "title", "url", "published" (YYYY-MM-DD)}.
    """
    seen = _load()
    known = {i.get("url") for i in seen}
    changed = False
    for it in items:
        url = it.get("url")
        if url and url not in known:
            seen.append({k: it.get(k, "") for k in ("company", "title", "url", "published")})
            known.add(url)
            changed = True
    if changed:
        SEEN_PATH.write_text(
            json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8"
        )


def find_newer_items(
    company_key: str,
    source_title: str,
    source_date: str,
    company_name: str = "",
) -> List[Dict[str, Any]]:
    """Υποψήφια νεότερα items (max 5, νεότερα πρώτα)."""
    exclude = _tokens(company_name, set()) | {company_key.lower()}
    base = _tokens(source_title, exclude)
    if not base:
        return []
    out: List[Dict[str, Any]] = []
    for it in _load():
        if it.get("company") != company_key or not it.get("published"):
            continue
        if it["published"] <= source_date:  # ISO ημερομηνίες: σύγκριση ως κείμενο
            continue
        overlap = base & _tokens(it.get("title", ""), exclude)
        if any(any(c.isdigit() for c in t) for t in overlap) or len(overlap) >= 2:
            out.append(it)
    return sorted(out, key=lambda i: i["published"], reverse=True)[:5]
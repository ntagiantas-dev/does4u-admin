"""
Pipeline δημιουργίας άρθρου για το does4u admin panel (v4.4).

PRIMARY-SOURCE-ONLY pipeline:
    Fetch -> Cleaner -> Writer -> Teasers -> Sources section -> Checks.

v4.3 (TASK-225): today/source_date στο prompt, πραγματικό word count, όρια teasers.
v4.4:
    - Ημερομηνία πηγής: UI/RSS -> provider (`published`) -> Cleaner.
    - age_days / age_label υπολογίζονται σε Python (όχι από το LLM).
    - Πύλη επίσημου domain + επίλυση Google News links.
    - Source Gate με επικάλυψη λέξεων (όχι ακριβής φράση) και ρητό flag.
    - Έλεγχος αντικατάστασης (utils.freshness) -> `newer_items` στο prompt.
    - Έλεγχοι άρθρου -> `flags` (αριθμοί, παρελθοντικές ημερομηνίες, υπερβολή
      "σύμφωνα με", άγνωστα links) που αποθηκεύονται μέσα στο bundle.
    - Teasers: κοπή σε όριο λέξης και πραγματικό `length`.
"""
import json
import logging
import re
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import streamlit as st
from openai import OpenAI

from utils.prompts import (
    BLOG_CATEGORIES,
    CITATION_INSTRUCTIONS,
    CLEANER_PROMPT,
)

logger = logging.getLogger(__name__)


# ============================================
# ΓΛΩΣΣΕΣ & MODES
# ============================================
LANGUAGE_OPTIONS: Dict[str, Dict[str, str]] = {
    "greek": {"name": "Greek", "native": "Ελληνικά", "code": "el"},
    "english": {"name": "English", "native": "English", "code": "en"},
}

INGESTION_MODE_RSS = "RSS (today's items)"
INGESTION_MODE_RESTRICTED = "Restricted Search"
INGESTION_MODE_MANUAL = "Manual URL"
INGESTION_MODE_CUSTOM = "Custom Idea (Growth Hack)"
INGESTION_MODES = [
    INGESTION_MODE_RSS,
    INGESTION_MODE_RESTRICTED,
    INGESTION_MODE_MANUAL,
    INGESTION_MODE_CUSTOM,
]

# Σε αυτά τα modes, πηγή εκτός επίσημων domains ΜΠΛΟΚΑΡΕΙ το pipeline.
# Στο Manual URL απλώς προειδοποιεί (ο χρήστης διάλεξε ρητά το URL).
STRICT_DOMAIN_MODES = {INGESTION_MODE_RSS, INGESTION_MODE_RESTRICTED}

# ============================================
# ΜΟΝΤΕΛΑ
# ============================================
CLEANER_MODEL = "gpt-5.6-luna"
WRITER_MODEL = "gpt-5.6-sol"
TEASER_MODEL = "gpt-5.6-luna"
TEASER_FALLBACK_MODEL = "gpt-4o-mini"

CLEANER_MAX_TOKENS = 4000
WRITER_MAX_TOKENS = 8000
TEASER_MAX_TOKENS = 8000
TEASER_FALLBACK_MAX_TOKENS = 1000

EMPTY_RESPONSE_RETRY_MULTIPLIER = 2

MAX_RAW_CONTENT_CHARS = 12000
MAX_CLEANED_CONTENT_CHARS = 6000
FALLBACK_RAW_CONTENT_CHARS = 4000

# ============================================
# ΚΑΝΟΝΕΣ ΕΛΕΓΧΩΝ
# ============================================
OLD_SOURCE_DAYS = 30           # πάνω από αυτό: προειδοποίηση παλιάς πηγής
DATE_MISMATCH_DAYS = 3         # RSS vs σελίδα: ανοχή ημερών
SOURCE_GATE_THRESHOLD = 0.6    # ποσοστό λέξεων θέματος που πρέπει να υπάρχει στην πηγή
MAX_ATTRIBUTIONS = 6           # "σύμφωνα με..." ανά άρθρο
TEASER_LIMITS = {"twitter": 280, "linkedin": 300, "facebook": 150}

GR_MONTHS = [
    "Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
    "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου",
]
EN_MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]
_GR_MONTH_NUM = {m: i for i, m in enumerate(GR_MONTHS, 1)}
_EN_MONTH_NUM = {m: i for i, m in enumerate(EN_MONTHS, 1)}

_GR_DATE_RE = re.compile(
    r"(\d{1,2})(?:ης|η|ο)?\s+(" + "|".join(GR_MONTHS) + r")\s+(\d{4})"
)
_EN_DATE_RE = re.compile(
    r"(" + "|".join(EN_MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})"
)
_FUTURE_RE = re.compile(
    r"προγραμματ|έγκαιρα|\bθα\b|πριν από|μέχρι|έως|"
    r"\bwill\b|upcoming|\bbefore\b|\buntil\b|\bby\b",
    re.IGNORECASE,
)
_PAST_OK_RE = re.compile(
    r"παρέλθ|έληξε|έχει λήξει|αποσύρθηκ|has passed|expired|was retired|already passed",
    re.IGNORECASE,
)
_ATTRIB_RE = re.compile(
    r"σύμφωνα με|όπως (?:αναφέρ|καταγράφ|διευκρινίζ|επιβεβαι)|βάσει|"
    r"according to|as stated|as reported",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


# ============================================
# ΗΜΕΡΟΜΗΝΙΕΣ
# ============================================
def _safe_date(y: Any, m: Any, d: Any) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Βρίσκει ημερομηνία YYYY-MM-DD μέσα σε κείμενο. None αν δεν υπάρχει."""
    if not value:
        return None
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", str(value))
    return _safe_date(*m.groups()) if m else None


def _today() -> date:
    """Σημερινή ημερομηνία στην Αθήνα (ο server συνήθως τρέχει σε UTC)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Athens")).date()
    except Exception:  # noqa: BLE001
        return date.today()


def format_date(d: date, language: str = "Greek") -> str:
    """Ανθρώπινη ημερομηνία ανά γλώσσα (χωρίς εξάρτηση από locale)."""
    if (language or "").strip().lower() == "greek":
        return f"{d.day} {GR_MONTHS[d.month - 1]} {d.year}"
    return f"{EN_MONTHS[d.month - 1]} {d.day}, {d.year}"


def describe_age(age_days: Optional[int]) -> str:
    if age_days is None:
        return "άγνωστη"
    if age_days < 0:
        return "μελλοντική ημερομηνία — έλεγξέ την"
    if age_days < OLD_SOURCE_DAYS:
        return f"{age_days} ημέρες"
    return f"{age_days} ημέρες (περίπου {age_days // 30} μήνες)"


# ============================================
# FLAGS
# ============================================
def make_flag(level: str, code: str, message: str) -> Dict[str, str]:
    """level: 'error' | 'warn' | 'info'."""
    return {"level": level, "code": code, "message": message}


# ============================================
# ΕΛΕΓΧΟΙ ΚΕΙΜΕΝΟΥ (καθαρές συναρτήσεις, χωρίς Streamlit)
# ============================================
def count_words(markdown: str) -> int:
    """Πραγματικός αριθμός λέξεων: χωρίς URLs, Sources και διαχωριστικά πινάκων."""
    text = markdown.split("## Sources")[0]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^\s*\|?[\s:|\-]+\|?\s*$", " ", text, flags=re.MULTILINE)
    tokens = re.findall(r"[^\s|#*>_`]+", text)
    return sum(1 for t in tokens if any(c.isalnum() for c in t))


# Γενικές λέξεις που δεν δείχνουν το πραγματικό θέμα (δεν μετρούν στην πύλη)
_TOPIC_STOP = {
    "the", "and", "for", "with", "new", "release", "launch", "update", "updates",
    "announcement", "announces", "news", "api", "docs", "version", "preview",
    "νέο", "νέα", "νέος", "ανακοίνωση", "κυκλοφορία", "έκδοση", "ενημέρωση",
}


def topic_in_source(topic: str, content: str, threshold: float = SOURCE_GATE_THRESHOLD) -> bool:
    """True αν αρκετές ΟΥΣΙΑΣΤΙΚΕΣ λέξεις του θέματος εμφανίζονται στην πηγή."""
    words = [
        w for w in re.findall(r"\w+", (topic or "").lower())
        if len(w) > 2 and w not in _TOPIC_STOP
    ]
    if not words:
        return True
    text = (content or "").lower()
    return sum(1 for w in words if w in text) / len(words) >= threshold


def _number_tokens(text: str) -> Dict[str, str]:
    """Αριθμοί -> κανονικοποιημένο κλειδί (μόνο ψηφία, ίδιο για 1,6 / 1.6 / 1.048.576)."""
    text = re.sub(r"\]\(https?://[^)\s]*\)", "]", text)
    text = re.sub(r"https?://\S+", " ", text)
    tokens: Dict[str, str] = {}
    for m in _NUM_RE.findall(text):
        norm = re.sub(r"\D", "", m).lstrip("0") or "0"
        tokens.setdefault(norm, m)
    return tokens


def find_unsupported_numbers(article_text: str, source_text: str) -> List[str]:
    """Αριθμοί (>10) του άρθρου που δεν υπάρχουν στο υλικό της πηγής."""
    art = _number_tokens(article_text)
    src = _number_tokens(source_text)
    return sorted(
        original
        for norm, original in art.items()
        if norm not in src and int(norm) > 10
    )


def find_stale_date_sentences(body: str, today: date) -> List[str]:
    """Προτάσεις με ημερομηνία που έχει ήδη περάσει αλλά μελλοντική διατύπωση."""
    flagged: List[str] = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", body):
        if not sent.strip() or not _FUTURE_RE.search(sent) or _PAST_OK_RE.search(sent):
            continue
        found = False
        for d, m, y in _GR_DATE_RE.findall(sent):
            dt = _safe_date(y, _GR_MONTH_NUM[m], d)
            if dt and dt < today:
                found = True
                break
        if not found:
            for m, d, y in _EN_DATE_RE.findall(sent):
                dt = _safe_date(y, _EN_MONTH_NUM[m], d)
                if dt and dt < today:
                    found = True
                    break
        if found:
            flagged.append(sent.strip()[:160])
    return flagged


def count_attributions(body: str) -> int:
    return len(_ATTRIB_RE.findall(body))


def _norm_url(u: str) -> str:
    return u.split("#")[0].rstrip("/")


def count_inline_links(body: str) -> int:
    return len(_MD_LINK_RE.findall(body))


def find_foreign_links(body: str, sources: List[Dict[str, str]]) -> List[str]:
    """Inline links που ΔΕΝ ανήκουν στις διαθέσιμες πηγές (πιθανό εφευρημένο URL)."""
    allowed = {_norm_url(s.get("url", "")) for s in sources if s.get("url")}
    return [u for u in _MD_LINK_RE.findall(body) if _norm_url(u) not in allowed]


# ============================================
# TEASERS HELPERS
# ============================================
def _fit(text: str, limit: int) -> str:
    """Κοπή σε όριο χαρακτήρων, κατά το δυνατόν στο όριο λέξης."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def normalize_teasers(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Εξασφαλίζει {twitter, linkedin, facebook} με σωστά όρια και πραγματικό length."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, limit in TEASER_LIMITS.items():
        entry = result.get(key)
        text = entry.get("text", "") if isinstance(entry, dict) else str(entry or "")
        text = _fit(text, limit)
        out[key] = {"text": text, "length": len(text)}
    return out


# ============================================
# MODULE HELPERS
# ============================================
def generate_fallback_teasers(article_text: str) -> Dict[str, Dict[str, Any]]:
    """Fallback teasers από τις πρώτες προτάσεις."""
    sentences = [s.strip() for s in article_text.split(".") if s.strip()]
    first = ". ".join(sentences[:2]) + "." if sentences else ""
    if not first:
        first = "Read our latest article."
    return normalize_teasers(
        {k: {"text": first} for k in TEASER_LIMITS}
    )


def append_sources_section(
    article_markdown: str, sources: List[Dict[str, str]]
) -> str:
    """Προσάρτηση ## Sources section, αντικαθιστώντας τυχόν υπάρχον."""
    if "## Sources" in article_markdown:
        idx = article_markdown.find("## Sources")
        article_markdown = article_markdown[:idx].rstrip()

    if not sources:
        return article_markdown

    lines: List[str] = ["## Sources"]
    for s in sources:
        title = s.get("title") or s.get("url", "Source")
        url = s.get("url", "")
        if not url:
            continue
        lines.append(f"- [{title}]({url})")

    if len(lines) == 1:
        return article_markdown

    return article_markdown.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def check_hallucinations(article_text: str, source_text: str) -> None:
    """Συμβατότητα με παλιό κώδικα: εμφανίζει warning για αριθμούς εκτός πηγής.

    Στο νέο pipeline χρησιμοποιείται το find_unsupported_numbers + flags.
    """
    for num in find_unsupported_numbers(article_text, source_text):
        st.warning(f"⚠️ Προσοχή: Ο αριθμός {num} δεν βρέθηκε στην πηγή!")


# ============================================
# ΚΥΡΙΑ ΚΛΑΣΗ
# ============================================
class ArticleGenerator:
    """Pipeline δημιουργίας άρθρου (primary-source-only, v4.4)."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = st.secrets.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Streamlit secrets")
        self.client: OpenAI = OpenAI(api_key=self.api_key)

    @staticmethod
    def resolve_languages(selection: str) -> List[Dict[str, str]]:
        sel = (selection or "").strip().lower()
        if sel in ("both", "bilingual", "el+en", "gr+en"):
            return [LANGUAGE_OPTIONS["greek"], LANGUAGE_OPTIONS["english"]]
        if sel in ("greek", "gr", "el", "ελληνικά"):
            return [LANGUAGE_OPTIONS["greek"]]
        if sel in ("english", "en", "αγγλικά"):
            return [LANGUAGE_OPTIONS["english"]]
        logger.warning("Unknown language %r — default Greek", selection)
        return [LANGUAGE_OPTIONS["greek"]]

    @staticmethod
    def get_category_config(category: str) -> Dict[str, Any]:
        if category not in BLOG_CATEGORIES:
            raise ValueError(
                f"Unknown category {category!r}. "
                f"Valid: {list(BLOG_CATEGORIES.keys())}"
            )
        return BLOG_CATEGORIES[category]

    @staticmethod
    def _resolve_provider_name() -> Optional[str]:
        try:
            return st.session_state.get("content_provider")
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------
    def _call_llm(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int,
        stage: str,
    ) -> Optional[str]:
        try:
            response = self.client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                retry_tokens = max_tokens * EMPTY_RESPONSE_RETRY_MULTIPLIER
                logger.warning(
                    "[%s] Empty response from %s — retry with %d tokens",
                    stage, model, retry_tokens,
                )
                response = self.client.chat.completions.create(
                    model=model,
                    max_completion_tokens=retry_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    logger.error("[%s] Empty response from %s after retry", stage, model)
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
        stage: str,
        max_retries: int = 1,
    ) -> Optional[Dict[str, Any]]:
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            raw = self._call_llm(
                model=model, prompt=prompt,
                max_tokens=max_tokens, stage=stage,
            )
            if raw is None:
                return None
            parsed = self._parse_json_response(raw, stage=stage)
            if parsed is not None:
                return parsed
            logger.warning("[%s] JSON parse failed (%d/%d)", stage, attempt, attempts)
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
            return None
        prompt = CLEANER_PROMPT.format(
            target_keywords=target_keywords or "(none)",
            raw_content=raw_content[:MAX_RAW_CONTENT_CHARS],
        )
        result = self._call_llm_json(
            model=CLEANER_MODEL, prompt=prompt,
            max_tokens=CLEANER_MAX_TOKENS, stage="Cleaner",
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
    # Stage 2 — Writer
    # ------------------------------------------------------------------
    def generate_article(
        self,
        cleaned_content: str,
        target_point: str,
        category: str,
        key_facts: Optional[List[str]] = None,
        language: str = "Greek",
        sources: Optional[List[Dict[str, str]]] = None,
        source_date: str = "Άγνωστη",
        newer_items: str = "(καμία)",
    ) -> Optional[Dict[str, Any]]:
        """Γράφει το άρθρο.

        source_date: ISO (YYYY-MM-DD) ή "Άγνωστη". Η ηλικία υπολογίζεται εδώ,
        σε Python, και περνά στο prompt ως age_days / age_label.
        Placeholders που δεν υπάρχουν στο prompt της κατηγορίας αγνοούνται.
        """
        if not cleaned_content or not cleaned_content.strip():
            logger.error("[Writer/%s] Empty cleaned content", language)
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

        sources = sources or []
        sources_str = self._format_sources_for_prompt(sources)
        citation_instructions = CITATION_INSTRUCTIONS.format(sources=sources_str)

        today = _today()
        src_dt = parse_iso_date(source_date)
        age_days = (today - src_dt).days if src_dt else None

        prompt = cfg["article_prompt"].format(
            today=format_date(today, language),
            today_iso=today.isoformat(),
            source_date=format_date(src_dt, language) if src_dt else "Άγνωστη",
            source_date_iso=src_dt.isoformat() if src_dt else "unknown",
            age_days=age_days if age_days is not None else "unknown",
            age_label=describe_age(age_days),
            newer_items=newer_items or "(καμία)",
            target_point=target_point,
            category=category,
            language=language,
            cleaned_content=cleaned_content[:MAX_CLEANED_CONTENT_CHARS],
            key_facts=key_facts_str,
            citation_instructions=citation_instructions,
        )

        result = self._call_llm_json(
            model=WRITER_MODEL, prompt=prompt,
            max_tokens=WRITER_MAX_TOKENS,
            stage=f"Writer/{category}/{language}",
        )
        if not result:
            return None

        article_text = result.get("content_markdown", "")
        if not article_text:
            logger.error("[Writer] Missing content_markdown")
            return None

        if not result.get("slug"):
            result["slug"] = self._fallback_slug(result.get("title", ""))

        # Πραγματικό word count / reading time (όχι ό,τι "δηλώνει" το μοντέλο)
        words = count_words(article_text)
        result["word_count"] = words
        result["reading_time_minutes"] = max(1, round(words / 200))

        return result

    # ------------------------------------------------------------------
    # Stage 3 — Teasers
    # ------------------------------------------------------------------
    def generate_social_teasers(
        self,
        title: str,
        category: str,
        keywords: List[str],
        language: str = "Greek",
        article_text: str = "",
    ) -> Dict[str, Dict[str, Any]]:
        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return generate_fallback_teasers(article_text)

        prompt = cfg["teaser_prompt"].format(
            title=title or "(untitled)",
            category=category,
            keywords=", ".join(keywords) if keywords else "(none)",
            language=language,
        )

        def _valid(res: Optional[Dict[str, Any]]) -> bool:
            return bool(res) and all(k in res for k in TEASER_LIMITS)

        result = self._call_llm_json(
            model=TEASER_MODEL, prompt=prompt,
            max_tokens=TEASER_MAX_TOKENS,
            stage=f"Teasers/{category}/{language}",
        )

        if not _valid(result):
            logger.warning(
                "[Teasers/%s/%s] Primary model failed, trying %s",
                category, language, TEASER_FALLBACK_MODEL,
            )
            result = self._call_llm_json(
                model=TEASER_FALLBACK_MODEL, prompt=prompt,
                max_tokens=TEASER_FALLBACK_MAX_TOKENS,
                stage=f"Teasers-fallback/{category}/{language}",
            )

        if not _valid(result):
            return generate_fallback_teasers(article_text)

        return normalize_teasers(result)

    # ------------------------------------------------------------------
    # Έλεγχοι άρθρου -> flags
    # ------------------------------------------------------------------
    @staticmethod
    def _article_checks(
        article_md: str,
        sources: List[Dict[str, str]],
        haystack: str,
        source_date_iso: str,
        age_days: Optional[int],
        today: date,
    ) -> List[Dict[str, str]]:
        flags: List[Dict[str, str]] = []
        body = article_md.split("## Sources")[0]

        # Στο υλικό αναφοράς προσθέτουμε ό,τι υπολογίζει ο ίδιος ο κώδικας
        extra = f" {source_date_iso} {today.isoformat()}"
        if age_days is not None:
            extra += f" {age_days} {age_days // 30}"
        nums = find_unsupported_numbers(body, haystack + extra)
        if nums:
            flags.append(make_flag(
                "warn", "numbers_unsupported",
                "Αριθμοί που δεν βρέθηκαν στην πηγή: " + ", ".join(nums[:12]),
            ))

        stale = find_stale_date_sentences(body, today)
        if stale:
            flags.append(make_flag(
                "warn", "stale_dates",
                "Παρελθοντική ημερομηνία με μελλοντική διατύπωση: " + " | ".join(stale[:3]),
            ))

        attrib = count_attributions(body)
        if attrib > MAX_ATTRIBUTIONS:
            flags.append(make_flag(
                "warn", "attribution_overload",
                f"{attrib} φράσεις τύπου «σύμφωνα με…» (όριο {MAX_ATTRIBUTIONS}).",
            ))

        if sources and count_inline_links(body) == 0:
            flags.append(make_flag(
                "warn", "no_inline_links", "Το άρθρο δεν έχει inline links προς την πηγή."
            ))

        foreign = find_foreign_links(body, sources)
        if foreign:
            flags.append(make_flag(
                "error", "foreign_links",
                "Links που δεν ανήκουν στις πηγές (πιθανό εφευρημένο URL): "
                + ", ".join(foreign[:3]),
            ))
        return flags

    @staticmethod
    def _render_flags(flags: List[Dict[str, str]]) -> None:
        seen = set()
        for f in flags:
            key = (f["code"], f["message"])
            if key in seen:
                continue
            seen.add(key)
            text = f"[{f['code']}] {f['message']}"
            if f["level"] == "error":
                st.error(f"❌ {text}")
            elif f["level"] == "warn":
                st.warning(f"⚠️ {text}")
            else:
                st.info(f"ℹ️ {text}")

    # ------------------------------------------------------------------
    # Ημερομηνία πηγής & έλεγχος αντικατάστασης
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_source_date(
        explicit: Optional[str],
        provider_date: Optional[str],
        cleaner_date: Optional[str],
        flags: List[Dict[str, str]],
    ) -> str:
        """Προτεραιότητα: UI/RSS -> provider (`published`) -> Cleaner. ISO ή ''."""
        ex = parse_iso_date(explicit)
        pv = parse_iso_date(provider_date)
        cl = parse_iso_date(cleaner_date)
        if ex and pv and abs((ex - pv).days) > DATE_MISMATCH_DAYS:
            flags.append(make_flag(
                "warn", "date_mismatch",
                f"Διαφορετικές ημερομηνίες: RSS/UI {ex.isoformat()} vs σελίδα {pv.isoformat()}.",
            ))
        chosen = ex or pv or cl
        return chosen.isoformat() if chosen else ""

    @staticmethod
    def _find_newer(
        company_key: str,
        sources: List[Dict[str, str]],
        source_date: str,
        company_info: Dict[str, Any],
        flags: List[Dict[str, str]],
    ) -> str:
        """Επιστρέφει κείμενο για το prompt ({newer_items}) και προσθέτει flag."""
        if not sources or not source_date:
            return "(καμία)"
        try:
            from utils.freshness import find_newer_items, record_items
        except ImportError:
            logger.info("[Pipeline] utils.freshness missing — supersession check skipped")
            return "(καμία)"
        src = sources[0]
        try:
            record_items([{
                "company": company_key,
                "title": src.get("title", ""),
                "url": src.get("url", ""),
                "published": source_date,
            }])
            newer = find_newer_items(
                company_key, src.get("title", ""), source_date,
                company_info.get("display_name", ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Pipeline] supersession check failed: %s", exc)
            return "(καμία)"
        if not newer:
            return "(καμία)"
        flags.append(make_flag(
            "warn", "newer_items",
            "Νεότερες ανακοινώσεις για το ίδιο προϊόν: "
            + "; ".join(f"{i['published']}: {i['title']}" for i in newer),
        ))
        return "\n".join(
            f"- {i['published']}: {i['title']} ({i['url']})" for i in newer
        )

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def full_pipeline(
        self,
        target_point: str,
        category: str,
        company_key: str,
        ingestion_mode: str = INGESTION_MODE_RESTRICTED,
        feed_item_url: Optional[str] = None,
        language_selection: str = "Greek",
        custom_idea: Optional[str] = None,
        source_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """source_date: ISO ημερομηνία του item από το watchlist/RSS (προαιρετικό)."""
        empty_result: Dict[str, Any] = {
            "cleaner": {},
            "sources": [],
            "company": {},
            "category_slug": "",
            "bundles": [],
            "flags": [],
        }

        try:
            cfg = self.get_category_config(category)
        except ValueError as exc:
            st.error(f"❌ {exc}")
            return empty_result
        empty_result["category_slug"] = cfg["slug"]

        flags: List[Dict[str, str]] = []
        today = _today()
        newer_text = "(καμία)"
        resolved_date = ""

        if ingestion_mode == INGESTION_MODE_CUSTOM:
            if not custom_idea or not custom_idea.strip():
                st.error("❌ Custom Idea mode requires an idea description.")
                return empty_result
            logger.info("[Pipeline] Custom Idea mode — using %d chars", len(custom_idea))
            raw_content = custom_idea.strip()
            sources: List[Dict[str, str]] = []
            resolved_date = today.isoformat()
            cleaner_output: Dict[str, Any] = {
                "cleaned_content": raw_content,
                "key_facts": [],
                "topic_summary": "(custom idea — no external source)",
                "source_date": resolved_date,
                "_fallback": True,
            }
            empty_result["company"] = {"key": "does4u", "display_name": "Does4U", "domains": []}
            final_target_point = target_point
            haystack = raw_content
        else:
            try:
                from utils.sources import get_company
                company = get_company(company_key)
                empty_result["company"] = {
                    "key": company.key,
                    "display_name": company.display_name,
                    "domains": company.domains,
                }
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Unknown company: {exc}")
                return empty_result

            raw_content, sources, final_target_point, fetch_flags = self._fetch_content(
                ingestion_mode=ingestion_mode,
                target_point=target_point,
                company_key=company_key,
                feed_item_url=feed_item_url,
            )
            flags.extend(fetch_flags)
            if not raw_content:
                self._render_flags(flags)
                st.error("❌ No content could be fetched. Pipeline aborted.")
                empty_result["flags"] = flags
                return empty_result

            with st.spinner("🧹 Cleaning content..."):
                cleaner_output = self.clean_content(raw_content, final_target_point)

            if not cleaner_output:
                truncated = raw_content[:FALLBACK_RAW_CONTENT_CHARS]
                logger.warning("[Pipeline] Cleaner failed — fallback (%d chars)", len(truncated))
                flags.append(make_flag(
                    "warn", "cleaner_fallback",
                    f"Cleaner failed — fallback στο raw content ({FALLBACK_RAW_CONTENT_CHARS} chars).",
                ))
                cleaner_output = {
                    "cleaned_content": truncated,
                    "key_facts": [],
                    "topic_summary": "(fallback — cleaner unavailable)",
                    "_fallback": True,
                }

            haystack = raw_content + "\n" + cleaner_output.get("cleaned_content", "")

            # Ημερομηνία πηγής + ηλικία (υπολογισμένη σε Python)
            resolved_date = self._resolve_source_date(
                source_date,
                sources[0].get("published") if sources else "",
                cleaner_output.get("source_date"),
                flags,
            )
            cleaner_output["source_date"] = resolved_date or "Άγνωστη"

            src_dt = parse_iso_date(resolved_date)
            if src_dt is None:
                flags.append(make_flag(
                    "warn", "unknown_date",
                    "Δεν βρέθηκε ημερομηνία της πηγής — έλεγξε χειροκίνητα πόσο πρόσφατη είναι.",
                ))
            else:
                age = (today - src_dt).days
                if age < 0:
                    flags.append(make_flag(
                        "warn", "future_date",
                        f"Η ημερομηνία της πηγής ({resolved_date}) είναι στο μέλλον.",
                    ))
                elif age > OLD_SOURCE_DAYS:
                    flags.append(make_flag(
                        "warn", "old_source",
                        f"Η πηγή είναι {age} ημερών ({resolved_date}). "
                        "Έλεγξε για νεότερη ανακοίνωση πριν δημοσιεύσεις.",
                    ))

            newer_text = self._find_newer(
                company_key, sources, resolved_date, empty_result["company"], flags
            )

        src_dt = parse_iso_date(resolved_date)
        age_days = (today - src_dt).days if src_dt else None

        targets = self.resolve_languages(language_selection)
        translation_id: Optional[str] = str(uuid.uuid4()) if len(targets) > 1 else None

        bundles: List[Dict[str, Any]] = []
        for target in targets:
            lang_name = target["name"]
            lang_code = target["code"]

            with st.spinner(f"✍️ Writing article ({target['native']})..."):
                article = self.generate_article(
                    cleaned_content=cleaner_output.get("cleaned_content", ""),
                    target_point=final_target_point,
                    category=category,
                    key_facts=cleaner_output.get("key_facts") or [],
                    language=lang_name,
                    sources=sources,
                    source_date=resolved_date or "Άγνωστη",
                    newer_items=newer_text,
                )
            if not article:
                logger.error("[Pipeline] Writer failed for %s", lang_name)
                continue

            article["content_markdown"] = append_sources_section(
                article.get("content_markdown", ""),
                sources,
            )

            article_flags = self._article_checks(
                article["content_markdown"], sources, haystack,
                resolved_date, age_days, today,
            )

            with st.spinner(f"📱 Generating teasers ({target['native']})..."):
                teasers = self.generate_social_teasers(
                    title=article.get("title", ""),
                    category=category,
                    keywords=article.get("keywords") or [],
                    language=lang_name,
                    article_text=article.get("content_markdown", ""),
                )

            bundles.append(
                {
                    "language": lang_code,
                    "language_name": lang_name,
                    "translation_id": translation_id,
                    "article": article,
                    "teasers": teasers,
                    "sources": sources,
                    "company_key": empty_result["company"].get("key", company_key),
                    "source_date": resolved_date,
                    "flags": flags + article_flags,
                }
            )

        all_flags = list(flags)
        for b in bundles:
            all_flags.extend(f for f in b["flags"] if f not in all_flags)
        self._render_flags(all_flags)

        return {
            "cleaner": cleaner_output,
            "sources": sources,
            "company": empty_result["company"],
            "category_slug": cfg["slug"],
            "bundles": bundles,
            "flags": all_flags,
        }

    # ------------------------------------------------------------------
    # Fetch (1 πρωτογενής πηγή) — με πύλη domain και Source Gate
    # ------------------------------------------------------------------
    def _fetch_content(
        self,
        *,
        ingestion_mode: str,
        target_point: str,
        company_key: str,
        feed_item_url: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, str]], str, List[Dict[str, str]]]:
        """Fetch 1 source βάσει ingestion_mode.

        Επιστρέφει: (raw_content, sources, final_target_point, flags)
        """
        flags: List[Dict[str, str]] = []
        if ingestion_mode == INGESTION_MODE_CUSTOM:
            return "", [], target_point, flags

        from utils.providers import (
            get_provider,
            is_official_url,
            resolve_google_news_url,
        )
        from utils.sources import get_company

        try:
            provider_name = self._resolve_provider_name()
            provider = get_provider(name=provider_name)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Could not initialize content provider: {exc}")
            return "", [], target_point, flags

        try:
            company = get_company(company_key)
        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Unknown company: {exc}")
            return "", [], target_point, flags

        raw_content = ""
        sources: List[Dict[str, str]] = []

        if ingestion_mode in (INGESTION_MODE_RSS, INGESTION_MODE_MANUAL):
            if not feed_item_url:
                st.error(f"❌ {ingestion_mode} requires a URL (feed_item_url empty).")
                return "", [], target_point, flags

            real_url = resolve_google_news_url(feed_item_url)
            if not real_url:
                flags.append(make_flag(
                    "error", "google_url_unresolved",
                    "Δεν βρέθηκε το πραγματικό URL του Google News link. "
                    "Χρησιμοποίησε Manual URL με τη σελίδα της εταιρείας.",
                ))
                return "", [], target_point, flags
            if real_url != feed_item_url:
                flags.append(make_flag(
                    "info", "google_url_resolved", f"Το Google link αντιστοιχεί σε {real_url}"
                ))

            with st.spinner("🔍 Extracting from URL..."):
                result = provider.extract_from_url(real_url)
            if not result:
                st.error(f"❌ Could not extract content from: {real_url}")
                return "", [], target_point, flags
            url = result.get("url", real_url)
            sources = [{
                "url": url,
                "title": result.get("title", "") or url,
                "domain": urlparse(url).netloc.lower(),
                "snippet": result.get("snippet", "") or "",
                "published": result.get("published", "") or "",
            }]
            raw_content = result.get("content", "")

        elif ingestion_mode == INGESTION_MODE_RESTRICTED:
            primary = company.primary_domain
            if not primary:
                st.error(f"❌ {company.display_name} has no domain for restricted search.")
                return "", [], target_point, flags
            if not target_point or not target_point.strip():
                st.error("❌ Restricted Search requires a topic.")
                return "", [], target_point, flags
            with st.spinner(f"🔍 Searching {primary} (restricted)..."):
                merged = provider.search_and_extract(target_point, max_results=6, site=primary)
            if not merged or not merged.get("sources"):
                st.error(f"❌ No results for {target_point!r} on {primary}.")
                return "", [], target_point, flags
            sources = merged["sources"][:1]
            raw_content = merged.get("content", "")

        # ---------------------------------------------------------
        # DOMAIN GATE: η πηγή πρέπει να ανήκει στην εταιρεία
        # ---------------------------------------------------------
        if sources:
            domains = [
                d for d in (
                    list(getattr(company, "domains", None) or [])
                    + [getattr(company, "primary_domain", None)]
                ) if d
            ]
            src_url = sources[0].get("url", "")
            if not domains:
                flags.append(make_flag(
                    "info", "no_domains",
                    f"Δεν υπάρχουν επίσημα domains για τη {company.display_name} — δεν έγινε έλεγχος.",
                ))
            elif not is_official_url(src_url, domains):
                msg = (
                    f"Η πηγή ({urlparse(src_url).netloc}) δεν ανήκει στα επίσημα "
                    f"domains της {company.display_name}."
                )
                if ingestion_mode in STRICT_DOMAIN_MODES:
                    flags.append(make_flag("error", "unofficial_domain", msg))
                    return "", [], target_point, flags
                flags.append(make_flag("warn", "unofficial_domain", msg))

        # ---------------------------------------------------------
        # SOURCE GATE: υπάρχει το θέμα στην πηγή; (επικάλυψη λέξεων)
        # ---------------------------------------------------------
        final_target = target_point
        if raw_content and target_point.strip():
            if not topic_in_source(target_point, raw_content):
                if sources and sources[0].get("title"):
                    final_target = sources[0]["title"]
                    flags.append(make_flag(
                        "warn", "topic_changed",
                        f"Το θέμα άλλαξε από «{target_point}» σε «{final_target}» "
                        "επειδή η πηγή δεν το αναφέρει.",
                    ))

        return raw_content, sources, final_target, flags

    @staticmethod
    def _format_sources_for_prompt(sources: List[Dict[str, str]]) -> str:
        if not sources:
            return "(no sources provided)"
        lines = []
        for idx, src in enumerate(sources, start=1):
            title = src.get("title", "") or src.get("url", "")
            url = src.get("url", "")
            lines.append(f"[{idx}] {title} - {url}")
        return "\n".join(lines)

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
        target_point="GPT-6 release",
        category="AI Updates",
        company_key="openai",
        ingestion_mode=INGESTION_MODE_RESTRICTED,
        feed_item_url=None,
        language_selection="Greek",
    )
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
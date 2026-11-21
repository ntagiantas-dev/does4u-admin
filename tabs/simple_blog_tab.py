"""Blog χωρίς πηγές: δημιουργία από θέμα, δικό μου άρθρο, Edit, Publish (git push) + SEO έλεγχοι.

Drafts: φάκελος simple_drafts/ (τοπικά). Δημοσιευμένα: ~/does4u-web/content/blog/ + git push.
"""

import os
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

import streamlit as st
from openai import OpenAI

from utils.article_generator import WRITER_MODEL

WEB_DIR = Path(os.getenv("DOES4U_WEB_DIR", "~/does4u-web")).expanduser()
BLOG_DIR = WEB_DIR / "content" / "blog"
DRAFT_DIR = Path("simple_drafts")
SITE_URL = "https://does4u.com/blog"

GR = {"α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th",
      "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p",
      "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o"}

PROMPT = """Γράψε άρθρο blog στα ελληνικά για μικρές επιχειρήσεις.
Θέμα: {topic}
Κύρια λέξη-κλειδί: {keyword}

Τόνος: φιλικός και απλός, στον ενικό, σαν να μιλάς σε επαγγελματία που δεν ξέρει τεχνολογία.
Στόχος: να καταλάβει πώς τον βοηθά και να θελήσει να επικοινωνήσει, χωρίς πίεση.

ΔΟΜΗ. Οι τίτλοι ## είναι σύντομοι (έως 8 λέξεις), περιγραφικοί, χωρίς άνω-κάτω τελεία και χωρίς οδηγίες.
Το «σκοπός» περιγράφει τι περιέχει η ενότητα και ΔΕΝ αντιγράφεται στον τίτλο.
1. Εισαγωγή 2-3 γραμμές, χωρίς τίτλο, με το καθημερινό πρόβλημα. Η λέξη-κλειδί εμφανίζεται μία φορά μέσα στις πρώτες 100 λέξεις.
2. ## (τίτλος με τη λέξη-κλειδί). Σκοπός: πώς δουλεύει, απλά, με ένα συγκεκριμένο παράδειγμα από μικρή επιχείρηση, χωρίς τεχνικούς όρους. Μέσα βάλε λίστα με bullets (4-5 τυπικές περιπτώσεις του παραδείγματος).
3. ## (τίτλος). Σκοπός: τι κερδίζει ο αναγνώστης.
4. ## (τίτλος). Σκοπός: 3 πρακτικά βήματα σε αριθμημένη λίστα, το τελευταίο να μου γράψει.
5. ## Συχνές ερωτήσεις, με 3 ερωτήσεις ως ### και σύντομη ειλικρινή απάντηση. Για το κόστος απάντησε «εξαρτάται από…» χωρίς αριθμούς.
Μήκος 700-900 λέξεις, σύντομες παράγραφοι.

ΣΥΝΔΕΣΜΟΙ: βάλε μία φορά τον σύνδεσμο [αυτοματοποίηση με AI](/services#ai-automation) μέσα στο κείμενο
και μία φορά το [γράψε μου](/services#contact) στο τρίτο βήμα.

ΑΥΣΤΗΡΟΙ ΚΑΝΟΝΕΣ:
- Χρησιμοποίησε ΜΟΝΟ ελληνικούς και λατινικούς χαρακτήρες (όχι κινεζικούς ή άλλους).
- ΜΗΝ γράψεις ποσοστά, αριθμούς εξοικονόμησης, στατιστικά, ονόματα πελατών, testimonials ή «είχα έναν πελάτη που…».
- Μην υποσχεθείς εγγυημένα αποτελέσματα (χρησιμοποίησε «μπορεί», «συνήθως»).
- Μην πεις ότι έχεις ήδη κάνει κάτι για συγκεκριμένους πελάτες.
- Μην χρησιμοποιείς τεχνικούς όρους χωρίς να τους εξηγήσεις.
- Μην βάλεις τον κύριο τίτλο μέσα στο κείμενο.
{notes}
Επέστρεψε ΑΚΡΙΒΩΣ σε αυτή τη μορφή:
ΤΙΤΛΟΣ: (έως 60 χαρακτήρες, με τη λέξη-κλειδί)
ΠΕΡΙΓΡΑΦΗ: (μία πρόταση έως 150 χαρακτήρες, με τη λέξη-κλειδί)
---
(το άρθρο σε markdown)"""


# ---------- αρχεία ----------
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", "".join(GR.get(c, c) for c in text)).strip("-")
    if len(text) > 60:
        text = text[:60].rsplit("-", 1)[0]
    return text or "arthro"


def read_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = parts[2].strip()
    return {"slug": path.stem, "title": meta.get("title", path.stem), "date": meta.get("date", ""),
            "description": meta.get("description", ""), "keyword": meta.get("keyword", ""), "body": body}


def write_post(folder, slug, title, description, body, keyword="", date=""):
    folder.mkdir(parents=True, exist_ok=True)
    date = date or datetime.now().strftime("%Y-%m-%d")
    one = lambda s: " ".join(s.split())  # noqa: E731
    (folder / f"{slug}.md").write_text(
        f"---\ntitle: {one(title)}\ndate: {date}\ndescription: {one(description)}\n"
        f"keyword: {one(keyword)}\n---\n\n{body.strip()}\n", encoding="utf-8")


def new_slug(text: str) -> str:
    base, slug, n = slugify(text), slugify(text), 2
    while (DRAFT_DIR / f"{slug}.md").exists() or (BLOG_DIR / f"{slug}.md").exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def list_posts(folder: Path):
    posts = [read_post(p) for p in folder.glob("*.md")] if folder.exists() else []
    return sorted(posts, key=lambda p: p["date"], reverse=True)


# ---------- SEO έλεγχοι ----------
def check_post(title, desc, body, keyword):
    warns, blockers = [], []
    text = f"{title} {desc} {body}"
    bad = sorted({c for c in text if ord(c) > 0x2FF and not (
        0x370 <= ord(c) <= 0x3FF or 0x1F00 <= ord(c) <= 0x1FFF or 0x2000 <= ord(c) <= 0x206F or c in "€→←✓•")})
    if bad:
        blockers.append("Βρέθηκαν ξένοι χαρακτήρες: " + " ".join(bad) + " (διόρθωσέ τους πριν τη δημοσίευση)")
    if len(title) > 60:
        warns.append(f"Ο τίτλος έχει {len(title)} χαρακτήρες (ιδανικά έως 60).")
    if not 70 <= len(desc) <= 155:
        warns.append(f"Η περιγραφή έχει {len(desc)} χαρακτήρες (ιδανικά 70-150).")
    kw = keyword.strip().lower()
    if kw:
        first = " ".join(body.split()[:100]).lower()
        h2 = " ".join(re.findall(r"^## (.+)$", body, re.M)).lower()
        for label, ok in (("τον τίτλο", kw in title.lower()), ("την περιγραφή", kw in desc.lower()),
                          ("τις πρώτες 100 λέξεις", kw in first), ("κάποιον τίτλο ενότητας", kw in h2)):
            if not ok:
                warns.append(f"Η λέξη-κλειδί λείπει από {label}.")
    else:
        warns.append("Δεν έχεις ορίσει λέξη-κλειδί.")
    if re.search(r"\d\s*%|€", body):
        warns.append("Υπάρχει ποσοστό ή ποσό: βεβαιώσου ότι δεν είναι επινοημένο.")
    if re.search(r"^## .*:", body, re.M):
        warns.append("Τίτλος ενότητας με «:» (πιθανή οδηγία του prompt μέσα στον τίτλο).")
    if "](/services" not in body:
        warns.append("Λείπει εσωτερικός σύνδεσμος προς τις υπηρεσίες.")
    if len(re.findall(r"^### ", body, re.M)) < 2:
        warns.append("Λείπει η ενότητα συχνών ερωτήσεων (### ερώτηση).")
    if len(body.split()) < 600:
        warns.append(f"Το κείμενο έχει {len(body.split())} λέξεις (ιδανικά 700+).")
    return warns, blockers


def show_checks(title, desc, body, keyword) -> bool:
    warns, blockers = check_post(title, desc, body, keyword)
    for b in blockers:
        st.error(b)
    for w in warns:
        st.warning(w)
    if not warns and not blockers:
        st.success("✅ Οι SEO έλεγχοι πέρασαν.")
    return bool(blockers)


# ---------- git ----------
def git_push(message: str):
    def run(*args):
        return subprocess.run(["git", "-C", str(WEB_DIR), *args], capture_output=True, text=True, timeout=90)
    BLOG_DIR.mkdir(parents=True, exist_ok=True)
    (BLOG_DIR / ".gitkeep").touch()
    r = run("add", "-A", "--", "content")
    if r.returncode:
        return False, r.stderr
    r = run("commit", "-m", message, "--", "content")
    if r.returncode and "nothing to commit" not in (r.stdout + r.stderr):
        return False, r.stdout + r.stderr
    r = run("push")
    return r.returncode == 0, (r.stdout + r.stderr)[-600:]


def publish(slug: str):
    src = DRAFT_DIR / f"{slug}.md"
    p = read_post(src)
    write_post(BLOG_DIR, slug, p["title"], p["description"], p["body"], p["keyword"])
    src.unlink()
    return git_push(f"Blog: δημοσίευση {slug}")


# ---------- LLM ----------
def generate(topic, keyword, notes):
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    extra = f"\nΣημεία που θέλω να αναφερθούν: {notes}\n" if notes.strip() else ""
    prompt = PROMPT.format(topic=topic, keyword=keyword, notes=extra)
    text = ""
    for tokens in (5000, 10000):
        resp = client.chat.completions.create(
            model=WRITER_MODEL, max_completion_tokens=tokens, messages=[{"role": "user", "content": prompt}])
        text = (resp.choices[0].message.content or "").strip()
        if text:
            break
    title, desc, body = topic, "", text
    if "---" in text:
        head, body = text.split("---", 1)
        for line in head.splitlines():
            if line.upper().startswith("ΤΙΤΛΟΣ:"):
                title = line.split(":", 1)[1].strip()
            elif line.upper().startswith("ΠΕΡΙΓΡΑΦΗ:"):
                desc = line.split(":", 1)[1].strip()
    return title, desc, body.strip()


# ---------- UI ----------
def edit_form(post: dict, published: bool):
    slug = post["slug"]
    k = f"{'pub' if published else 'dr'}_{slug}"
    title = st.text_input("Τίτλος", post["title"], key=f"t_{k}")
    st.caption(f"{len(title)} / 60 χαρακτήρες")
    kw = st.text_input("Λέξη-κλειδί", post["keyword"], key=f"k_{k}")
    desc = st.text_input("Περιγραφή (μία πρόταση)", post["description"], key=f"d_{k}")
    st.caption(f"{len(desc)} / 150 χαρακτήρες")
    new = slug
    if published:
        st.caption(f"Διεύθυνση: {SITE_URL}/{slug} (δεν αλλάζει μετά τη δημοσίευση)")
    else:
        new = slugify(st.text_input("Slug (η διεύθυνση του άρθρου)", slug, key=f"sl_{k}"))
        st.caption(f"{SITE_URL}/{new}")
    body = st.text_area("Κείμενο (markdown)", post["body"], height=420, key=f"b_{k}")
    blocked = show_checks(title, desc, body, kw)

    folder = BLOG_DIR if published else DRAFT_DIR
    cols = st.columns(3)
    if cols[0].button("💾 Αποθήκευση" + (" και push" if published else ""), key=f"s_{k}"):
        if new != slug and (DRAFT_DIR / f"{new}.md").exists():
            st.error("Υπάρχει ήδη draft με αυτό το slug.")
            return
        write_post(folder, new, title, desc, body, kw, post["date"] if published else "")
        if new != slug:
            (folder / f"{slug}.md").unlink(missing_ok=True)
            st.rerun()
        if published:
            ok, msg = git_push(f"Blog: επεξεργασία {slug}")
            (st.success if ok else st.error)("Αποθηκεύτηκε και ανέβηκε." if ok else msg)
        else:
            st.success("Αποθηκεύτηκε.")
    if not published and cols[1].button("🚀 Δημοσίευση", key=f"p_{k}", disabled=blocked):
        write_post(DRAFT_DIR, new, title, desc, body, kw)
        if new != slug:
            (DRAFT_DIR / f"{slug}.md").unlink(missing_ok=True)
        ok, msg = publish(new)
        st.success(f"Ανέβηκε! Σε 1-2 λεπτά θα φαίνεται στο {SITE_URL}/{new}") if ok else st.error(msg)
    if not published and cols[2].button("🗑️ Διαγραφή", key=f"x_{k}"):
        (DRAFT_DIR / f"{slug}.md").unlink(missing_ok=True)
        st.rerun()
    if published and cols[1].button("↩️ Αποσύρω (πίσω σε draft)", key=f"u_{k}"):
        write_post(DRAFT_DIR, slug, title, desc, body, kw, post["date"])
        (BLOG_DIR / f"{slug}.md").unlink(missing_ok=True)
        ok, msg = git_push(f"Blog: απόσυρση {slug}")
        (st.success if ok else st.error)("Αποσύρθηκε." if ok else msg)


def render_simple_blog_tab() -> None:
    if not WEB_DIR.exists():
        st.error(f"Δεν βρέθηκε ο φάκελος του site: {WEB_DIR}")
        return
    t_gen, t_own, t_dr, t_pub = st.tabs(["✨ Νέο από θέμα", "✍️ Δικό μου άρθρο", "📋 Drafts", "🚀 Δημοσιευμένα"])

    with t_gen:
        topic = st.text_input("Θέμα άρθρου", placeholder="π.χ. Πώς ένα chatbot απαντά στους πελάτες ενός μικρού ξενοδοχείου")
        keyword = st.text_input("Κύρια λέξη-κλειδί", placeholder="π.χ. chatbot για ξενοδοχείο")
        notes = st.text_area("Σημεία που θέλεις να αναφερθούν (προαιρετικό)", height=80)
        if st.button("✨ Δημιουργία άρθρου", disabled=not (topic.strip() and keyword.strip())):
            with st.spinner("Γράφω το άρθρο..."):
                try:
                    title, desc, body = generate(topic.strip(), keyword.strip(), notes)
                    write_post(DRAFT_DIR, new_slug(keyword), title, desc, body, keyword.strip())
                    st.success(f"Αποθηκεύτηκε στα Drafts: {title}. Διάβασέ το και δες τους ελέγχους πριν το δημοσιεύσεις.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Σφάλμα: {exc}")

    with t_own:
        title = st.text_input("Τίτλος", key="own_title")
        kw = st.text_input("Κύρια λέξη-κλειδί", key="own_kw")
        desc = st.text_input("Περιγραφή (μία πρόταση)", key="own_desc")
        body = st.text_area("Γράψε ή επικόλλησε το κείμενο (markdown)", height=420, key="own_body")
        if st.button("💾 Αποθήκευση ως draft", disabled=not (title.strip() and body.strip())):
            write_post(DRAFT_DIR, new_slug(kw or title), title, desc, body, kw)
            st.success("Αποθηκεύτηκε στα Drafts. Από εκεί το ελέγχεις και το δημοσιεύεις.")

    with t_dr:
        drafts = list_posts(DRAFT_DIR)
        st.info("Δεν υπάρχουν drafts.") if not drafts else None
        for post in drafts:
            with st.expander(f"📝 {post['title']}"):
                edit_form(post, published=False)

    with t_pub:
        posts = list_posts(BLOG_DIR)
        st.info("Δεν υπάρχουν δημοσιευμένα άρθρα.") if not posts else None
        for post in posts:
            with st.expander(f"✅ {post['title']} ({post['date']})"):
                st.markdown(f"[Άνοιγμα στο site]({SITE_URL}/{post['slug']})")
                edit_form(post, published=True)
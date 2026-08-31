"""
Build a section-level corpus from the AGC Malaysia PDF dump.

Reads pdfs/<category>/EN/*.pdf, extracts text, splits each Act into
individual sections, and writes one JSONL record per section.

    pip install pymupdf

    python build_corpus.py --test          # 20 acts, prints samples
    python build_corpus.py                 # updated + fc + amendments
    python build_corpus.py --categories updated

Output:
    corpus/sections.jsonl   one JSON object per section
    corpus/skipped.csv      files with no text layer (need OCR) or no sections
    corpus/report.txt       extraction quality summary
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    sys.exit("Missing dependency. Run:  pip install pymupdf")

ROOT = Path(__file__).resolve().parent
PDF_ROOT = ROOT / "pdfs"
OUT = ROOT / "corpus"

# Categories safe to index. 'repealed', 'revised' and 'translated' are
# deliberately absent: repealed law must never be retrieved as current, and
# the other two are ~82% unsearchable scans that duplicate 'updated'.
#
# 'federal_constitution' is also excluded. The Reprint 2020 interleaves an
# editorial annotation apparatus (~130 NOTES blocks, each restarting its
# numbering at 1) with the operative text, and the two cannot be separated
# reliably by pattern. Ordinary Acts carry no such apparatus and parse clean.
# Add it back with --categories once it has a bespoke parser, or source an
# unannotated copy of the Constitution.
DEFAULT_CATEGORIES = ["updated", "amendment"]

# Fallback categories, consulted only for Acts absent from the primary ones.
# 'translated' and 'revised' are ~82% scans, but the readable remainder holds
# statutes 'updated' simply does not carry -- the Evidence Act 1950 among them,
# which parses to 180 clean sections. Scans are still skipped automatically by
# the text-layer check, so this adds coverage without adding noise. An Act that
# appears only here is the most current text AGC publishes for it.
FALLBACK_CATEGORIES = ["translated", "revised"]

# Repealed Acts leak into pdfs/updated/ under names like
# "ACT 310 REPEALED BY ACT 364.pdf". Never index these.
REPEALED_NAME_RE = re.compile(r"\brepeal", re.I)

# "12." / "12A." / "3B." at the start of a line, followed by the section body.
# The letter suffix must accept lowercase: AGC typesets lettered sections in
# lowercase ("60e." for section 60E), and matching only uppercase silently
# folded 1,890 of them into the preceding section -- s.60E, annual leave,
# among them. The suffix is upper-cased when the record is built.
SECTION_RE = re.compile(r"^[^\S\n]*(\d{1,3}[A-Za-z]{0,2})\.[^\S\n]+(?=\S)", re.M)

# PART II / Part IIA / CHAPTER 3 dividers. Case-insensitive: the Federal
# Constitution writes "Part I", Acts write "PART I".
PART_RE = re.compile(
    r"^[ \t]*((?:PART|Part)\s+[IVXLC]+[A-Z]?|(?:CHAPTER|Chapter)\s+[\dIVXLC]+)\b.*$",
    re.M)

# Schedules restart numbering at 1, so they must be parsed separately or
# they collide with the sections of the Act proper.
SCHEDULE_RE = re.compile(
    r"^[ \t]*((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|"
    r"TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH)?\s*SCHEDULES?)"
    r"[ \t]*$", re.M | re.I)

# Where the table of contents stops and the enacting text begins.
BODY_START_RE = re.compile(
    r"^.*\b(?:ENACTED BY|BE IT ENACTED|An Act to|An Act for|WHEREAS)\b.*$",
    re.M | re.I)

# Every AGC cover page prints the official title in caps two or three times
# ("EDUCATION ACT 1996"), sometimes wrapped across lines. Frequency picks it
# out from the surrounding boilerplate far more reliably than position does.
CAPS_LINE_RE = re.compile(r"^[^a-z]*[A-Z][^a-z]*$")
# The AGC disclaimer names the Act outright: "This text is ONLY AN UPDATED
# TEXT of the Labuan Companies Act 1990 by the Attorney General's Chambers".
# That is the most authoritative statement of the title on the page, and it
# survives covers that are typeset in small caps or omit the word "Act".
DISCLAIMER_TITLE_RE = re.compile(
    r"(?:UPDATED\s+TEXT|AUTHENTIC\s+TEXT)\s+of\s+the\s+(.{6,110}?)\s+by\s+the\s+"
    r"Attorney", re.I | re.S)
# Same shape as a title but case-insensitive, for covers set in small caps
# ("communications and multimedia act 1998").
ANYCASE_TITLE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9 ’'()\-,\.&/]*\b(?:ACT|ORDINANCE|ENACTMENT)"
    r"\s+\d{4}$", re.I)
# Lines that are clearly cover furniture rather than part of a title.
NON_TITLE_RE = re.compile(
    r"^\s*$|\.\.\.|…|^(?:Date|Published|Under the Authority|In Collaboration|"
    r"Incorporating|First enacted|Revised|Latest amendment|As at|Reprint|"
    r"Publisher|All rights reserved|PREVIOUS REPRINTS)\b", re.I)
TITLE_RE = re.compile(
    r"^[A-Z0-9][A-Z0-9 ’'()\-,\.&/]*\b(?:ACT|ORDINANCE|ENACTMENT)"
    r"\s+\d{4}$")
# Cover boilerplate that also ends in "ACT <year>" and must never win.
TITLE_BLACKLIST_RE = re.compile(
    r"REVISION OF LAWS|UNDER THE AUTHORITY|PUBLISHED BY|ARRANGEMENT|"
    r"INTERPRETATION ACTS", re.I)
# Cover furniture that sits on the same caps run as the title and gets glued
# to the front of it ("REPRINT MEMBERS OF PARLIAMENT ... ACT 1980").
TITLE_PREFIX_RE = re.compile(
    r"^(?:ONLINE VERSION(?: OF UPDATED)?|TEXT OF REPRINT|OF UPDATED TEXT"
    r"(?: OF REPRINT)?|REPRINT|LAWS OF MALAYSIA|MALAYSIA)\s+", re.I)
# Some reprints carry the printer's colophon in the same caps run as the
# title: "PREPARED FOR PUBLICATION BY MALAYAN LAW JOURNAL SDN BHD AND PRINTED
# BY PERCETAKAN NASIONAL ... KUALA LUMPUR BRANCH KEMUBU AGRICULTURAL ... ACT
# 1972". Everything up to the printer's address is boilerplate.
# The .* must be greedy: it has to run to the LAST publisher marker, not the
# first. A lazy match stops at "SDN BHD" and leaves "AND PRINTED BY ... KUALA
# LUMPUR BRANCH" still glued to the title.
COLOPHON_RE = re.compile(
    r"^(?:AND\s+)?(?:PREPARED FOR PUBLICATION|PRINTED BY|PUBLISHED BY)\b.*"
    r"\b(?:BRANCH|BERHAD|SDN\s+BHD)\s+", re.I)
# Same shape as TITLE_RE but with the year optional -- a few Acts print the
# title without one. Only consulted when the strict pass finds nothing.
LOOSE_TITLE_RE = re.compile(
    r"^[A-Z0-9][A-Z0-9 ’'()\-,\.&/]{10,}\b(?:ACT|ORDINANCE|ENACTMENT)"
    r"(?:\s+\d{4})?$")

# "Act 265 - Employment Act 1955.pdf" -> title after the dash
FILENAME_TITLE_RE = re.compile(r"^Act\s+A?\d{1,4}\s*-\s*(.+)$", re.I)
# Not \b after the digits: filenames read "Act 333_Final.pdf", and underscore
# is a word character, so \b never matches there. 21 Acts fell through to the
# cover page and picked up "[Act 1]" out of the Revision of Laws disclaimer.
# Neither \b nor a plain boundary works here: filenames read both
# "Act 333_Final.pdf" and "100622_Act 441_final.pdf", and underscore is a word
# character on both sides. Use an explicit lookbehind that allows "_" before
# "Act" but rejects letters, so "Fact 12" never matches.
ACT_NO_RE = re.compile(r"(?<![A-Za-z0-9])Act[\s_\-]+(A?\d{1,4})(?![0-9])", re.I)
# "Finance" running head + "Finance Act 2013" title -> "FINANCE FINANCE ACT".
REPEATED_HEAD_RE = re.compile(r"^([A-Z][A-Z'’\-]*)\s+(?=\1\b)")

# Annotated reprints -- the Federal Constitution above all -- interleave
# editorial footnotes with the operative text. Each NOTES block restarts its
# numbering at 1, which collides head-on with the Articles themselves, so the
# blocks have to go before any section splitting happens.
ANNOTATION_RE = re.compile(
    r"^(?:\d{1,3}|[a-z])\.\s+(?:Added\b|Inserted\b|Substituted\b|Deleted\b|"
    r"Repealed\b|Numbered\b|Formerly\b|See\s|The words?\b|The word\b|"
    r"This (?:Article|Item|Schedule|section|paragraph)\b|"
    r"The (?:present|earlier|heading|note|original|last sentence|functions)\b|"
    r"Acts?\s+A?\d|In the shoulder note\b|Upon\b|Until\b|These Articles\b)",
    re.I)
NOTES_HEAD_RE = re.compile(r"^(?:NOTES?|Clause\s*\(?\d+[a-z]?\)?)\s*$", re.I)
# Body text resuming after a footnote block: "(3) No person shall...",
# a Part divider, or the next numbered provision.
RESUME_RE = re.compile(
    r"^(?:\(\d+[A-Za-z]?\)|(?:PART|Part|CHAPTER|Chapter)\s|\d{1,3}[A-Z]?\.\s)")

MIN_CHARS_PER_PAGE = 120  # below this, assume the page is a scan
MAX_NOTE_LEN = 100        # marginal notes are short; longer means we grabbed prose
MAX_SCHEDULE_CHARS = 8000  # above this, split a schedule on its own numbering


def extract_text(pdf_path):
    """Return (text, n_pages, n_text_pages). Few text pages => needs OCR."""
    chunks, text_pages = [], 0
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            t = page.get_text("text")
            if len(t.strip()) >= MIN_CHARS_PER_PAGE:
                text_pages += 1
            chunks.append(t)
        return "\n".join(chunks), doc.page_count, text_pages


def clean(text):
    """Strip running headers/footers and normalise PDF whitespace."""
    lines = []
    for ln in text.splitlines():
        # PDF extraction litters tabs and runs of spaces mid-sentence. Use
        # [^\S\n] rather than [ \t]: AGC sets an EN SPACE (U+2002) after the
        # section number, which no plain-space pattern matches.
        s = re.sub(r"[^\S\n]+", " ", ln).strip()
        if not s:
            lines.append("")
            continue
        if re.fullmatch(r"\d{1,4}", s):                      # bare page number
            continue
        # Running heads, with the page number often glued on either side:
        # "10 Laws of Malaysia ACT 177", "Laws of Malaysia 24".
        if re.fullmatch(r"(?:\d{1,4}\s+)?"
                        r"(?:Laws of Malaysia|Undang-Undang Malaysia|"
                        r"Federal Constitution|Perlembagaan Persekutuan)"
                        r"(?:\s+(?:ACT|AKTA)\s+A?\d{1,4})?"
                        r"(?:\s+\d{1,4})?", s, re.I):
            continue
        if re.fullmatch(r"(?:\d{1,4}\s+)?(?:ACT|AKTA)\s+A?\d{1,4}(?:\s+\d{1,4})?",
                        s, re.I):
            continue
        # InDesign print furniture: "WJW23/0686 Act 265.indd 58" and the
        # timestamp that follows it on the next line.
        if re.search(r"\.indd\s+\d+", s, re.I):
            continue
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M", s, re.I):
            continue
        lines.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(strip_annotations(lines)))


def strip_annotations(lines):
    """Drop NOTES footnote blocks, keeping the operative text around them.

    A block starts at a NOTES heading or an annotation line and runs until the
    text resumes with a clause, a Part divider or the next provision.
    """
    out, skipping = [], False
    for ln in lines:
        s = ln.strip()
        if NOTES_HEAD_RE.match(s) or ANNOTATION_RE.match(s):
            skipping = True
            continue
        if skipping:
            if not s:
                continue
            if RESUME_RE.match(s):
                skipping = False
            else:
                continue  # continuation of the footnote
        out.append(ln)
    return out


def title_candidates(text):
    """All-caps blocks on the cover page that look like an Act's long title."""
    blocks, buf = [], []
    for ln in text.splitlines():
        s = ln.strip()
        if s and CAPS_LINE_RE.match(s) and len(s) <= 90:
            buf.append(s)
            continue
        if buf:
            blocks.append(" ".join(buf))
            buf = []
    if buf:
        blocks.append(" ".join(buf))

    cleaned = []
    for i, b in enumerate(blocks):
        b = re.sub(r"\s+", " ", b).strip(" .")
        b = COLOPHON_RE.sub("", b)
        prev = None
        while prev != b:                       # "ONLINE VERSION REPRINT X" -> "X"
            prev, b = b, TITLE_PREFIX_RE.sub("", b)
        if b and not TITLE_BLACKLIST_RE.search(b):
            cleaned.append((b, i))

    strict = [(b, i) for b, i in cleaned if TITLE_RE.match(b)]
    return strict or [(b, i) for b, i in cleaned if LOOSE_TITLE_RE.match(b)]


def anycase_candidates(head):
    """Title-shaped blocks regardless of case, for small-caps covers."""
    blocks, buf = [], []
    for ln in head.splitlines():
        s = ln.strip()
        if s and len(s) <= 90 and not NON_TITLE_RE.search(s):
            buf.append(s)
            continue
        if buf:
            blocks.append(" ".join(buf))
            buf = []
    if buf:
        blocks.append(" ".join(buf))

    out = []
    for i, b in enumerate(blocks):
        b = re.sub(r"\s+", " ", COLOPHON_RE.sub("", b)).strip(" .")
        prev = None
        while prev != b:
            prev, b = b, TITLE_PREFIX_RE.sub("", b)
        if b and not TITLE_BLACKLIST_RE.search(b) and ANYCASE_TITLE_RE.match(b):
            out.append((b.upper(), i))
    return out


def pick_most_frequent(cands):
    """Most repeated candidate wins; earliest on the page breaks a tie."""
    if not cands:
        return None
    counts, first = {}, {}
    for b, i in cands:
        counts[b] = counts.get(b, 0) + 1
        first.setdefault(b, i)
    return sorted(counts, key=lambda b: (-counts[b], first[b]))[0]


def act_identity(text, pdf_path):
    """Return (act_no, act_title) from the cover page, falling back to name."""
    head = text[:6000]
    title = None

    # 1. The disclaimer states the Act's name outright -- most reliable.
    m = DISCLAIMER_TITLE_RE.search(head)
    if m:
        cand = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if ANYCASE_TITLE_RE.match(cand) and not TITLE_BLACKLIST_RE.search(cand):
            title = cand.upper()

    # 2. All-caps cover title, chosen by how often it repeats.
    if not title:
        title = pick_most_frequent(title_candidates(head))

    # 3. Same idea but case-insensitive, for small-caps typesetting.
    if not title:
        title = pick_most_frequent(anycase_candidates(head))

    # 4. Some reprints print the short title without the word "Act" at all
    # ("CHILDREN AND YOUNG PERSONS (EMPLOYMENT)"). Require it to repeat, which
    # titles do on an AGC cover and boilerplate does not.
    if not title:
        blocks, buf = [], []
        for ln in head.splitlines():
            s = ln.strip()
            if s and len(s) <= 90 and not NON_TITLE_RE.search(s):
                buf.append(s)
            elif buf:
                blocks.append(" ".join(buf))
                buf = []
        if buf:
            blocks.append(" ".join(buf))
        counts = {}
        for b in blocks:
            b = re.sub(r"\s+", " ", b).strip(" .").upper()
            if len(b) >= 10 and not TITLE_BLACKLIST_RE.search(b) \
                    and re.match(r"^[A-Z][A-Z0-9 ’'()\-,\.&/]+$", b):
                counts[b] = counts.get(b, 0) + 1
        # Structural headings repeat too, and must not be mistaken for a title.
        structural = re.compile(
            r"^(?:INTERPRETATION|PRELIMINARY|ARRANGEMENT|SECTION|PART|CHAPTER|"
            r"SCHEDULE|CONTENTS|SHORT TITLE|GENERAL|MISCELLANEOUS|"
            r"SAVINGS|TRANSITIONAL|ENFORCEMENT|DEFINITIONS?)\b", re.I)
        repeated = [b for b, n in counts.items()
                    if n >= 2 and not structural.match(b)]
        if repeated:
            title = max(repeated, key=len)

    if not title:
        fm = FILENAME_TITLE_RE.match(pdf_path.stem)
        title = fm.group(1).strip().upper() if fm else None

    if not title:
        m2 = re.search(r"^([A-Z][A-Z \-'(),\.]{8,90}"
                       r"(?:ACT|ORDINANCE|CONSTITUTION)[ \t]*\d{0,4})$",
                       head, re.M)
        title = re.sub(r"\s+", " ", m2.group(1)).strip() if m2 else pdf_path.stem

    prev = None
    while prev != title:                 # "FINANCE FINANCE ACT 2013"
        prev, title = title, REPEATED_HEAD_RE.sub("", title)

    # The filename is the reliable source (700/822 start "Act NNN"). A bare
    # "ACT 1968" on the cover is usually a year, so only the bracketed or
    # parenthesised forms are trusted as a fallback.
    fm = ACT_NO_RE.search(pdf_path.stem)
    act_no = fm.group(1) if fm else None
    if not act_no:
        # Every AGC cover carries "...Revision of Laws Act 1968 [Act 1]" in its
        # disclaimer, so a bracketed "Act 1" here is boilerplate, never the
        # document's own number. The real Act 1 is named in its filename.
        for m in re.finditer(r"[\[(]\s*Act\s+(A?\d{1,4})\b", head, re.I):
            if m.group(1) != "1":
                act_no = m.group(1)
                break

    return act_no, title


def find_body_start(text):
    """Skip the ARRANGEMENT OF SECTIONS table of contents."""
    toc = re.search(r"ARRANGEMENT OF (?:SECTIONS|ARTICLES)", text, re.I)
    search_from = toc.end() if toc else 0
    body = BODY_START_RE.search(text, search_from)
    if body:
        return body.start()
    return search_from


def is_toc_like(note):
    """TOC lines leak in as marginal notes: dot leaders, or '4. Grant of...'."""
    if not note or len(note) > MAX_NOTE_LEN:
        return True
    if "..." in note:
        return True
    if re.search(r"\b\d{1,3}\.\s+[A-Z]", note):   # embedded section numbering
        return True
    if note.count(".") > 1:
        return True
    return False


def marginal_note(body, pos, act_title):
    """The short line(s) immediately above a section number."""
    preceding = body[max(0, pos - 240):pos].strip().splitlines()
    note = ""
    for ln in reversed(preceding):
        s = ln.strip()
        if not s:
            if note:
                break
            continue
        if len(s) > 120 or s.endswith((".", ";", ":")):
            break
        note = (s + " " + note).strip()

    if PART_RE.match(note or "") or SCHEDULE_RE.match(note or ""):
        return ""
    if note and note.upper() == act_title.upper():
        return ""
    return "" if is_toc_like(note) else note


def parts_index(body):
    """[(offset, part_name)] so each section can report the PART it sits in."""
    return [(m.start(), re.sub(r"\s+", " ", m.group(1)).strip())
            for m in PART_RE.finditer(body)]


def part_at(parts, pos):
    cur = None
    for off, name in parts:
        if off <= pos:
            cur = name
        else:
            break
    return cur


def parse_sections(body, act_title):
    """Yield section dicts from the operative body of an Act."""
    marks = list(SECTION_RE.finditer(body))
    if not marks:
        return []
    parts = parts_index(body)

    best = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        sec_no = m.group(1).upper()          # "60e" -> "60E"
        sec_body = body[m.end():end].strip()
        if len(sec_body) < 40:
            continue
        # An Act cannot have two s.5. If a number repeats, the table of
        # contents leaked through -- keep the longest body, which is the
        # real provision rather than the one-line TOC entry.
        prev = best.get(sec_no)
        if prev is None or len(sec_body) > len(prev["text"]):
            best[sec_no] = {
                "section_no": sec_no,
                "marginal_note": marginal_note(body, m.start(), act_title),
                "text": sec_body,
                "part": part_at(parts, m.start()),
                "is_schedule": False,
                "schedule": None,
            }

    def sort_key(s):
        m = re.match(r"(\d+)([A-Z]*)", s["section_no"])
        return (int(m.group(1)), m.group(2)) if m else (9999, "")

    return sorted(best.values(), key=sort_key)


def parse_schedules(tail):
    """Schedules restart at 1, so they get their own namespace."""
    out = []
    marks = list(SCHEDULE_RE.finditer(tail))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tail)
        name = re.sub(r"\s+", " ", m.group(1)).strip().title()
        content = tail[m.end():end].strip()
        if len(content) < 40:
            continue
        if len(content) <= MAX_SCHEDULE_CHARS:
            out.append({"section_no": None, "marginal_note": "", "text": content,
                        "part": None, "is_schedule": True, "schedule": name})
        else:
            items = list(SECTION_RE.finditer(content))
            if not items:
                out.append({"section_no": None, "marginal_note": "",
                            "text": content[:MAX_SCHEDULE_CHARS], "part": None,
                            "is_schedule": True, "schedule": name})
                continue
            for j, im in enumerate(items):
                iend = items[j + 1].start() if j + 1 < len(items) else len(content)
                body = content[im.end():iend].strip()
                if len(body) < 40:
                    continue
                out.append({"section_no": im.group(1), "marginal_note": "",
                            "text": body, "part": None, "is_schedule": True,
                            "schedule": name})
    return out


def split_document(text, act_title):
    """Split into operative sections plus schedule items."""
    body = text[find_body_start(text):]

    sched = SCHEDULE_RE.search(body)
    # Only treat it as the schedule boundary if it is late in the document;
    # an early hit is usually a cross-reference in the TOC.
    if sched and sched.start() > len(body) * 0.4:
        main, tail = body[:sched.start()], body[sched.start():]
    else:
        main, tail = body, ""

    return parse_sections(main, act_title) + (parse_schedules(tail) if tail else [])


def cite(act_title, rec):
    """The Federal Constitution has Articles; Acts have sections."""
    if rec["is_schedule"]:
        base = f"{act_title}, {rec['schedule']}"
        return f"{base}, para {rec['section_no']}" if rec["section_no"] else base
    unit = "Art." if "CONSTITUTION" in act_title.upper() else "s."
    return f"{act_title}, {unit}{rec['section_no']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES))
    ap.add_argument("--fallback", default=",".join(FALLBACK_CATEGORIES),
                    help="categories used only for Acts missing from the "
                         "primary ones; empty string disables")
    ap.add_argument("--lang", default="EN")
    ap.add_argument("--test", action="store_true", help="20 acts, print samples")
    args = ap.parse_args()

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    fallbacks = [c.strip() for c in args.fallback.split(",") if c.strip()]
    OUT.mkdir(exist_ok=True)

    # (path, category, is_fallback), primary categories first so that a
    # fallback copy is only ever used when the Act is otherwise absent.
    pdfs = []
    for c in cats:
        d = PDF_ROOT / c / args.lang
        if d.is_dir():
            pdfs += [(p, c, False) for p in sorted(d.glob("*.pdf"))]
    primary_count = len(pdfs)
    for c in fallbacks:
        d = PDF_ROOT / c / args.lang
        if d.is_dir():
            pdfs += [(p, c, True) for p in sorted(d.glob("*.pdf"))]

    if args.test:
        pdfs = pdfs[:20]
    if not pdfs:
        sys.exit(f"No PDFs found under {PDF_ROOT} for categories {cats}")

    print(f"{len(pdfs)} PDFs to process "
          f"({primary_count} primary, {len(pdfs) - primary_count} fallback)\n")

    seen_acts = set()   # act_no, or a normalised title when there is no number

    n_sections = n_schedules = ok_files = 0
    skipped = []

    with (OUT / "sections.jsonl").open("w", encoding="utf-8") as out:
        for i, (pdf, category, is_fallback) in enumerate(pdfs, 1):
            rel = pdf.relative_to(ROOT).as_posix()

            if REPEALED_NAME_RE.search(pdf.stem):
                skipped.append((rel, "repealed_in_filename", pdf.stem[:60]))
                continue

            try:
                raw, pages, text_pages = extract_text(pdf)
            except Exception as e:
                skipped.append((rel, "unreadable", str(e)[:120]))
                continue

            if pages and text_pages / pages < 0.5:
                skipped.append((rel, "needs_ocr", f"{text_pages}/{pages} text pages"))
                continue

            text = clean(raw)
            act_no, act_title = act_identity(text, pdf)

            # A fallback copy is used only when the primary categories did not
            # supply that Act at all, otherwise the same law lands in the index
            # twice in two different vintages. Primary entries are never
            # dropped: amendment Acts legitimately share a principal Act's
            # number and must stay separate.
            key = act_no or re.sub(r"[^A-Z0-9]", "", act_title.upper())
            if is_fallback:
                if key in seen_acts:
                    skipped.append((rel, "already_covered", f"Act {key}"))
                    continue
            seen_acts.add(key)

            found = 0
            for rec in split_document(text, act_title):
                sid = rec["section_no"] or "x"
                prefix = (rec["schedule"] or "").replace(" ", "") if rec["is_schedule"] else ""
                out.write(json.dumps({
                    "id": f"{act_no or pdf.stem}-{prefix}s{sid}-{found}",
                    "act_no": act_no,
                    "act_title": act_title,
                    "category": category,
                    "part": rec["part"],
                    "section_no": rec["section_no"],
                    "marginal_note": rec["marginal_note"],
                    "is_schedule": rec["is_schedule"],
                    "schedule": rec["schedule"],
                    "citation": cite(act_title, rec),
                    "text": rec["text"],
                    "source_pdf": rel,
                }, ensure_ascii=False) + "\n")
                found += 1
                if rec["is_schedule"]:
                    n_schedules += 1
                else:
                    n_sections += 1

            if found:
                ok_files += 1
            else:
                skipped.append((rel, "no_sections_matched", f"{pages}p"))

            if i % 50 == 0 or i == len(pdfs):
                print(f"  [{i}/{len(pdfs)}] {n_sections} sections, "
                      f"{len(skipped)} skipped")

    with (OUT / "skipped.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "reason", "detail"])
        w.writerows(skipped)

    reasons = {}
    for _, r, _ in skipped:
        reasons[r] = reasons.get(r, 0) + 1

    report = [
        f"PDFs processed      : {len(pdfs)}",
        f"Acts with sections  : {ok_files}",
        f"Sections extracted  : {n_sections}",
        f"Schedule items      : {n_schedules}",
        f"Avg sections / act  : {n_sections / ok_files:.1f}" if ok_files else "",
        f"Skipped             : {len(skipped)}",
        *[f"  - {k:22}: {v}" for k, v in sorted(reasons.items())],
    ]
    text_report = "\n".join(x for x in report if x)
    (OUT / "report.txt").write_text(text_report, encoding="utf-8")
    print("\n" + text_report)
    print(f"\nWrote {OUT / 'sections.jsonl'}")

    if args.test:
        print("\n--- sample sections ---")
        with (OUT / "sections.jsonl").open(encoding="utf-8") as f:
            for line in list(f)[:3]:
                r = json.loads(line)
                print(f"\n[{r['citation']}]  part={r['part']}  "
                      f"note={r['marginal_note']!r}")
                print(r["text"][:300])


if __name__ == "__main__":
    main()

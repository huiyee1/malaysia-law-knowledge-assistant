"""
Polite downloader for Malaysian Federal Legislation PDFs from https://lom.agc.gov.my/

Notes
-----
- The site loads its tables via server-side DataTables AJAX endpoints
  (e.g. json-updated-2024.php, json-amendment-2024.php). Each response
  embeds <a href="../../../ilims/upload/portal/akta/.../*.pdf"> links;
  we extract those and download them.
- Rate-limited (default 1 request / sec) and resumable: files that already
  exist on disk are skipped.
- Writes manifest.csv with one row per downloaded PDF for downstream RAG indexing.

Run examples
------------
  python download_lom.py --test          # 5 records per category, sanity check
  python download_lom.py --all           # full download
  python download_lom.py --categories updated,amendment
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

BASE = "https://lom.agc.gov.my"
USER_AGENT = (
    "Mozilla/5.0 (LOM-RAG-Corpus-Builder; personal research; contact: local)"
)
RATE_LIMIT_SEC = 1.0           # min seconds between any two HTTP requests
PDF_TIMEOUT_SEC = 120
JSON_TIMEOUT_SEC = 60
PAGE_SIZE = 200                # AJAX batch size per request

OUT_ROOT = Path(__file__).parent / "pdfs"
MANIFEST = Path(__file__).parent / "manifest.csv"
LOG_FILE = Path(__file__).parent / "download.log"


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

@dataclass
class Category:
    key: str                   # short id used for folder name + CLI
    label: str                 # human description
    endpoint: str              # json-*.php (relative to BASE)
    needs_language: bool = True

CATEGORIES: list[Category] = [
    Category("updated",        "Principal Acts (Updated)",       "/json-updated-2024.php"),
    Category("repealed",       "Principal Acts (Repealed)",      "/json-repealed-2024.php"),
    Category("translated",     "Principal Acts (Translated)",    "/json-translated-2024.php"),
    Category("revised",        "Principal Acts (Revised)",       "/json-revised-2024.php"),
    Category("amendment",      "Amendment Acts",                 "/json-amendment-2024.php"),
    Category("fc_amendment",   "Federal Constitution Amendments","/json-amendment-fc-2024.php"),
    Category("ordinance",      "Ordinances",                     "/json-ordinance-2024.php", needs_language=False),
]

# Federal Constitution itself: two static PDFs (not in any AJAX list).
FEDERAL_CONSTITUTION_PDFS = [
    ("BI", "/ilims/upload/portal/akta/LOM/EN/Federal Constitution (Reprint 2020).pdf"),
    ("BM", "/ilims/upload/portal/akta/LOM/MY/Perlembagaan Persekutuan (Cetakan Semula 2020).pdf"),
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
_last_request_ts = 0.0


def _throttle() -> None:
    global _last_request_ts
    now = time.time()
    delta = now - _last_request_ts
    if delta < RATE_LIMIT_SEC:
        time.sleep(RATE_LIMIT_SEC - delta)
    _last_request_ts = time.time()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_json(endpoint: str, start: int, length: int, language: str | None) -> dict:
    """POST to a DataTables JSON endpoint and return the parsed payload."""
    _throttle()
    data = {
        "draw": 1,
        "start": start,
        "length": length,
        "search[value]": "",
        "order[0][column]": 0,
        "order[0][dir]": "desc",
    }
    if language:
        data["language"] = language
    url = urljoin(BASE, endpoint)
    r = session.post(url, data=data, timeout=JSON_TIMEOUT_SEC)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# PDF URL extraction
# ---------------------------------------------------------------------------

# Matches href="../../../ilims/.../file.pdf" inside any HTML blob.
PDF_HREF_RE     = re.compile(r'href="((?:\.\./)+ilims/[^"]+?\.pdf)"', re.IGNORECASE)
PDFJS_VIEWER_RE = re.compile(r'pdfjs/web/viewer\.html\?file=((?:\.\./)+ilims/[^"&]+?\.pdf)', re.IGNORECASE)
ACT_DETAIL_RE   = re.compile(r'act-detail\.php\?act=([^&"#]+)&lang=([A-Z]+)', re.IGNORECASE)
ACT_NO_FIELDS   = ("ILA_ACT_NO", "lgt_act_no", "lgt_act_id",
                   "ACTNO_LEGISLATION", "NOMBOR_ORDINAN", "NO_ORDINAN")


def _rel_to_abs(rel: str) -> str:
    return BASE + "/" + rel.lstrip("./")


def extract_pdf_urls_from_record(record: dict) -> list[str]:
    """Pull PDF URLs from any string field in a record."""
    urls: list[str] = []
    for value in record.values():
        if not isinstance(value, str):
            continue
        for m in PDF_HREF_RE.finditer(value):
            abs_url = _rel_to_abs(m.group(1))
            if abs_url not in urls:
                urls.append(abs_url)
    return urls


def detail_page_urls(record: dict) -> list[str]:
    """For metadata-only records (repealed, translated), derive act-detail URLs."""
    urls: list[str] = []
    for value in record.values():
        if not isinstance(value, str):
            continue
        for m in ACT_DETAIL_RE.finditer(value):
            u = f"{BASE}/act-detail.php?act={m.group(1)}&lang={m.group(2)}"
            if u not in urls:
                urls.append(u)
    if not urls:
        act_no = next((str(record[k]) for k in ACT_NO_FIELDS if record.get(k)), None)
        if act_no:
            from urllib.parse import quote
            encoded = quote(act_no, safe="")
            urls = [f"{BASE}/act-detail.php?act={encoded}&lang={lang}" for lang in ("BI", "BM")]
    return urls


_detail_cache: dict[str, list[str]] = {}


def extract_pdf_urls_from_detail(detail_url: str) -> list[str]:
    if detail_url in _detail_cache:
        return _detail_cache[detail_url]
    urls: list[str] = []
    try:
        _throttle()
        r = session.get(detail_url, timeout=JSON_TIMEOUT_SEC)
        r.raise_for_status()
        html = r.text
        for m in PDFJS_VIEWER_RE.finditer(html):
            u = _rel_to_abs(m.group(1))
            if u not in urls:
                urls.append(u)
        for m in PDF_HREF_RE.finditer(html):
            u = _rel_to_abs(m.group(1))
            if u not in urls:
                urls.append(u)
    except requests.RequestException as e:
        log(f"  ERROR fetching {detail_url}: {e}")
    _detail_cache[detail_url] = urls
    return urls


def language_of(url: str) -> str:
    """Best-effort language tag from path: _BI/ -> EN, _BM/ -> MS, /EN/ /MY/, else UNK."""
    u = url.upper()
    if "_BI/" in u or "/EN/" in u:
        return "EN"
    if "_BM/" in u or "/MY/" in u:
        return "MS"
    return "UNK"


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    name = unquote(name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    return name.strip()[:200] or "untitled.pdf"


def download_pdf(url: str, dest: Path) -> tuple[bool, int]:
    """Download `url` to `dest`. Returns (downloaded, size_bytes). Skips if exists."""
    if dest.exists() and dest.stat().st_size > 0:
        return False, dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    _throttle()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=PDF_TIMEOUT_SEC) as r:
        if r.status_code != 200:
            log(f"  HTTP {r.status_code} for {url}")
            return False, 0
        ctype = r.headers.get("Content-Type", "")
        if "pdf" not in ctype.lower() and not url.lower().endswith(".pdf"):
            log(f"  Skipping non-PDF response ({ctype}) for {url}")
            return False, 0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    tmp.rename(dest)
    return True, dest.stat().st_size


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

MANIFEST_HEADERS = ["category", "language", "source_url", "local_path", "size_bytes"]


def append_manifest(rows: list[dict]) -> None:
    new_file = not MANIFEST.exists()
    with MANIFEST.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_HEADERS)
        if new_file:
            w.writeheader()
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# Per-category driver
# ---------------------------------------------------------------------------

def download_category(cat: Category, limit: int | None) -> None:
    log(f"=== {cat.label} ===")
    out_dir = OUT_ROOT / cat.key
    out_dir.mkdir(parents=True, exist_ok=True)

    # Language param: BI works for most; ordinance ignores it.
    language = "BI" if cat.needs_language else None

    head = fetch_json(cat.endpoint, 0, 1, language)
    total = head.get("recordsTotal", 0)
    if limit is not None:
        total = min(total, limit)
    log(f"  {total} records to scan via {cat.endpoint}")

    seen_urls: set[str] = set()
    manifest_rows: list[dict] = []
    fetched = 0
    start = 0

    while start < total:
        length = min(PAGE_SIZE, total - start)
        payload = fetch_json(cat.endpoint, start, length, language)
        records = payload.get("records", [])
        if not records:
            break
        for rec in records:
            pdf_urls = extract_pdf_urls_from_record(rec)
            if not pdf_urls:
                # Fallback for categories (repealed, translated) whose JSON has
                # metadata only — fetch the act-detail page and harvest pdfjs URLs.
                for detail in detail_page_urls(rec):
                    for u in extract_pdf_urls_from_detail(detail):
                        if u not in pdf_urls:
                            pdf_urls.append(u)
            for url in pdf_urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                fname = safe_filename(url.rsplit("/", 1)[-1])
                lang = language_of(url)
                dest = out_dir / lang / fname
                try:
                    downloaded, size = download_pdf(url, dest)
                except requests.RequestException as e:
                    log(f"  ERROR {url}: {e}")
                    continue
                status = "GOT " if downloaded else "skip"
                log(f"  [{status}] {dest.relative_to(OUT_ROOT)}  ({size} B)")
                manifest_rows.append({
                    "category": cat.key,
                    "language": lang,
                    "source_url": url,
                    "local_path": str(dest.relative_to(Path(__file__).parent)),
                    "size_bytes": size,
                })
                fetched += 1
        start += length

    if manifest_rows:
        append_manifest(manifest_rows)
    log(f"  done: {fetched} PDFs ({len(seen_urls)} unique URLs)")


def download_federal_constitution() -> None:
    log("=== Federal Constitution (reprint) ===")
    out_dir = OUT_ROOT / "federal_constitution"
    rows: list[dict] = []
    for lang, path in FEDERAL_CONSTITUTION_PDFS:
        url = BASE + path
        fname = safe_filename(path.rsplit("/", 1)[-1])
        dest = out_dir / lang / fname
        try:
            downloaded, size = download_pdf(url, dest)
        except requests.RequestException as e:
            log(f"  ERROR {url}: {e}")
            continue
        status = "GOT " if downloaded else "skip"
        log(f"  [{status}] {dest.relative_to(OUT_ROOT)}  ({size} B)")
        rows.append({
            "category": "federal_constitution",
            "language": "EN" if lang == "BI" else "MS",
            "source_url": url,
            "local_path": str(dest.relative_to(Path(__file__).parent)),
            "size_bytes": size,
        })
    if rows:
        append_manifest(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--all", action="store_true", help="Download every category in full.")
    p.add_argument("--test", action="store_true", help="Limit to 5 records per category (sanity check).")
    p.add_argument(
        "--categories",
        help="Comma-separated category keys to download. "
             "Available: " + ", ".join(c.key for c in CATEGORIES) + ", federal_constitution",
    )
    p.add_argument("--limit", type=int, default=None, help="Max records per category.")
    args = p.parse_args()

    if not (args.all or args.test or args.categories):
        p.print_help()
        return 1

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    log(f"Output: {OUT_ROOT}")
    log(f"Manifest: {MANIFEST}")

    limit = 5 if args.test else args.limit

    selected_keys: list[str]
    if args.categories:
        selected_keys = [k.strip() for k in args.categories.split(",") if k.strip()]
    else:
        selected_keys = ["federal_constitution"] + [c.key for c in CATEGORIES]

    for key in selected_keys:
        if key == "federal_constitution":
            download_federal_constitution()
            continue
        cat = next((c for c in CATEGORIES if c.key == key), None)
        if cat is None:
            log(f"Unknown category: {key}")
            continue
        download_category(cat, limit=limit)

    log("All done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
